#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, random, json
from collections import defaultdict, deque, namedtuple

from fractions import Fraction  # add this near the top

def _alpha_threshold_int(alpha: float, width: int) -> int:
    """
    Return floor(alpha * 2**width) using exact integer arithmetic.
    Alpha is parsed through Fraction(str(alpha)) to avoid float overflow/rounding.
    """
    if width <= 0:
        return 0
    f = Fraction(str(alpha))
    if f < 0: f = Fraction(0, 1)
    if f > 1: f = Fraction(1, 1)
    # floor( (num/den) * 2**width ) = (num * 2**width) // den
    return (f.numerator << width) // f.denominator

GATE_TYPES = {"AND","NAND","OR","NOR","XOR","XNOR","NOT","BUF"}
Gate = namedtuple("Gate", ["op","inputs"])

# ----------------- Core circuit -----------------
class Circuit:
    def __init__(self):
        self.inputs = []   # list[str]
        self.outputs = []  # list[str]
        self.gates = {}    # name -> Gate(op, inputs)
        self.dffs  = []    # list[(Q, D)]
        self.topo_order = []

    @staticmethod
    def from_bench(path):
        import re
        c = Circuit()
        re_in   = re.compile(r'^\s*INPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
        re_out  = re.compile(r'^\s*OUTPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
        re_dff  = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*DFF\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
        re_gate = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*([A-Z]+)\s*\(\s*([A-Za-z0-9_\s,]+)\s*\)\s*$')
        with open(path,'r') as f:
            for line in f:
                line = line.split('#',1)[0].strip()
                if not line: continue
                m = re_in.match(line)
                if m: c.inputs.append(m.group(1)); continue
                m = re_out.match(line)
                if m: c.outputs.append(m.group(1)); continue
                m = re_dff.match(line)
                if m: c.dffs.append((m.group(1), m.group(2))); continue
                m = re_gate.match(line)
                if m:
                    name, op, argstr = m.group(1), m.group(2).upper(), m.group(3)
                    args = [a.strip() for a in argstr.split(',') if a.strip()]
                    if op in GATE_TYPES:
                        c.gates[name] = Gate(op, args)
        c.compute_topo()
        return c

    def compute_topo(self):
        indeg = defaultdict(int); adj = defaultdict(list)
        nodes = set(self.inputs) | set(q for q,_ in self.dffs) | set(self.gates.keys())
        for n,g in self.gates.items():
            for x in g.inputs:
                adj[x].append(n)
                indeg[n]+=1
                indeg.setdefault(x,0)
        for n in list(nodes): indeg.setdefault(n,0)
        dq = deque([n for n in nodes if indeg[n]==0]); order=[]; seen=set()
        while dq:
            u = dq.popleft(); order.append(u); seen.add(u)
            for v in adj[u]:
                indeg[v]-=1
                if indeg[v]==0 and v not in seen: dq.append(v)
        self.topo_order = [n for n in order if n in self.gates]

    def eval_comb(self, inputs_map, state_map):
        val = {}; val.update(state_map); val.update(inputs_map)
        for n in self.topo_order:
            op,ins = self.gates[n].op,[val.get(x,0) for x in self.gates[n].inputs]
            if   op=="AND": v=1;  [(_:= (v:=v&a)) for a in ins]
            elif op=="NAND":v=1;  [(_:= (v:=v&a)) for a in ins]; v^=1
            elif op=="OR":  v=0;  [(_:= (v:=v|a)) for a in ins]
            elif op=="NOR": v=0;  [(_:= (v:=v|a)) for a in ins]; v^=1
            elif op=="XOR": v=0;  [(_:= (v:=v^a)) for a in ins]
            elif op=="XNOR":v=0;  [(_:= (v:=v^a)) for a in ins]; v^=1
            elif op=="NOT": v=0 if ins[0] else 1
            elif op=="BUF": v=ins[0]
            else: v=0
            val[n]=v
        y={o:val.get(o,0) for o in self.outputs}
        dnext={q:val.get(d,0) for (q,d) in self.dffs}
        return y,dnext

    def simulate(self, inputs_seq, cycles=None):
        if cycles is None: cycles = len(inputs_seq)
        state = {q:0 for q,_ in self.dffs}; out=[]
        for t in range(cycles):
            y, dn = self.eval_comb(inputs_seq[t] if t<len(inputs_seq) else {}, state)
            out.append(y)
            for q in state: state[q] = dn.get(q,0)
        return out

    def add_gate(self, name, op, inputs): self.gates[name] = Gate(op, list(inputs))
    def add_dff(self, qname, dname): self.dffs.append((qname, dname))
    def replace_signal_uses(self, old, new):
        for n,g in list(self.gates.items()):
            ins = [new if x==old else x for x in g.inputs]
            if ins != g.inputs: self.gates[n] = Gate(g.op, ins)
        self.dffs = [(q, (new if d==old else d)) for (q,d) in self.dffs]
        self.compute_topo()

# ----------------- TriLock simulator (unchanged) -----------------
def random_stimuli(pi_names, T, rng): return [{pi:rng.randint(0,1) for pi in pi_names} for _ in range(T)]
def fc_rate(y0,y1):
    tot=0; diff=0
    for a,b in zip(y0,y1):
        for k in a.keys():
            tot+=1
            if a[k]!=b[k]: diff+=1
    return diff/tot if tot else 0.0

class TriLockExact:
    def __init__(self, circuit, ks, kf, alpha, seed=0, po_fraction=1.0):
        self.c=circuit; self.ks=int(ks); self.kf=int(kf); self.k=self.ks+self.kf
        self.alpha=float(alpha); self.PI=list(self.c.inputs); self.PO=list(self.c.outputs)
        random.seed(int(seed))
        self.k_star=[[random.randint(0,1) for _ in self.PI] for _ in range(self.k)]
        if self.kf>0:
            suf=self.k_star[self.ks:]
            while True:
                cand=[[random.randint(0,1) for _ in self.PI] for _ in range(self.kf)]
                if cand!=suf: self.k_starstar=cand; break
        else: self.k_starstar=[]
        m=max(1,int(round(po_fraction*len(self.PO)))) if self.PO else 0
        idx=list(range(len(self.PO))); random.shuffle(idx); self.po_idx=set(idxs[:m]) if (idxs:=idx) else set()
    def correct_key(self): return [list(b) for b in self.k_star]
    def random_wrong_key(self):
        k=self.correct_key()
        if self.k>0 and len(self.PI)>0:
            i=random.randrange(self.k); j=random.randrange(len(self.PI)); k[i][j]^=1
        return k
    def rank_suffix(self, i_bits, k_bits):
        v=0
        for b in (i_bits+k_bits): v=(v<<1)|(1 if b else 0)
        return v
    def es_flag_at_t(self, t, key_blocks, input_blocks):
        if self.k==0 or t!=self.ks-1 or key_blocks==self.k_star: return 0
        for j in range(self.ks):
            if key_blocks[j]!=input_blocks[j]: return 0
        return 1
    def ef_flag_at_t(self, t, key_blocks, input_blocks):
        # Guard conditions unchanged
        if self.k == 0 or t < self.ks or t >= self.k or key_blocks == self.k_star or self.kf == 0:
            return 0
        if key_blocks[self.ks:] == self.k_starstar:
            return 0

        # Build suffix vectors
        i_bits = [b for blk in input_blocks[self.ks:] for b in blk]
        k_bits = [b for blk in key_blocks[self.ks:] for b in blk]
        W = self.kf * len(self.PI)
        if W == 0:
            return 0

        # Compute rank modulo 2**W without ever overflowing
        mask = (1 << W) - 1
        R = 0
        for b in (i_bits + k_bits):
            R = ((R << 1) | (1 if b else 0)) & mask

        # Exact integer threshold: T = floor(alpha * 2**W)
        T = _alpha_threshold_int(self.alpha, W)

        return 1 if R < T else 0

    def flip_outputs(self, y):
        if not self.po_idx: return y
        y2=dict(y)
        for i,name in enumerate(self.PO):
            if i in self.po_idx: y2[name]=1-y2.get(name,0)
        return y2
    def simulate_locked(self, inputs_seq, key_blocks):
        blocks=[[int(v.get(pi,0)) for pi in self.PI] for v in inputs_seq]; out=[]
        for t in range(len(inputs_seq)):
            if self.k>0:
                pos=t%self.k; cstart=t-pos
                win=[(blocks[cstart+j] if (cstart+j)<len(blocks) else [0]*len(self.PI)) for j in range(self.k)]
                es=self.es_flag_at_t(pos,key_blocks,win); ef=self.ef_flag_at_t(pos,key_blocks,win)
                flip=1 if (es or ef) else 0
            else: flip=0
            out.append((t,flip))
        return out

# ----------------- RCG & SCC -----------------
def build_rcg(circ: Circuit):
    consumers = defaultdict(set)
    for n,g in circ.gates.items():
        for x in g.inputs: consumers[x].add(n)
    for q,d in circ.dffs: consumers[d].add(("DFF_D", q))
    adj = defaultdict(set)
    for q,_ in circ.dffs:
        dq=deque([q]); seen=set()
        while dq:
            s=dq.popleft()
            if s in seen: continue
            seen.add(s)
            for cons in consumers[s]:
                if isinstance(cons,tuple) and cons[0]=="DFF_D": adj[q].add(cons[1])
                else: dq.append(cons)
    for q,_ in circ.dffs: adj.setdefault(q,set())
    return adj

def strongly_connected_components(adj):
    nodes=set(adj.keys()); [nodes.update(v) for v in adj.values()]
    index=0; stack=[]; on=set(); idx={}; low={}; sccs=[]
    def dfs(v):
        nonlocal index
        idx[v]=index; low[v]=index; index+=1
        stack.append(v); on.add(v)
        for w in adj.get(v,[]):
            if w not in idx: dfs(w); low[v]=min(low[v],low[w])
            elif w in on:   low[v]=min(low[v],idx[w])
        if low[v]==idx[v]:
            comp=[]
            while True:
                w=stack.pop(); on.discard(w); comp.append(w)
                if w==v: break
            sccs.append(comp)
    for v in list(nodes):
        if v not in idx: dfs(v)
    return sccs

# ----------------- M-SCG (guarantee Mixed SCCs) -----------------
def apply_enc_dec_pair(circ: Circuit, ro: str, re: str, pair_idx: int):
    # enc/dec on RAW Q nets
    e = f"ENC_{pair_idx}__XOR_{ro}_{re}"
    dec_ro = f"DEC_{pair_idx}__{ro}"
    dec_re = f"DEC_{pair_idx}__{re}"
    circ.add_gate(e,      "XOR", [ro, re])
    circ.add_gate(dec_ro, "XOR", [e,  re])  # == ro
    circ.add_gate(dec_re, "XOR", [e,  ro])  # == re

    # selective downstream redirection (skip enc/dec)
    skip = {e, dec_ro, dec_re}
    updated = {}
    for n,g in list(circ.gates.items()):
        if n in skip: continue
        ins2 = [(dec_ro if x==ro else dec_re if x==re else x) for x in g.inputs]
        if ins2 != g.inputs: updated[n] = Gate(g.op, ins2)
    for n,g2 in updated.items(): circ.gates[n] = g2
    circ.dffs = [(q, (dec_ro if d==ro else dec_re if d==re else d)) for (q,d) in circ.dffs]

    # zero-effect cross-dependencies using RAW ro/re
    d_map = {q:d for (q,d) in circ.dffs}
    dro = d_map.get(ro); dre = d_map.get(re)
    if dre is not None:
        znot_ro=f"ZERO_NOT__{pair_idx}__{ro}"
        zero_ro=f"ZERO_AND__{pair_idx}__{ro}"
        dre_new=f"D_WRAP__{pair_idx}__{re}"
        circ.add_gate(znot_ro,"NOT",[ro])
        circ.add_gate(zero_ro,"AND",[ro,znot_ro])   # ==0
        circ.add_gate(dre_new,"XOR",[dre,zero_ro])  # preserve
        circ.dffs = [(q,(dre_new if q==re else d)) for (q,d) in circ.dffs]
    if dro is not None:
        znot_re=f"ZERO_NOT__{pair_idx}__{re}"
        zero_re=f"ZERO_AND__{pair_idx}__{re}"
        dro_new=f"D_WRAP__{pair_idx}__{ro}"
        circ.add_gate(znot_re,"NOT",[re])
        circ.add_gate(zero_re,"AND",[re,znot_re])   # ==0
        circ.add_gate(dro_new,"XOR",[dro,zero_re])  # preserve
        circ.dffs = [(q,(dro_new if q==ro else d)) for (q,d) in circ.dffs]
    circ.compute_topo()

def run_reencoding(circ: Circuit, extra_regs: list, S_pairs: int):
    orig_regs = [q for q,_ in circ.dffs if q not in extra_regs]
    pairs = list(zip(orig_regs[:S_pairs], extra_regs[:S_pairs]))
    for idx,(ro,re) in enumerate(pairs): apply_enc_dec_pair(circ, ro, re, idx)
    return pairs

def classify_sccs(circ: Circuit, extra_regs: set):
    adj = build_rcg(circ); sccs = strongly_connected_components(adj)
    O,E,M = [],[],[]; regset=set(q for q,_ in circ.dffs); seen=set()
    for comp in sccs:
        regs = [r for r in comp if r in regset]
        if not regs: continue
        seen.update(regs)
        has_o = any(r not in extra_regs for r in regs)
        has_e = any(r in extra_regs for r in regs)
        if has_o and has_e: M.append(sorted(regs))
        elif has_o: O.append(sorted(regs))
        elif has_e: E.append(sorted(regs))
    for r in sorted(extra_regs):
        if r in regset and r not in seen: E.append([r])
    return O,E,M

# ----------------- Structural keyed error generator -----------------
def _add_const01(circ: Circuit, anchor_sig: str):
    # CONST0 = AND(a, NOT(a)); CONST1 = NOT(CONST0)
    cn = "CONST0_ANCHOR_NOT"; c0="CONST0"; c1="CONST1"
    circ.add_gate(cn, "NOT", [anchor_sig])
    circ.add_gate(c0, "AND", [anchor_sig, cn])
    circ.add_gate(c1, "NOT", [c0])
    return c0, c1

def _xnor(circ, a, b, name):
    # If XNOR gate available, use directly
    xn = f"{name}"
    circ.add_gate(xn, "XNOR", [a,b])
    return xn

def _and_list(circ, sigs, base):
    if not sigs:
        return None
    cur = sigs[0]
    for i,s in enumerate(sigs[1:], 1):
        n = f"{base}__AND{i}"
        circ.add_gate(n, "AND", [cur, s])
        cur = n
    return cur

def _or_list(circ, sigs, base):
    if not sigs:
        return None
    cur = sigs[0]
    for i,s in enumerate(sigs[1:], 1):
        n = f"{base}__OR{i}"
        circ.add_gate(n, "OR", [cur, s])
        cur = n
    return cur

def _not(circ, a, name):
    n = f"{name}__NOT"
    circ.add_gate(n, "NOT", [a]); return n

def _lt_const(circ: Circuit, vec_bits, T_bits, base):
    """
    Build comparator: A < T  (A, T MSB-first arrays)
    Uses recurrence:
      less = less OR (eq AND (~A[i] AND T[i]))
      eq   = eq AND XNOR(A[i], T[i])
    """
    assert len(vec_bits)==len(T_bits)
    N = len(vec_bits)
    # initialize eq=1, less=0
    _, ONE = _add_const01(circ, vec_bits[0])
    eq = ONE; less = None
    for idx in range(N):
        i = idx  # MSB-first assumed
        a = vec_bits[i]; t = T_bits[i]
        na = _not(circ, a, f"{base}__A{i}")
        na_and_t = f"{base}__A{i}_ltbit"
        circ.add_gate(na_and_t, "AND", [na, t])
        eq_and_lt = f"{base}__EQ_AND_LT{i}"
        circ.add_gate(eq_and_lt, "AND", [eq, na_and_t])
        less = eq_and_lt if less is None else (lambda prev=less, cur=eq_and_lt: circ.add_gate(f"{base}__LESS_OR{i}", "OR", [prev, cur]) or f"{base}__LESS_OR{i}")()
        xni = _xnor(circ, a, t, f"{base}__XNOR{i}")
        eqn = f"{base}__EQ{i}"
        circ.add_gate(eqn, "AND", [eq, xni])
        eq = eqn
    return less

def add_keyed_error_logic(circ: Circuit, ks: int, kf: int, alpha: float, po_fraction: float, seed: int):
    """
    Adds KEY_* ports and synthesizes ES/EF/ESF structurally:
      - k-deep PI history via shift registers
      - ES = prefix(history) == key_prefix AND key != k*
      - EF = (key_suffix != k**) AND (suffix_inputs < T)
      - ESF flips a fraction of POs
    """
    rng = random.Random(seed)
    k = ks + kf
    pis = list([n for n in circ.inputs])  # base PIs before adding keys
    P = len(pis)

    # 1) Add KEY_* inputs
    key_names = []
    for b in range(k):
        for i in range(P):
            kn = f"KEY_B{b}_I{i}"
            key_names.append(kn)
            if kn not in circ.inputs:
                circ.inputs.append(kn)

    # 2) Build k-stage PI history (stage 0 = current; stage j = j-th previous)
    hist = [[None for _ in range(P)] for __ in range(k)]
    for i,pi in enumerate(pis):
        # stage 0 DFF
        q0 = f"PIHIST_B0_I{i}"
        circ.add_dff(q0, pi)
        hist[0][i] = q0
        for b in range(1, k):
            qb = f"PIHIST_B{b}_I{i}"
            circ.add_dff(qb, hist[b-1][i])
            hist[b][i] = qb

    # Constants & secret key constants
    # anchor on first available signal (PI 0)
    anchor = pis[0] if pis else key_names[0]
    C0, C1 = _add_const01(circ, anchor)
    # k* and k** constants realized as CONST0/CONST1 nets
    kstar = {}    # (b,i) -> const net name
    kstar2 = {}   # suffix only (b >= ks)
    for b in range(k):
        for i in range(P):
            bit = rng.randint(0,1)
            kstar[(b,i)] = C1 if bit==1 else C0
    for b in range(ks, k):
        for i in range(P):
            bit = rng.randint(0,1)
            kstar2[(b,i)] = C1 if bit==1 else C0

    # 3) ES: prefix(history) == key_prefix AND key != k*
    es_eq_bits = []
    ck_eq_bits = []
    for b in range(ks):
        for i in range(P):
            es_eq_bits.append(_xnor(circ, hist[b][i], f"KEY_B{b}_I{i}", f"ES_XNOR_B{b}_I{i}"))
            ck_eq_bits.append(_xnor(circ, f"KEY_B{b}_I{i}", kstar[(b,i)], f"KSTAR_XNOR_B{b}_I{i}"))
    for b in range(ks, k):
        for i in range(P):
            ck_eq_bits.append(_xnor(circ, f"KEY_B{b}_I{i}", kstar[(b,i)], f"KSTAR_XNOR_B{b}_I{i}"))

    es_prefix_eq = _and_list(circ, es_eq_bits, "ES_PREFIX_EQ") if es_eq_bits else None
    ck_eq_all   = _and_list(circ, ck_eq_bits, "CK_EQ_ALL")     if ck_eq_bits else None
    not_ck_eq   = _not(circ, ck_eq_all, "NOT_CK_EQ") if ck_eq_all else None
    ES = None
    if es_prefix_eq and not_ck_eq:
        ES = f"ES_FLAG"
        circ.add_gate(ES, "AND", [es_prefix_eq, not_ck_eq])
    else:
        ES = None

    # 4) EF: (key_suffix != k**) AND (suffix_inputs < T)
    EF = None
    if kf > 0:
        # key_suffix != k**
        suf_eq_bits = []
        for b in range(ks, k):
            for i in range(P):
                suf_eq_bits.append(_xnor(circ, f"KEY_B{b}_I{i}", kstar2[(b,i)], f"K2_XNOR_B{b}_I{i}"))
        suf_eq = _and_list(circ, suf_eq_bits, "SUF_EQ") if suf_eq_bits else None
        not_suf_eq = _not(circ, suf_eq, "NOT_SUF_EQ") if suf_eq else None

        # suffix_inputs vector (MSB-first): B=ks..k-1, i=0..P-1
        vec = []
        for b in range(ks, k):
            for i in range(P):
                vec.append(hist[b][i])
        W = len(vec)
        # threshold T = floor(alpha * 2^W)
        T_val = _alpha_threshold_int(alpha, W)  # exact integer threshold

        # T bits MSB-first
        T_bits = []
        for j in reversed(range(W)):
            T_bits.append(C1 if ((T_val>>j)&1) else C0)
        # A < T comparator
        A_lt_T = _lt_const(circ, vec_bits=vec, T_bits=T_bits, base="EF_CMP")

        # wrong key (reuse not_ck_eq)
        if A_lt_T and not_suf_eq and not_ck_eq:
            tmp = "EF_KGATE"
            circ.add_gate(tmp, "AND", [not_suf_eq, not_ck_eq])
            EF = "EF_FLAG"
            circ.add_gate(EF, "AND", [tmp, A_lt_T])

    # 5) ESF and PO flipping
    if ES and EF:
        ESF = "ESF_FLAG"
        circ.add_gate(ESF, "OR", [ES, EF])
    else:
        ESF = ES or EF  # whichever exists

    if ESF:
        m = max(1, int(round(po_fraction*len(circ.outputs)))) if circ.outputs else 0
        # flip first m outputs (or all if po_fraction ~ 1.0)
        for idx,name in enumerate(list(circ.outputs)):
            if idx < m:
                xo = f"POLOCK_{name}"
                circ.add_gate(xo, "XOR", [name, ESF])
                circ.outputs[idx] = xo

    circ.compute_topo()

# ----------------- Writers -----------------
def write_bench(circ: Circuit, out_path: str, meta: dict = None):
    lines=[]
    if meta:
        lines.append("# === TriLock Locked Bench ===")
        for k,v in meta.items(): lines.append(f"# {k}: {v}")
        lines.append("# ============================")
    for name in circ.inputs:  lines.append(f"INPUT({name})")
    for name in circ.outputs: lines.append(f"OUTPUT({name})")
    gate_names = circ.topo_order if getattr(circ,"topo_order",None) else sorted(circ.gates.keys())
    for n in gate_names:
        if n in circ.gates:
            g = circ.gates[n]
            lines.append(f"{n} = {g.op}({','.join(g.inputs)})")
    for (q,d) in circ.dffs: lines.append(f"{q} = DFF({d})")
    with open(out_path,"w") as f:
        f.write("\n".join(lines) + "\n")

# ----------------- CLI -----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--ks", type=int, default=3)
    ap.add_argument("--kf", type=int, default=3)
    ap.add_argument("--alpha", type=float, default=0.2)
    ap.add_argument("--po-fraction", type=float, default=1.0)
    ap.add_argument("--validate", type=int, default=200)
    ap.add_argument("--wrong-keys", type=int, default=4)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--extra-count", type=int, default=3)
    ap.add_argument("--reencode-pairs", type=int, default=3)
    ap.add_argument("--out-bench", type=str, default="", help="Write M-SCG-only locked .bench")
    ap.add_argument("--emit-keyed-bench", type=str, default="", help="Write locked .bench with KEY_* ports and active keyed logic")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    circ = Circuit.from_bench(args.bench)

    # Insert extra regs (E-regs)
    extra_regs = []
    for i in range(args.extra_count):
        q = f"EXTRA_R{i}"; buf = f"EXTRA_BUF_{i}"
        circ.add_gate(buf, "BUF", [q]); circ.add_dff(q, buf); extra_regs.append(q)

    # Re-encode pairs (M-SCG)
    pairs = run_reencoding(circ, extra_regs, min(args.reencode_pairs, len(extra_regs)))

    # Report SCC classes AFTER re-encoding
    O1,E1,M1 = classify_sccs(circ, set(extra_regs))
    print("=== TriLock State Re-encoding: SCC classes AFTER re-encoding ===")
    print(f"O-SCC (#={len(O1)}):"); [print("  O:", comp) for comp in O1]
    print(f"E-SCC (#={len(E1)}):"); [print("  E:", comp) for comp in E1]
    print(f"M-SCC (#={len(M1)}):"); [print("  M:", comp) for comp in M1]

    # Behavioral validation (sim-only) to estimate FC trends
    stim = random_stimuli(circ.inputs, args.validate, rng)
    y0 = circ.simulate(stim, cycles=args.validate)
    tri = TriLockExact(circ, args.ks, args.kf, args.alpha, seed=args.seed, po_fraction=args.po_fraction)
    k_ok = tri.correct_key(); flips_ok = tri.simulate_locked(stim, k_ok)
    y_ok = [ tri.flip_outputs(y0[t]) if flip else y0[t] for t,flip in flips_ok ]
    fc_ok = fc_rate(y0, y_ok)
    fcs=[]
    for _ in range(args.wrong_keys):
        kw = tri.random_wrong_key(); flips = tri.simulate_locked(stim, kw)
        yb = [ tri.flip_outputs(y0[t]) if flip else y0[t] for t,flip in flips ]
        fcs.append(fc_rate(y0, yb))
    print("\n=== TriLock ES/EF Validation ===")
    print(json.dumps({
        "PIs": len([n for n in circ.inputs if not n.startswith('KEY_')]),
        "KEY_PIs": len([n for n in circ.inputs if n.startswith('KEY_')]),
        "POs": len(circ.outputs), "DFFs": len(circ.dffs),
        "extra_inserted": len(extra_regs), "reencoded_pairs": len(pairs),
        "ks": args.ks, "kf": args.kf, "alpha": args.alpha,
        "correct_key_FC": fc_ok,
        "wrong_key_avg_FC": (sum(fcs)/len(fcs)) if fcs else 0.0
    }, indent=2))

    # Emit M-SCG only
    if args.out_bench:
        write_bench(circ, args.out_bench, {"extra_count": len(extra_regs), "reencode_pairs": len(pairs)})
        print(f"Locked bench written to: {args.out_bench}")

    # Emit fully keyed bench (adds KEY_* ports and active keyed logic)
    if args.emit_keyed_bench:
        add_keyed_error_logic(circ, args.ks, args.kf, args.alpha, args.po_fraction, args.seed)
        meta = {
            "extra_count": len(extra_regs),
            "reencode_pairs": len(pairs),
            "key_blocks": args.ks + args.kf,
            "key_inputs": (args.ks + args.kf) * len([n for n in circ.inputs if not n.startswith("KEY_")])
        }
        write_bench(circ, args.emit_keyed_bench, meta)
        print(f"Keyed locked bench written to: {args.emit_keyed_bench}")

if __name__ == "__main__":
    main()
