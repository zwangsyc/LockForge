#!/usr/bin/env python3
import argparse, re, random, os
from collections import defaultdict, deque

IN_RE = re.compile(r'^\s*INPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
OUT_RE = re.compile(r'^\s*OUTPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
GATE_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*([A-Z]+)\s*\(\s*([A-Za-z0-9_\s,]+)\s*\)\s*$')

def parse_bench(path):
    inputs, outputs, assigns = [], [], []
    with open(path, "r") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#") or s.startswith("//"): continue
            m = IN_RE.match(s)
            if m: inputs.append(m.group(1)); continue
            m = OUT_RE.match(s)
            if m: outputs.append(m.group(1)); continue
            m = GATE_RE.match(s)
            if m:
                out, op = m.group(1), m.group(2).upper()
                ins = [t.strip() for t in m.group(3).split(",") if t.strip()]
                assigns.append((out, op, ins)); continue
            raise SystemExit(f"Cannot parse: {s}")
    return {"inputs": inputs, "outputs": outputs, "assigns": assigns}

def write_bench(path, circ):
    with open(path, "w") as f:
        for n in circ["inputs"]: f.write(f"INPUT({n})\n")
        f.write("\n")
        for n in circ["outputs"]: f.write(f"OUTPUT({n})\n")
        f.write("\n")
        for out, op, ins in circ["assigns"]:
            if op in ("BUF","NOT"):
                f.write(f"{out} = {op}({ins[0]})\n")
            else:
                f.write(f"{out} = {op}({', '.join(ins)})\n")

def topo_order(assigns):
    deps=defaultdict(set); outs=set(); nodes=set()
    for o,op,ins in assigns:
        outs.add(o); nodes.add(o)
        for i in ins: deps[o].add(i); nodes.add(i)
    indeg={n:0 for n in nodes}
    for o in outs:
        for d in deps[o]: indeg[o]+=1
    q=deque([n for n in nodes if indeg[n]==0])
    order=[]; seen=set()
    while q:
        n=q.popleft()
        if n in seen: continue
        seen.add(n); order.append(n)
        for o,op,ins in assigns:
            if n in deps[o]:
                indeg[o]-=1
                if indeg[o]==0: q.append(o)
    gmap={o:(o,op,ins) for (o,op,ins) in assigns}
    return [gmap[n] for n in order if n in gmap] if len(gmap)==len(assigns) else assigns

def build_linear_cascade(lits, start_op, pref):
    if len(lits)==1: return lits[0], []
    cur = lits[0]
    op = start_op
    new=[]
    for i in range(1,len(lits)):
        out=f"{pref}_{op}_{i}"
        new.append((out, op, [cur, lits[i]]))
        cur=out
        op = "OR" if op=="AND" else "AND"
    return cur, new

def unique_name(base, used):
    if base not in used: return base
    i=1
    while f"{base}_{i}" in used: i+=1
    return f"{base}_{i}"

def lock(infile, outfile, N, pattern, xnor_rate, seed, target=None):
    rnd = random.Random(seed)
    circ = parse_bench(infile)
    inputs=list(circ["inputs"])
    outputs=list(circ["outputs"])
    assigns=list(circ["assigns"])
    used = set(inputs+outputs+[a for a,_,_ in assigns])
    data_inputs=[i for i in inputs if not i.upper().startswith("KEY")]
    if not data_inputs: raise SystemExit("No data inputs found")
    taps = data_inputs[:N] if len(data_inputs)>=N else data_inputs
    if len(taps)<N: N=len(taps)
    keyA=[f"KEYA{i}" for i in range(N)]
    keyB=[f"KEYB{i}" for i in range(N)]
    for k in keyA+keyB:
        if k not in inputs: inputs.append(k)
    opsA=[("XNOR" if rnd.random()<xnor_rate else "XOR") for _ in range(N)]
    opsB=[("XNOR" if rnd.random()<xnor_rate else "XOR") for _ in range(N)]
    KA_bits=[rnd.randint(0,1) for _ in range(N)]
    KB_bits=[]
    for i in range(N):
        if opsA[i]==opsB[i]:
            KB_bits.append(1-KA_bits[i])
        else:
            KB_bits.append(KA_bits[i])
    s_nodes=[]
    t_nodes=[]
    for i,t in enumerate(taps):
        s=unique_name(f"CAS_S{i}", used); used.add(s)
        tt=unique_name(f"CAS_T{i}", used); used.add(tt)
        assigns.append((s, opsA[i], [t, keyA[i]]))
        assigns.append((tt, opsB[i], [t, keyB[i]]))
        s_nodes.append(s); t_nodes.append(tt)
    g_start = "AND" if pattern.lower() in ("alt","and") else "OR"
    gb_start = "OR" if g_start=="AND" else "AND"
    g, g_gates = build_linear_cascade(s_nodes, g_start, "CAS_G")
    gb, gb_gates = build_linear_cascade(t_nodes, gb_start, "CAS_GB")
    assigns.extend(g_gates); assigns.extend(gb_gates)
    Y=unique_name("CAS_Y", used); used.add(Y)
    assigns.append((Y, "AND", [g, gb]))
    if target is None: target = outputs[0]
    if target not in outputs: raise SystemExit(f"Target output {target} not found")
    locked=unique_name(f"{target}_LOCKED", used); used.add(locked)
    assigns.append((locked, "XOR", [target, Y]))
    new_outputs=[locked if o==target else o for o in outputs]
    write_bench(outfile, {"inputs":inputs,"outputs":new_outputs,"assigns":assigns})
    KA="".join(str(b) for b in KA_bits)
    KB="".join(str(b) for b in KB_bits)
    KEY=KA+KB
    print(f"KEYA={KA}")
    print(f"KEYB={KB}")
    print(f"KEY={KEY}")
    print(f"OPS_A={','.join(opsA)}")
    print(f"OPS_B={','.join(opsB)}")
    print(f"TAPS={','.join(taps)}")
    print(f"LOCKED_OUT={locked}")
    print(f"Y={Y}")
    print(f"SAVED={outfile}")

def main():
    ap=argparse.ArgumentParser(prog="CAS-Lock (random XOR/XNOR literals; dual cascades)")
    sub=ap.add_subparsers(dest="cmd", required=True)
    pl=sub.add_parser("lock")
    pl.add_argument("--in", dest="infile", required=True)
    pl.add_argument("--out", dest="outfile", required=True)
    pl.add_argument("--N", type=int, required=True)
    pl.add_argument("--pattern", default="alt", choices=["alt","and","or"])
    pl.add_argument("--xnor-rate", type=float, default=0.5)
    pl.add_argument("--seed", type=int, default=1)
    pl.add_argument("--target", type=str, default=None)
    args=ap.parse_args()
    if args.cmd=="lock":
        lock(args.infile, args.outfile, args.N, args.pattern, args.xnor_rate, args.seed, args.target)

if __name__=="__main__":
    main()
