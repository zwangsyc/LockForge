#!/usr/bin/env python3
import argparse, re, random

def parse_bench(p):
    lines = [l.rstrip() for l in open(p, "r") if l.strip()]
    inputs, outputs, assigns, others, flops = [], [], {}, [], set()
    r_in = re.compile(r'^\s*INPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$', re.I)
    r_out= re.compile(r'^\s*OUTPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$', re.I)
    r_dff= re.compile(r'^\s*DFF\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$', re.I)
    r_eq = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*(.+)$')
    for l in lines:
        m=r_in.match(l)
        if m: inputs.append(m.group(1)); continue
        m=r_out.match(l)
        if m: outputs.append(m.group(1)); continue
        m=r_dff.match(l)
        if m: flops.add(m.group(1)); others.append(l); continue
        m=r_eq.match(l)
        if m:
            assigns[m.group(1)] = m.group(2).strip(); continue
        others.append(l)
    return inputs, outputs, assigns, others, flops

def uniq(name, used):
    if name not in used: return name
    i=1
    while f"{name}_{i}" in used: i+=1
    return f"{name}_{i}"

class Flat:
    def __init__(self, used):
        self.used = set(used)
        self.lines = []
        self._ctr = 0
    def w(self, s):
        self.lines.append(s)
        return s.split("=",1)[0].strip()
    def tmp(self, base="W"):
        n = uniq(f"{base}{self._ctr}", self.used)
        self.used.add(n); self._ctr += 1
        return n
    def NOT(self, a):
        n = self.tmp("N")
        self.w(f"{n} = NOT({a})")
        return n
    def AND(self, a, b):
        n = self.tmp("A")
        self.w(f"{n} = AND({a},{b})")
        return n
    def OR(self, a, b):
        n = self.tmp("O")
        self.w(f"{n} = OR({a},{b})")
        return n
    def XOR(self, a, b):
        n = self.tmp("X")
        self.w(f"{n} = XOR({a},{b})")
        return n
    def BUF(self, a):
        n = self.tmp("B")
        self.w(f"{n} = BUF({a})")
        return n
    def reduce_or(self, sigs):
        if not sigs: return "0"
        cur = sigs[0]
        for s in sigs[1:]:
            cur = self.OR(cur, s)
        return cur
    def reduce_xor(self, sigs):
        if not sigs: return "0"
        cur = sigs[0]
        for s in sigs[1:]:
            cur = self.XOR(cur, s)
        return cur

