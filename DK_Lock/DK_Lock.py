#!/usr/bin/env python3
import argparse, random, re
from collections import defaultdict, OrderedDict, deque

GATE_TYPES = {"AND","NAND","OR","NOR","XOR","XNOR","NOT","BUF","DFF"}

class Bench:
    def __init__(self):
        self.inputs=[]; self.outputs=[]; self.nodes=OrderedDict()
    def add_input(self,n):
        if n not in self.inputs: self.inputs.append(n)
    def add_output(self,n):
        self.outputs.append(n)
    def add_node(self,name,typ,fins):
        if typ not in GATE_TYPES: raise ValueError(f"Unknown gate {typ}")
        self.nodes[name]=(typ,fins[:])
    @staticmethod
    def parse(path):
        b=Bench()
        text=open(path,"r",encoding="utf-8",errors="ignore").read()
        text=re.sub(r"#.*","",text)
        def alias(op): op=op.upper(); return {"INV":"NOT","BUFF":"BUF"}.get(op,op)
        token_pat=re.compile(r"""
            INPUT\(\s*(?P<input>[A-Za-z0-9_]+)\s*\)
            |
            OUTPUT\(\s*(?P<output>[A-Za-z0-9_]+)\s*\)
            |
            (?P<name>[A-Za-z0-9_]+)\s*=\s*
            (?P<op>[A-Za-z0-9_]+)\s*\(
                \s*(?P<args>[A-Za-z0-9_,\s]*)\s*
            \)
        """, re.VERBOSE)
        for m in token_pat.finditer(text):
            if m.group("input"):
                b.add_input(m.group("input")); continue
            if m.group("output"):
                b.add_output(m.group("output")); continue
            name=m.group("name"); op=alias(m.group("op")); args=m.group("args")
            fins=[] if args.strip()=="" else [a.strip() for a in args.split(",")]
            b.add_node(name,op,fins)
        if not b.nodes: raise ValueError("Parsed empty .bench")
        return b
    def write(self,path):
        with open(path,"w",encoding="utf-8") as f:
            for n in self.inputs:  f.write(f"INPUT({n})\n")
            for n in self.outputs: f.write(f"OUTPUT({n})\n")
            for name,(typ,fins) in self.nodes.items():
                if typ=="DFF": f.write(f"{name} = DFF({fins[0]})\n")
                elif typ in {"NOT","BUF"}: f.write(f"{name} = {typ}({fins[0]})\n")
                else: f.write(f"{name} = {typ}({','.join(fins)})\n")

class NetBuilder:
    def __init__(self, b: Bench):
        self.b=b; self.c=defaultdict(int)
    def fresh(self,base):
        i=self.c[base]; self.c[base]+=1; return f"{base}_{i}"
    def add(self,op,*ins):
        n=self.fresh(op); self.b.add_node(n,op,list(ins)); return n
    def NOT(self,a): return self.add("NOT",a)
    def BUF(self,a): return self.add("BUF",a)
    def AND(self,a,b): return self.add("AND",a,b)
    def OR (self,a,b): return self.add("OR" ,a,b)
    def XOR(self,a,b): return self.add("XOR",a,b)
    def XNOR(self,a,b): return self.add("XNOR",a,b)
    def DFF(self,d): q=self.fresh("FF"); self.b.add_node(q,"DFF",[d]); return q

def choose_po_sites(b: Bench, N, rng):
    outs=list(b.outputs); rng.shuffle(outs); return outs[:min(N,len(outs))]

