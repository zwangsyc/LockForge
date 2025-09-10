#!/usr/bin/env python3
import sys, argparse, itertools, random, copy

def parse_bench(path):
    inputs, outputs, gates = [], [], {}
    with open(path, 'r') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('INPUT('):
                name = line[line.find('(')+1:line.find(')')]
                inputs.append(name)
            elif line.startswith('OUTPUT('):
                name = line[line.find('(')+1:line.find(')')]
                outputs.append(name)
            elif '=' in line:
                left, right = [x.strip() for x in line.split('=', 1)]
                gtype = right[:right.find('(')].strip().upper()
                args = [a.strip() for a in right[right.find('(')+1:right.rfind(')')].split(',') if a.strip()]
                gates[left] = (gtype, args)
    return inputs, outputs, gates

def write_bench(path, inputs, outputs, gates):
    with open(path, 'w') as f:
        for i in inputs: f.write(f'INPUT({i})\n')
        for o in outputs: f.write(f'OUTPUT({o})\n')
        for n,(gt,as_) in gates.items(): f.write(f'{n} = {gt}({", ".join(as_)})\n')

def topo_order(inputs, gates):
    fanouts = {n:[] for n in list(inputs)+list(gates.keys())}
    indeg = {n:0 for n in list(inputs)+list(gates.keys())}
    for n,(gt,as_) in gates.items():
        for a in as_:
            fanouts.setdefault(a, []).append(n)
            indeg[n] = indeg.get(n,0)+1
            indeg.setdefault(a, 0)
    q=[n for n,d in indeg.items() if d==0]
    out=[]
    while q:
        u=q.pop(0); out.append(u)
        for v in fanouts.get(u,[]):
            indeg[v]-=1
            if indeg[v]==0: q.append(v)
    return out

def depths(inputs, gates):
    order = topo_order(inputs, gates)
    d={}
    for n in order:
        if n in inputs: d[n]=0
        elif n in gates:
            _, as_ = gates[n]
            d[n] = 1 + max(d.get(a,0) for a in as_)
        else:
            d[n]=0
    return d

def ensure_inv(G, net):
    inv = f'{net}_INV'
    if inv not in G: G[inv]=('NOT',[net])
    return inv

def build_and_chain(G, nets, prefix):
    if len(nets)==1: return nets[0]
    cur=f'{prefix}_AND0'; G[cur]=('AND',[nets[0], nets[1]])
    idx=1
    for n in nets[2:]:
        nxt=f'{prefix}_AND{idx}'; G[nxt]=('AND',[cur, n]); cur=nxt; idx+=1
    return cur

def build_or_chain(G, nets, prefix):
    if len(nets)==1: return nets[0]
    cur=f'{prefix}_OR0'; G[cur]=('OR',[nets[0], nets[1]])
    idx=1
    for n in nets[2:]:
        nxt=f'{prefix}_OR{idx}'; G[nxt]=('OR',[cur, n]); cur=nxt; idx+=1
    return cur

def build_mux(G, sel, a, b, prefix):
    nsel = f'{prefix}_NOTS'; G[nsel]=('NOT',[sel])
    a1 = f'{prefix}_A1'; G[a1]=('AND',[nsel,a])
    a2 = f'{prefix}_A2'; G[a2]=('AND',[sel,b])
    out = f'{prefix}_OUT'; G[out]=('OR',[a1,a2])
    return out

def insert_xor_lock(G, net, key_name, prefix):
    x = f'{prefix}_XOR'
    G[x]=('XOR',[net, key_name])
    return x

def build_graph(inputs, gates):
    succ = {n:[] for n in list(inputs)+list(gates.keys())}
    pred = {n:[] for n in list(inputs)+list(gates.keys())}
    for n,(gt,as_) in gates.items():
        for a in as_:
            succ.setdefault(a, []).append(n)
            pred.setdefault(n, []).append(a)
            pred.setdefault(a, []); succ.setdefault(n, [])
    return succ, pred

def cone_fanin(pred, start):
    vis=set(); stack=[start]
    while stack:
        u=stack.pop()
        for p in pred.get(u, []):
            if p not in vis:
                vis.add(p); stack.append(p)
    return vis

def cone_fanout(succ, start):
    vis=set(); stack=[start]
    while stack:
        u=stack.pop()
        for v in succ.get(u, []):
            if v not in vis:
                vis.add(v); stack.append(v)
    return vis

def pick_entangler_pool_safe(inputs, outputs, gates, target, avoid):
    d = depths(inputs, gates)
    succ, pred = build_graph(inputs, gates)
    fin = cone_fanin(pred, target)
    fout = cone_fanout(succ, target)
    pool=[n for n in gates.keys() if n not in avoid and n not in outputs and n not in fin and n not in fout]
    pool.sort(key=lambda n: d.get(n,0))
    return pool

