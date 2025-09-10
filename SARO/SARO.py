
#!/usr/bin/env python3
"""
saro_lock_rename.py — Robust SARO locker with rename-then-wrap (guaranteed identity under correct key).

Features
- Supports .bench with AND/OR/NAND/NOR/XOR/XNOR/NOT/BUF and DFF (two syntaxes).
- Sequential cut for ISCAS’89: treat each DFF Q as PI*, each DFF D as PO* (lock the combinational slice).
- N-input gate support (reduces AND/OR/XOR and complements over any fan-in).
- Greedy hypergraph-ish partitioning; lock partition boundary nodes.
- T3 modes: shuffled outputs, 2-bit arithmetic add, invert, dummy substitution, random.
- **Rename-then-wrap** transform: original gate X -> X__ORIGk; locked logic defined on X (no global rewiring).
- Validation prints Matches(correct/wrong) and exits non-zero if correct-key match isn’t perfect.

Usage
  python3 saro_lock_rename.py --in c1908.bench --out c1908_locked.bench --key-size 64 --seed 7 --validate --patterns 256
"""

import argparse, re, sys, random, math
from collections import defaultdict, deque

# ---------------- Parsing (.bench + DFF) ----------------

IN_RE   = re.compile(r'^\s*INPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
OUT_RE  = re.compile(r'^\s*OUTPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
EQ_RE   = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*([A-Za-z]+)\s*\((.*?)\)\s*$')
DFF_EQ1 = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*DFF\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
DFF_EQ2 = re.compile(r'^\s*DFF\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*=\s*([A-Za-z0-9_]+)\s*$')

def parse_bench_with_dff(path):
    inputs, outputs, gates, dffs = [], [], {}, []
    with open(path,'r') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'): continue
            m = IN_RE.match(s)
            if m: inputs.append(m.group(1)); continue
            m = OUT_RE.match(s)
            if m: outputs.append(m.group(1)); continue
            m = DFF_EQ1.match(s)
            if m: dffs.append((m.group(1), m.group(2))); continue
            m = DFF_EQ2.match(s)
            if m: dffs.append((m.group(1), m.group(2))); continue
            m = EQ_RE.match(s)
            if m:
                out = m.group(1)
                op  = m.group(2).upper()
                args = [a.strip() for a in m.group(3).split(',') if a.strip()]
                gates[out] = (op, args); continue
    return inputs, outputs, gates, dffs

def sequential_cut(inputs, outputs, gates, dffs):
    """Cut sequential circuits: add DFF Q to PIs, DFF D to POs; remove DFF arcs from logic slice."""
    if not dffs:
        return inputs[:], outputs[:], dict(gates), False, dffs[:]
    new_inputs = list(inputs)
    new_outputs = list(outputs)
    for q,d in dffs:
        if q not in new_inputs: new_inputs.append(q)
        if d not in new_outputs: new_outputs.append(d)
    return new_inputs, new_outputs, dict(gates), True, dffs[:]

# ---------------- Netlist utilities ----------------

def topo_order(inputs, gates):
    indeg = defaultdict(int)
    nodes = set(inputs) | set(gates.keys())
    for g,(_,ins) in gates.items():
        for i in ins:
            if i in nodes:
                indeg[g]+=1
    q = deque([n for n in nodes if indeg[n]==0])
    order, seen = [], set(q)
    while q:
        u = q.popleft(); order.append(u)
        for v,(_,ins) in gates.items():
            if u in ins:
                indeg[v]-=1
                if indeg[v]==0 and v not in seen:
                    q.append(v); seen.add(v)
    return [n for n in order if n in gates]

def levelize(inputs, gates):
    level = {i:0 for i in inputs}
    order = topo_order(inputs, gates)
    for n in order:
        _,ins = gates[n]
        level[n] = 1 + max(level.get(i,0) for i in ins)
    return level, order

def build_fanin_fanout(inputs, gates):
    fanin = {g:set(args) for g,(_,args) in gates.items()}
    fanout = defaultdict(set)
    for g,(_,ins) in gates.items():
        for w in ins:
            fanout[w].add(g)
    return fanin, fanout

def reduce_gate(op, vals):
    op=op.upper()
    if op=='BUF': return int(vals[0])
    if op in ('NOT','INV'):
        if len(vals)!=1:
            acc=0
            for v in vals: acc^=int(v)
            return 1-acc
        return 1-int(vals[0])
    if op in ('AND','NAND'):
        acc=1
        for v in vals: acc&=int(v)
        return acc if op=='AND' else 1-acc
    if op in ('OR','NOR'):
        acc=0
        for v in vals: acc|=int(v)
        return acc if op=='OR' else 1-acc
    if op in ('XOR','XNOR'):
        acc=0
        for v in vals: acc^=int(v)
        return acc if op=='XOR' else 1-acc
    raise ValueError(f"Unsupported op {op}")

def simulate(inputs, outputs, gates, assignment):
    order = topo_order(inputs, gates)
    values = dict(assignment)
    for n in order:
        op, ins = gates[n]
        ins_vals = [values.get(w,0) for w in ins]
        values[n] = reduce_gate(op, ins_vals)
    return [values.get(o,0) for o in outputs]

# ---------------- Partitioning ----------------

def build_hyperedges(inputs, gates):
    net_to_sinks = defaultdict(set)
    for g,(_,ins) in gates.items():
        for w in ins:
            net_to_sinks[w].add(g)
    return net_to_sinks

def greedy_partition(inputs, gates, key_size, seed=0):
    random.seed(seed)
    level, order = levelize(inputs,gates)
    net_sinks = build_hyperedges(inputs,gates)
    allg = list(gates.keys())
    N = len(allg)
    tsize = max(2, min(max(1, N//max(1,key_size)), 64))
    P = max(1, math.ceil(N/max(1,tsize)))

    neigh = defaultdict(set)
    for net, sinks in net_sinks.items():
        sinks=list(sinks)
        for i in range(len(sinks)):
            for j in range(i+1,len(sinks)):
                a,b = sinks[i], sinks[j]
                neigh[a].add(b); neigh[b].add(a)

    seeds=[]; step=max(1, len(order)//P)
    for i in range(0,len(order),step):
        if len(seeds)>=P: break
        if order[i] in gates: seeds.append(order[i])
    if not seeds and allg: seeds=[allg[0]]
    parts=[set([s]) for s in seeds]; assigned=set(seeds)

    def gain(g, pi):
        score=0
        for nb in neigh[g]:
            if nb in parts[pi]: score+=2
            elif nb in assigned: score-=1
        if parts[pi]:
            avg=sum(level.get(x,0) for x in parts[pi])/max(1,len(parts[pi]))
            score-=abs(level.get(g,0)-avg)*0.01
        return score

    rest=[g for g in allg if g not in assigned]
    rest.sort(key=lambda x: len(neigh[x]), reverse=True)
    for g in rest:
        bestpi=None; best=-1e9
        for pi in range(len(parts)):
            if len(parts[pi])>=tsize: continue
            sc=gain(g,pi)
            if sc>best: best=sc; bestpi=pi
        if bestpi is None: bestpi=min(range(len(parts)), key=lambda i: len(parts[i]))
        parts[bestpi].add(g); assigned.add(g)

    for g in allg:
        if g not in assigned:
            idx=min(range(len(parts)), key=lambda i: len(parts[i]))
            parts[idx].add(g); assigned.add(g)
    return parts, level

# ---------------- Builders (rename-then-wrap) ----------------

class NameGen:
    def __init__(self): self.c=defaultdict(int)
    def new(self, base): self.c[base]+=1; return f"{base}{self.c[base]}"

def rename_gate(gates, name, ng):
    """Rename existing gate 'name' to a fresh 'name__ORIGk', return new name."""
    k=1
    while f"{name}__ORIG{k}" in gates:
        k+=1
    newn=f"{name}__ORIG{k}"
    gates[newn]=gates.pop(name)
    return newn

def pick_dummies(bn, level, inputs, fanout):
    # Avoid bn's fanout cone; choose from <= depth(bn) + PIs
    visited=set()
    q=deque([bn])
    while q:
        u=q.popleft()
        for v in fanout.get(u,[]):
            if v not in visited:
                visited.add(v); q.append(v)
    forbid=visited|{bn}
    depth=level.get(bn,0)
    cands=[n for n,l in level.items() if n not in forbid and l<=depth] + list(inputs)
    if not cands: return [bn]  # fallback
    random.shuffle(cands)
    k=random.choice([1,2,3])
    return cands[:k]

def xor_chain(gates, wires, ng):
    if len(wires)==1: return wires[0]
    cur=wires[0]
    for w in wires[1:]:
        h=ng.new("H_XOR_"); gates[h]=('XOR',[cur,w]); cur=h
    return cur

def enable_from_key(gates, keyname, correct_bit, ng):
    # e = KEY if correct_bit==0 else NOT(KEY)
    if correct_bit==0: return keyname
    n=ng.new("H_NOT_"); gates[n]=('NOT',[keyname]); return n

# ---- Single-output T3 using rename-then-wrap: produces final under original name ----

def t3_single(gates, node, kind, e, R, ng):
    """Rename node -> node__ORIGk, then define locked logic at 'node'."""
    orig = rename_gate(gates, node, ng)  # original function now at orig
    if kind=='invert':
        gates[node]=('XOR',[orig, e])
    elif kind=='gatedxor':
        a=ng.new("H_AND_"); gates[a]=('AND',[e, R])
        gates[node]=('XOR',[orig, a])
    elif kind=='substitute':
        ne=ng.new("H_NOT_"); gates[ne]=('NOT',[e])
        t1=ng.new("H_AND_"); gates[t1]=('AND',[ne, orig])
        t2=ng.new("H_AND_"); gates[t2]=('AND',[e, R])
        gates[node]=('OR',[t1,t2])
    elif kind=='random':
        p1=ng.new("H_XOR_"); gates[p1]=('XOR',[orig, R])
        p2=ng.new("H_AND_"); gates[p2]=('AND',[R, e])
        r1=ng.new("H_XNOR_"); gates[r1]=('XNOR',[p1,p2])
        ne=ng.new("H_NOT_"); gates[ne]=('NOT',[e])
        t1=ng.new("H_AND_"); gates[t1]=('AND',[ne, orig])
        t2=ng.new("H_AND_"); gates[t2]=('AND',[e, r1])
        gates[node]=('OR',[t1,t2])
    else:
        raise ValueError("unknown T3 kind")

def rename_pair_freeze(gates, a, b, ng):
    """Rename a->a__ORIGk and b->b__ORIGk, and rewrite *inside those two renamed gates*
    any cross references:
      - inputs of a that equal 'b' become 'b__ORIGk'
      - inputs of b that equal 'a' become 'a__ORIGk'
    This prevents combinational loops when we later define locked a,b that depend on the originals.
    """
    # grab originals
    if a not in gates or b not in gates:
        raise KeyError("rename_pair_freeze expects both nodes present")
    op_a, ins_a = gates[a]
    op_b, ins_b = gates[b]

    # allocate new names
    k=1
    aorig = f"{a}__ORIG{k}"
    while aorig in gates: k+=1; aorig = f"{a}__ORIG{k}"
    k=1
    borig = f"{b}__ORIG{k}"
    while borig in gates: k+=1; borig = f"{b}__ORIG{k}"

    # rewrite ins to freeze cross-dependency
    new_ins_a = [borig if w==b else w for w in ins_a]
    new_ins_b = [aorig if w==a else w for w in ins_b]

    # commit renames
    del gates[a]; del gates[b]
    gates[aorig] = (op_a, new_ins_a)
    gates[borig] = (op_b, new_ins_b)
    return aorig, borig

# ---- Pairwise T3 (shuffle/arithmetic) using rename-then-wrap on BOTH nodes ----

def t3_shuffle(gates, a, b, e, ng):
    aorig, borig = rename_pair_freeze(gates, a, b, ng)
    ne=ng.new("H_NOT_"); gates[ne]=('NOT',[e])
    t1=ng.new("H_AND_"); gates[t1]=('AND',[ne, aorig])
    t2=ng.new("H_AND_"); gates[t2]=('AND',[e, borig])
    gates[a]=('OR',[t1,t2])
    ne2=ng.new("H_NOT_"); gates[ne2]=('NOT',[e])
    u1=ng.new("H_AND_"); gates[u1]=('AND',[ne2, borig])
    u2=ng.new("H_AND_"); gates[u2]=('AND',[e, aorig])
    gates[b]=('OR',[u1,u2])

def t3_arithmetic(gates, a, b, e, ng):
    # Treat [b,a] as 2-bit, add e (0=identity)
    aorig, borig = rename_pair_freeze(gates, a, b, ng)
    s0=ng.new("H_XOR_"); gates[s0]=('XOR',[aorig, e])
    c0=ng.new("H_AND_"); gates[c0]=('AND',[aorig, e])
    t =ng.new("H_XOR_"); gates[t ]=('XOR',[borig, e])
    s1=ng.new("H_XOR_"); gates[s1]=('XOR',[t, c0])
    gates[a]=('BUF',[s0])
    gates[b]=('BUF',[s1])


# ---------------- Transitive fanin utilities ----------------
def transitive_fanin_of(node, gates, memo):
    if node in memo:
        return memo[node]
    if node not in gates:
        memo[node] = set()
        return memo[node]
    _, ins = gates[node]
    s = set(ins)
    for w in ins:
        if w in gates:
            s |= transitive_fanin_of(w, gates, memo)
    memo[node] = s
    return s
# ---------------- SARO flow ----------------

def apply_saro_lock(inputs, outputs, gates, key_size=64, seed=0):
    random.seed(seed)
    ng = NameGen()
    fanin, fanout = build_fanin_fanout(inputs, gates)
    parts, level = greedy_partition(inputs, gates, key_size, seed=seed)

    key_inputs=[f"KEY{i}" for i in range(key_size)]
    correct_key=[random.randint(0,1) for _ in range(key_size)]
    new_inputs = inputs + key_inputs

    key_idx=0
    outs_set=set(outputs)

    for p in parts:
        # boundary: any gate in p whose sink leaves p or is a PO
        boundary=[]
        for g in p:
            if g in outs_set: boundary.append(g); continue
            if any((s not in p) for s in fanout.get(g, [])): boundary.append(g)
        if not boundary: continue

        # opportunistic pairwise on random pairs
        local=boundary[:]
        random.shuffle(local)
        while len(local)>=2 and key_idx<key_size and random.random()<0.5:
            a=local.pop(); b=local.pop()
            # Skip pairwise if cross-dependency exists to avoid cyclic definitions
            __memo = {}
            fa = transitive_fanin_of(a, gates, __memo)
            fb = transitive_fanin_of(b, gates, __memo)
            cross = (a in fb) or (b in fa)
            if cross:
                # put them back and break to handle individually
                local.append(b); local.append(a)
                break
            e = enable_from_key(gates, key_inputs[key_idx], correct_key[key_idx], ng); key_idx+=1
            if random.random()<0.5: t3_shuffle(gates, a, b, e, ng)
            else: t3_arithmetic(gates, a, b, e, ng)

        # single-output on remaining
        for bn in local:
            if key_idx>=key_size: break
            e = enable_from_key(gates, key_inputs[key_idx], correct_key[key_idx], ng); key_idx+=1
            dums = pick_dummies(bn, level, inputs, fanout)
            R = dums[0] if len(dums)==1 else xor_chain(gates, dums, ng)
            kind = random.choice(['invert','substitute','random','gatedxor'])
            t3_single(gates, bn, kind, e, R, ng)

    return new_inputs, outputs, gates, key_inputs, correct_key

# ---------------- CLI ----------------

def deep_copy_gates(g):
    # copy {name: (op, [ins...])} without sharing lists
    return {k: (op, list(ins)) for k, (op, ins) in g.items()}

def run(args):
    # Parse and do sequential cut (if DFFs are present)
    inps, outs, gs, dffs_list = parse_bench_with_dff(args.inp)
    ci, co, cg, is_seq, dffs_list = sequential_cut(inps, outs, gs, dffs_list)

    # Keep an immutable golden copy of the combinational slice
    base_inputs  = ci[:]                  # list copy
    base_outputs = co[:]                  # list copy
    base_gates   = deep_copy_gates(cg)    # dict copy

    # Build the locked version on a completely separate copy
    locked_inputs, locked_outputs, locked_gates, key_inputs, correct_key = apply_saro_lock(
        ci[:],                            # list copy (avoid side-effects)
        co[:],                            # list copy
        deep_copy_gates(cg),              # dict copy (critical!)
        key_size=args.key_size,
        seed=args.seed
    )

    # Write the locked netlist
    with open(args.outp, 'w') as f:
        for x in locked_inputs:
            f.write(f"INPUT({x})\n")
        for y in locked_outputs:
            f.write(f"OUTPUT({y})\n")
        f.write("\n")
        for n, (op, ins) in locked_gates.items():
            if op in ('NOT', 'INV', 'BUF') and len(ins) == 1:
                f.write(f"{n} = {op}({ins[0]})\n")
            else:
                f.write(f"{n} = {op}({', '.join(ins)})\n")

    print(f"[+] Locked netlist written: {args.outp}")
    print(f"[+] Correct key (K*): {''.join(map(str, correct_key))[:64]}{'...' if len(correct_key)>64 else ''}")
    if is_seq:
        print(f"[info] Sequential cut applied: DFFs={len(dffs_list)}")

    # Validation: compare original (base_*) vs locked with (correct / wrong) keys
    if args.validate:
        wrong_key = [1 - b for b in correct_key]  # strong wrong key
        ok = bad = 0
        for _ in range(args.patterns):
            vec = [random.randint(0, 1) for _ in base_inputs]
            pat = dict(zip(base_inputs, vec))

            gold = simulate(base_inputs, base_outputs, base_gates, pat)

            pc = dict(pat)
            pc.update({k: v for k, v in zip(key_inputs, correct_key)})
            good = simulate(locked_inputs, locked_outputs, locked_gates, pc)

            pw = dict(pat)
            pw.update({k: v for k, v in zip(key_inputs, wrong_key)})
            wout = simulate(locked_inputs, locked_outputs, locked_gates, pw)

            if good == gold:
                ok += 1
            if wout == gold:
                bad += 1

        print(f"[Validation] Patterns={args.patterns} | Matches(correct)={ok}/{args.patterns} | Matches(wrong)={bad}/{args.patterns}")
        if ok != args.patterns:
            print("[ERROR] Correct-key validation failed; investigate transforms.")
            sys.exit(2)



def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="outp", required=True)
    ap.add_argument("--key-size", type=int, default=64)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--patterns", type=int, default=256)
    args=ap.parse_args()
    run(args)

if __name__=="__main__":
    main()