def insert_dk_lock(b: Bench, key_size: int, m_cycles: int, seed: int=7):
    rng=random.Random(seed); nb=NetBuilder(b)
    # Key pins
    keys=[f"KEY{i}" for i in range(key_size)]
    for k in keys: b.add_input(k)
    # Constants
    b.add_input("CONST0"); b.add_input("CONST1")

    # --- Activation: enable when ALL key bits match chosen pattern
    act_correct=[rng.randint(0,1) for _ in range(key_size)]
    eq_terms=[(keys[i] if act_correct[i]==1 else nb.NOT(keys[i])) for i in range(key_size)]
    enable=eq_terms[0]
    for t in eq_terms[1:]: enable=nb.AND(enable,t)

    # N-bit counter increments by +1 ONLY when enable==1
    ACT_Q=[nb.DFF("CONST0") for _ in range(key_size)]
    carry_one="CONST1"; not_en=nb.NOT(enable); carry=carry_one
    for i,qi in enumerate(ACT_Q):
        inc_i=nb.XOR(qi, carry)        # next if incrementing by +1
        carry=nb.AND(qi, carry)        # ripple carry
        hold_i=nb.AND(not_en, qi)      # hold when enable==0
        step_i=nb.AND(enable, inc_i)   # step when enable==1
        nxt_i =nb.OR(hold_i, step_i)
        b.nodes[qi]=("DFF",[nxt_i])

    # ACT when count == m
    m=m_cycles
    terms=[]
    for i,qi in enumerate(ACT_Q):
        bit=(m>>i)&1
        terms.append(qi if bit==1 else nb.NOT(qi))
    ACT=terms[0]
    for t in terms[1:]: ACT=nb.AND(ACT,t)

    # Sticky activation latch + release gate
    ACT_L=nb.DFF("CONST0")
    ACT_L_or=nb.OR(ACT_L, ACT)     # ACT_L <- ACT_L OR ACT
    b.nodes[ACT_L]=("DFF",[ACT_L_or])
    UNBLOCK=nb.OR(ACT_L, ACT)      # release on ACT and after

    # --- PO-only wrapping, no bypass
    picks=choose_po_sites(b, key_size, rng)
    polarity=[rng.choice(["XOR","XNOR"]) for _ in range(len(picks))]
    func_correct=[]
    for i,po in enumerate(picks):
        src=po
        y_key=nb.XOR(src,keys[i]) if polarity[i]=="XOR" else nb.XNOR(src,keys[i])
        y=nb.AND(y_key, UNBLOCK)   # clamp before activation
        y_buf=nb.BUF(y)
        idx=b.outputs.index(po)
        b.outputs[idx]=y_buf
        func_correct.append(0 if polarity[i]=="XOR" else 1)

    return {"keys":keys,"act_correct":act_correct,"func_correct":func_correct,
            "picked_nets":picks,"polarity":polarity}

def topo_order(b: Bench):
    indeg=defaultdict(int); fan=defaultdict(list); nodes=list(b.nodes.keys())
    for n,(t,fins) in b.nodes.items():
        if t=="DFF": continue
        for f in fins:
            if f in b.nodes and b.nodes[f][0]!="DFF":
                indeg[n]+=1; fan[f].append(n)
    q=deque([n for n in nodes if indeg[n]==0 or b.nodes[n][0]=="DFF"])
    order=[]; seen=set()
    while q:
        u=q.popleft()
        if u in seen: continue
        seen.add(u); order.append(u)
        for v in fan.get(u,[]):
            indeg[v]-=1
            if indeg[v]==0: q.append(v)
    return [n for n in order if b.nodes[n][0]!="DFF"] + [n for n in nodes if b.nodes[n][0]=="DFF"]

def eval_gate(op, ins):
    if op=="BUF":  return ins[0]
    if op=="NOT":  return 1-ins[0]
    if op=="AND":  return ins[0]&ins[1]
    if op=="NAND": return 1-(ins[0]&ins[1])
    if op=="OR":   return ins[0]|ins[1]
    if op=="NOR":  return 1-(ins[0]|ins[1])
    if op=="XOR":  return ins[0]^ins[1]
    if op=="XNOR": return 1-(ins[0]^ins[1])
    raise ValueError(op)