def build_lut_sop(G, lut_inputs, key_tt_names, prefix):
    import itertools
    k = len(lut_inputs)
    gated_terms=[]
    for idx, combo in enumerate(itertools.product([0,1], repeat=k)):
        lits=[]
        for j,bit in enumerate(combo):
            src=lut_inputs[j]
            lits.append(src if bit==1 else ensure_inv(G, src))
        match = build_and_chain(G, lits, f'{prefix}_M{idx}')
        gated=f'{prefix}_G{idx}'; G[gated]=('AND',[match, key_tt_names[idx]])
        gated_terms.append(gated)
    return build_or_chain(G, gated_terms, f'{prefix}_SUM')

def eval_gate(g, args):
    if g=='AND': return args[0] & args[1]
    if g=='NAND': return 1 - (args[0] & args[1])
    if g=='OR': return args[0] | args[1]
    if g=='NOR': return 1 - (args[0] | args[1])
    if g=='XOR': return args[0] ^ args[1]
    if g=='XNOR': return 1 - (args[0] ^ args[1])
    if g=='NOT': return 1 - args[0]
    if g=='BUF': return args[0]
    raise ValueError(g)

def srll_apply_block(block_id, inputs, outputs, G, target, ent_inputs=1):
    inps = list(inputs); outs = list(outputs); gates = G
    gt_type, fins = gates[target][0], list(gates[target][1])
    k = len(fins)
    key_tt = [f'KEY_TT{block_id}_{i}' for i in range(2**k)]
    for n in key_tt:
        if n not in inps: inps.append(n)
    import itertools
    tt_bits=[eval_gate(gt_type, list(combo)) for combo in itertools.product([0,1], repeat=k)]
    ent_names=[]; lut_inputs=fins[:]
    pool = pick_entangler_pool_safe(inps, outs, gates, target, avoid=set(fins+[target]))
    for j in range(min(ent_inputs, len(fins), len(pool))):
        src = pool[(block_id+j) % len(pool)]
        sel=f'KEY_ENT{block_id}_{j}'; ent_names.append(sel)
        if sel not in inps: inps.append(sel)
        mux_out = build_mux(gates, sel, fins[j], src, f'{target}_ENT{block_id}_{j}')
        lut_inputs[j]=mux_out
    lut_out = build_lut_sop(gates, lut_inputs, key_tt, f'{target}_LUT{block_id}')
    if target in outs:
        outs[outs.index(target)] = lut_out
    del gates[target]
    for n,(gt,as_) in list(gates.items()):
        gates[n]=(gt, [lut_out if a==target else a for a in as_])
    keybits = {**{key_tt[i]: tt_bits[i] for i in range(2**k)},
               **{name: 0 for name in ent_names}}
    return inps, outs, gates, keybits, lut_out

def apply_locking(inputs, outputs, G, how_many=0):
    if how_many<=0: return inputs, outputs, G, {}
    inps=list(inputs); outs=list(outputs); gates=G; keybits={}
    import random
    cands=[n for n in gates.keys() if n not in outs]
    random.shuffle(cands); picks=cands[:how_many]
    for i,net in enumerate(picks):
        key=f'KEY_LCK_{i}'; 
        if key not in inps: inps.append(key)
        new_net = insert_xor_lock(gates, net, key, f'{net}_LOCK')
        for n,(gt,as_) in list(gates.items()):
            gates[n]=(gt, [new_net if a==net else a for a in as_])
        keybits[key]=0
    return inps, outs, G, keybits

def apply_obfuscation(inputs, outputs, G, inserts=0):
    if inserts<=0: return inputs, outputs, G
    inps=list(inputs); outs=list(outputs); gates=G
    import random
    nets=[n for n in gates.keys()]
    random.shuffle(nets)
    for i,net in enumerate(nets[:inserts]):
        a=f'{net}_OBF_A'; b=f'{net}_OBF_B'
        gates[a]=('NOT',[net]); gates[b]=('NOT',[a])
        for n,(gt,as_) in list(gates.items()):
            if n in (a,b): continue
            gates[n]=(gt, [b if x==net else x for x in as_])
    return inputs, outputs, G

# === New: Eq.(5)-style Alternative Blocks (G-AntiSAT-like pair) ===
def select_taps(inputs, gates, n):
    taps = list(inputs)[:n]
    if len(taps) < n:
        for name in gates.keys():
            if name not in taps:
                taps.append(name)
                if len(taps) == n:
                    break
    return taps[:n]

def build_and_tree(G, terms, prefix):
    if not terms:
        const1 = f'{prefix}_ONE'
        G[const1]=('BUF',['1'])
        return const1
    return build_and_chain(G, terms, prefix)