def emit_full_flat(in_path, out_path, obf_bits, auth_bits, num_se, seed):
    rng = random.Random(seed)
    pis, pos, assigns, others, flops = parse_bench(in_path)
    used = set(pis)|set(pos)|set(assigns.keys())|set(flops)
    KEY = uniq("KEY", used); used.add(KEY)
    RST = uniq("RST", used); used.add(RST)
    SCAN = uniq("SCAN_EN", used); used.add(SCAN)
    TEST = uniq("TEST_MODE", used); used.add(TEST)
    TKEY = uniq("TEST_KEY_OK", used); used.add(TKEY)

    flat = Flat(used)

    se_bits = [uniq(f"SE{i}", used) for i in range(max(1,num_se))]
    for n in se_bits: used.add(n)
    se_next = [uniq(f"{n}_D", used) for n in se_bits]
    for n in se_next: used.add(n)

    fb = flat.reduce_xor(se_bits) if len(se_bits)>1 else se_bits[0]
    flat.w(f"{se_next[0]} = {fb}")
    for i in range(1,len(se_bits)):
        flat.w(f"{se_next[i]} = {se_bits[i-1]}")

    ctrl_O = [uniq(f"OBF_S{i}", used) for i in range(len(obf_bits))]
    for n in ctrl_O: used.add(n)
    ctrl_A = [uniq(f"AUTH_S{i}", used) for i in range(len(auth_bits))]
    for n in ctrl_A: used.add(n)
    CTRL_U = uniq("UNLOCKED", used); used.add(CTRL_U)
    CTRL_T = uniq("TRAP", used); used.add(CTRL_T)

    eq_obf = []
    for i,b in enumerate(obf_bits):
        eq = uniq(f"EQ_OBF_{i}", used); used.add(eq)
        flat.w(f"{eq} = {'BUF('+KEY+')' if b==1 else 'NOT('+KEY+')'}")
        eq_obf.append(eq)
    eq_auth = []
    for i,b in enumerate(auth_bits):
        eq = uniq(f"EQ_AUTH_{i}", used); used.add(eq)
        flat.w(f"{eq} = {'BUF('+KEY+')' if b==1 else 'NOT('+KEY+')'}")
        eq_auth.append(eq)

    rst_n = flat.NOT(RST)

    if ctrl_O:
        flat.w(f"{ctrl_O[0]} = OR({RST},0)")
        for i in range(1,len(ctrl_O)):
            t1 = flat.AND(rst_n, ctrl_O[i-1])
            t2 = flat.AND(t1, eq_obf[i-1])
            flat.w(f"{ctrl_O[i]} = BUF({t2})")

    if ctrl_O and ctrl_A:
        t = flat.AND(rst_n, ctrl_O[-1])
        t = flat.AND(t, eq_obf[-1])
        flat.w(f"{ctrl_A[0]} = BUF({t})")
        for j in range(1,len(ctrl_A)):
            t1 = flat.AND(rst_n, ctrl_A[j-1])
            t2 = flat.AND(t1, eq_auth[j-1])
            flat.w(f"{ctrl_A[j]} = BUF({t2})")

    terms_U = []
    if ctrl_A:
        t = flat.AND(rst_n, ctrl_A[-1])
        t = flat.AND(t, eq_auth[-1])
        terms_U.append(t)
    t_hold = flat.AND(rst_n, CTRL_U)
    terms_U.append(t_hold)
    U_expr = flat.reduce_or(terms_U)
    flat.w(f"{CTRL_U} = BUF({U_expr})")

    terms_T = []
    for i,s in enumerate(ctrl_O):
        nbit = flat.NOT(eq_obf[i])
        terms_T.append(flat.AND(s, nbit))
    for j,s in enumerate(ctrl_A):
        nbit = flat.NOT(eq_auth[j])
        terms_T.append(flat.AND(s, nbit))
    terms_T.append(flat.AND(rst_n, SCAN))
    terms_T.append(flat.AND(rst_n, CTRL_T))
    T_expr = flat.reduce_or(terms_T)
    flat.w(f"{CTRL_T} = BUF({T_expr})")

    BYPASS = uniq("BYPASS_OK", used); used.add(BYPASS)
    flat.w(f"{BYPASS} = BUF({flat.AND(TEST, TKEY)})")
    R_eff = uniq("R_EFF", used); used.add(R_eff)
    flat.w(f"{R_eff} = BUF({flat.OR(CTRL_U, BYPASS)})")
    E_eff = uniq("E_EFF", used); used.add(E_eff)
    flat.w(f"{E_eff} = BUF({flat.NOT(R_eff)})")

    pi_alias = {}
    for i,pi in enumerate(pis):
        m = uniq(f"{pi}_M", used); used.add(m)
        a = uniq(f"{pi}_LOCK", used); used.add(a)
        bit = se_bits[i % len(se_bits)]
        t_mask = flat.AND(E_eff, bit)
        flat.w(f"{m} = BUF({t_mask})")
        t_x = flat.XOR(pi, m)
        flat.w(f"{a} = BUF({t_x})")
        pi_alias[pi] = a

    se_x = flat.reduce_xor(se_bits)
    flop_list = sorted(list(flops))
    alpha_sel = flop_list[:min(8, len(flop_list))]
    if alpha_sel:
        alpha = alpha_sel[0]
        for n in alpha_sel[1:]:
            alpha = flat.XOR(alpha, n)
    else:
        alpha = "0"
    corr = uniq("CORR", used); used.add(corr)
    flat.w(f"{corr} = BUF({flat.XOR(se_x, alpha)})")
    corr_g = uniq("CORR_G", used); used.add(corr_g)
    flat.w(f"{corr_g} = BUF({flat.AND(E_eff, corr)})")

    new_assigns = {}
    for k,v in list(assigns.items()):
        new_rhs = v
        for pi,ali in pi_alias.items():
            new_rhs = re.sub(rf'\\b{re.escape(pi)}\\b', ali, new_rhs)
        new_assigns[k] = new_rhs
    assigns = new_assigns

    ren_po = {o: uniq(f"{o}_ORIG", used) for o in pos}
    for n in ren_po.values(): used.add(n)

    out = []
    for n in pis: out.append(f"INPUT({n})")
    for n in [KEY, RST, SCAN, TEST, TKEY]: out.append(f"INPUT({n})")
    for n in pos: out.append(f"OUTPUT({n})")
    for l in others:
        if l.startswith("INPUT(") or l.startswith("OUTPUT("): continue
        out.append(l)

    for n in se_bits: out.append(f"DFF({n})")
    for n in ctrl_O: out.append(f"DFF({n})")
    for n in ctrl_A: out.append(f"DFF({n})")
    out.append(f"DFF({CTRL_U})")
    out.append(f"DFF({CTRL_T})")

    for k,v in assigns.items():
        if k in ren_po:
            out.append(f"{ren_po[k]} = {v}")
        else:
            out.append(f"{k} = {v}")

    for o in pos:
        if ren_po[o] not in [lhs.split('=',1)[0].strip() for lhs in out if '=' in lhs]:
            out.append(f"{ren_po[o]} = BUF({o})")
        tmp = flat.XOR(ren_po[o], corr_g)
        out.append(f"{o} = BUF({tmp})")

    out.extend(flat.lines)

    with open(out_path, "w") as f:
        f.write("\n".join(out) + "\n")

def parse_bits_csv(s):
    if not s: return []
    return [int(x) for x in s.split(",") if x!=""]

def main():
    ap = argparse.ArgumentParser(description="Emit a full HARPOON-locked .bench (flattened, no nested gates)")
    ap.add_argument("--in", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--obf-seq", default="1,0,1")
    ap.add_argument("--auth-seq", default="1,1")
    ap.add_argument("--num-se", type=int, default=4)
    ap.add_argument("--seed", type=int, default=2025)
    args = ap.parse_args()
    emit_full_flat(args.__dict__["in"], args.out, parse_bits_csv(args.obf_seq), parse_bits_csv(args.auth_seq), args.num_se, args.seed)

if __name__ == "__main__":
    main()