def simulate(b: Bench, cycles, pi_stream, key_stream=None):
    order=topo_order(b)
    val=defaultdict(int); outs=[]
    for t in range(cycles):
        for pi in b.inputs:
            if pi.startswith("KEY") and key_stream is not None:
                idx=int(pi[3:]); val[pi]=key_stream[t].get(idx,0)
            elif pi=="CONST1": val[pi]=1
            elif pi=="CONST0": val[pi]=0
            else: val[pi]=pi_stream[t].get(pi,0)
        dD={}
        for n in order:
            typ,fins=b.nodes[n]
            if typ=="DFF": dD[n]=val[fins[0]]
            else: val[n]=eval_gate(typ,[val[x] for x in fins])
        outs.append({po:val.get(po,0) for po in b.outputs})
        for n in dD: val[n]=dD[n]
    return outs

def outs_vector(bench: Bench, log):
    order=bench.outputs
    return [[int(log[t].get(name,0)) for name in order] for t in range(len(log))]

def cmd_lock(args):
    b=Bench.parse(args.infile)
    info=insert_dk_lock(b, key_size=args.keys, m_cycles=args.m, seed=args.seed)
    b.write(args.outfile)
    act_bits="".join(str(x) for x in info["act_correct"])
    func_bits="".join(str(x) for x in info["func_correct"])
    print("[DK-Lock] Wrote:", args.outfile)
    print("[DK-Lock] Picked outputs:", ", ".join(info["picked_nets"]))
    print("[DK-Lock] Polarity:", ", ".join(info["polarity"]))
    print("[DK-Lock] Correct activation key:", act_bits)
    if len(info["func_correct"])<args.keys:
        print("[DK-Lock] Correct functional key (used pins):", func_bits)
        print("[DK-Lock] Padded functional key (N bits):", func_bits + "0"*(args.keys-len(info["func_correct"])))
    else:
        print("[DK-Lock] Correct functional key :", func_bits)
    print("[DK-Lock] m cycles:", args.m)

def cmd_validate(args):
    b0=Bench.parse(args.orig); b1=Bench.parse(args.locked)
    rng=random.Random(args.seed)
    pis=[n for n in b0.inputs if not n.startswith("KEY") and n not in ("CONST0","CONST1")]
    stream=[{p:rng.randint(0,1) for p in pis} for _ in range(args.cycles)]
    key_pins=[p for p in b1.inputs if p.startswith("KEY")]; N=len(key_pins)
    def parse_bits(s,Nexp):
        if len(s)!=Nexp or any(c not in "01" for c in s): raise ValueError(f"Key must be exactly {Nexp} bits")
        return [int(c) for c in s]
    act=parse_bits(args.act_key,N); func=parse_bits(args.func_key,N)
    key_stream=[({i:act[i] for i in range(N)} if t<args.m else {i:func[i] for i in range(N)}) for t in range(args.cycles)]
    out0=simulate(b0,args.cycles,stream,None); out1=simulate(b1,args.cycles,stream,key_stream)
    v0=outs_vector(b0,out0); v1=outs_vector(b1,out1)
    total=match=0
    for t in range(args.m, args.cycles):
        total+=1
        if v0[t]==v1[t]: match+=1
    print(f"[Validate] Cycles compared (t >= {args.m}): {total}; matches: {match}/{total} ({100.0*match/max(1,total):.1f}%)")

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd", required=True)
    lp=sub.add_parser("lock", help="Lock a .bench"); lp.add_argument("--in", dest="infile", required=True)
    lp.add_argument("--out", dest="outfile", required=True); lp.add_argument("--keys", type=int, default=10)
    lp.add_argument("--m", type=int, default=9); lp.add_argument("--seed", type=int, default=7); lp.set_defaults(func=cmd_lock)
    vp=sub.add_parser("validate", help="Validate locked vs original"); vp.add_argument("--orig", required=True)
    vp.add_argument("--locked", required=True); vp.add_argument("--cycles", type=int, default=300)
    vp.add_argument("--m", type=int, required=True); vp.add_argument("--act-key", required=True); vp.add_argument("--func-key", required=True)
    vp.add_argument("--seed", type=int, default=1); vp.set_defaults(func=cmd_validate)
    args=ap.parse_args(); args.func(args)

if __name__=="__main__": main()