def build_eq5_alt_blocks(inputs, outputs, G, ab_n=8, ab_c=3, ab_outputs=1, ab_j=None, seed=1337):
    import random
    random.seed(seed)
    inps=list(inputs); outs=list(outputs); Gdict=G; keybits={}
    n = ab_n; C = max(1, min(ab_c, n))
    taps = select_taps(inps, Gdict, n)

    Kf_names = [f'KEY_ABF_{i}' for i in range(n)]
    Kg_names = [f'KEY_ABG_{i}' for i in range(n)]
    for nm in Kf_names + Kg_names:
        if nm not in inps: inps.append(nm)

    Kf = [random.randint(0,1) for _ in range(n)]
    Kg = Kf[:]
    lower_len = max(1, n - C)
    j = random.randrange(0, lower_len) if ab_j is None else max(0, min(n-1, ab_j))
    Kg[j] = 1 - Kg[j]

    # f: AND over window bits (n-C..n-1) of XNOR(x_i, Kf[i])
    litF=[]; 
    for i in range(n-C, n):
        lf = f'ABF_LIT_{i}'; Gdict[lf]=('XNOR',[taps[i], Kf_names[i]]); litF.append(lf)
    F_and = build_and_tree(Gdict, litF, 'ABF_AND')

    # g: AND over all bits of XNOR(x_i, Kg[i])  -> point function at Kg
    litG=[]
    for i in range(n):
        lg = f'ABG_LIT_{i}'; Gdict[lg]=('XNOR',[taps[i], Kg_names[i]]); litG.append(lg)
    G_and = build_and_tree(Gdict, litG, 'ABG_AND')

    F_not = 'ABF_NOT'; Gdict[F_not]=('NOT',[F_and])
    T_and = f'AB_TRIG'; Gdict[T_and]=('AND',[F_not, G_and])

    targets = outs[-ab_outputs:] if ab_outputs>0 else []
    for po in targets:
        xout = f'{po}_LOCKED'
        if po in Gdict:
            Gdict[xout]=('XOR',[po, T_and])
        else:
            Gdict[xout]=('XOR',[po, T_and])
        outs[outs.index(po)] = xout

    for i in range(n):
        keybits[Kf_names[i]] = Kf[i]
        keybits[Kg_names[i]] = Kg[i]

    return inps, outs, Gdict, keybits

def srll_fig6(inputs, outputs, gates, blocks=1, ent_per_block=1, alt_blocks=1, lock_gates=0, obf_pairs=0, seed=1337):
    random.seed(seed)
    G = copy.deepcopy(gates)
    inps=list(inputs); outs=list(outputs)
    key_all = {}
    # Concatenated withholding + entanglement
    def choose_targets(inputs, outputs, gates, count):
        d = depths(inputs, gates)
        cands = [n for n,(gt,as_) in gates.items() if len(as_) in (2,3) and not all(a in inputs for a in as_)]
        if not cands: cands = list(gates.keys())
        cands.sort(key=lambda n: (d.get(n,0), n))
        if count >= len(cands): return cands
        step = max(1, len(cands)//count)
        return [cands[i] for i in range(step//2, step*count, step)]
    targets = choose_targets(inps, outs, G, blocks)
    for b, tgt in enumerate(targets):
        inps, outs, G, keybits, _ = srll_apply_block(b, inps, outs, G, tgt, ent_inputs=ent_per_block)
        key_all.update(keybits)

    # Step-5 Alternative Blocks (Eq.(5) G-AntiSAT-like)
    inps, outs, G, keybits = build_eq5_alt_blocks(inps, outs, G, ab_n=8, ab_c=3, ab_outputs=alt_blocks, seed=seed)
    key_all.update(keybits)

    # Optional scattered locks + obfuscation
    inps, outs, G, keybits = apply_locking(inps, outs, G, how_many=lock_gates)
    key_all.update(keybits)
    inps, outs, G = apply_obfuscation(inps, outs, G, inserts=obf_pairs)
    return inps, outs, G, key_all

def main():
    ap = argparse.ArgumentParser(description='SRLL (Fig. 6) locker with Eq.(5) Alternative Blocks.')
    ap.add_argument('input', help='.bench input')
    ap.add_argument('output', help='locked .bench output')
    ap.add_argument('--blocks', type=int, default=1, help='withheld LUT blocks')
    ap.add_argument('--ent', type=int, default=1, help='entangled LUT inputs per block')
    ap.add_argument('--alt', type=int, default=1, help='number of POs to lock with Eq.(5) alt-blocks')
    ap.add_argument('--lock', type=int, default=0, help='number of scattered XOR key locks')
    ap.add_argument('--obf', type=int, default=0, help='number of double-NOT obfuscation inserts')
    ap.add_argument('--seed', type=int, default=1337, help='seed')
    args = ap.parse_args()

    inps, outs, gates = parse_bench(args.input)
    L_inps, L_outs, L_gates, key = srll_fig6(inps, outs, gates,
                                             blocks=args.blocks,
                                             ent_per_block=args.ent,
                                             alt_blocks=args.alt,
                                             lock_gates=args.lock,
                                             obf_pairs=args.obf,
                                             seed=args.seed)
    write_bench(args.output, L_inps, L_outs, L_gates)
    print(f'[WRITE] {args.output}')
    print('[KEY] Correct key (use in simulator):')
    print(','.join(f'{k}={v}' for k,v in key.items()))

if __name__ == '__main__':
    main()
