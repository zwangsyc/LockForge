#!/usr/bin/env python3
import sys, itertools, argparse, json

def parse_bench(path):
    inputs, outputs, gates = [], [], {}
    with open(path, 'r') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            # strip trailing comments like //...
            if '//' in line:
                line = line.split('//',1)[0].strip()
                if not line:
                    continue
            if line.startswith('INPUT('):
                name = line[line.find('(')+1:line.find(')')].strip()
                inputs.append(name)
            elif line.startswith('OUTPUT('):
                name = line[line.find('(')+1:line.find(')')].strip()
                outputs.append(name)
            elif '=' in line:
                left, right = [x.strip() for x in line.split('=', 1)]
                # Handle alias (wire) assignments: "A = B"
                if '(' not in right or ')' not in right:
                    # Treat as BUF
                    gates[left] = ('BUF', [right])
                    continue
                    gates[left] = ('BUFF', [right])
                    continue
                gtype = right[:right.find('(')].strip().upper()
                args = [a.strip() for a in right[right.find('(')+1:right.rfind(')')].split(',') if a.strip()]
                gates[left] = (gtype, args)
    return inputs, outputs, gates

def fold_and(bits):
    acc = 1
    for b in bits: acc &= b
    return acc

def fold_or(bits):
    acc = 0
    for b in bits: acc |= b
    return acc

def fold_xor(bits):
    acc = 0
    for b in bits: acc ^= b
    return acc

def eval_gate(g, args):
    g = g.upper()
    if g == 'INV': g = 'NOT'
    if g == 'BUF':
        return args[0]
    if g == 'BUFF':
        return args[0]
    if g == 'NOT':
        return 1 - args[0]
    if g == 'AND':
        return fold_and(args)
    if g == 'NAND':
        return 1 - fold_and(args)
    if g == 'OR':
        return fold_or(args)
    if g == 'NOR':
        return 1 - fold_or(args)
    if g == 'XOR':
        return fold_xor(args)
    if g == 'XNOR':
        return 1 - fold_xor(args)
    raise ValueError(f'Unknown gate {g}')

def coerce_const(token, values):
    # Support constants '0', '1' as implicit nodes
    if token == '0':
        values.setdefault('__CONST0__', 0)
        return '__CONST0__'
    if token == '1':
        values.setdefault('__CONST1__', 1)
        return '__CONST1__'
    return token

def simulate(inputs, outputs, gates, vector):
    # Initialize input values
    values = {name:bit for name,bit in zip(inputs, vector)}
    # Handle implicit constants on demand inside loop
    unresolved = set(gates.keys())
    guard = 0
    while unresolved:
        progressed = False
        for n in list(unresolved):
            gtype, args = gates[n]
            # map constants '0'/'1' to synthetic nodes
            adj_args = []
            ready = True
            for a in args:
                aa = a
                if a not in values and (a == '0' or a == '1'):
                    # synthesize constant nodes
                    if a == '0':
                        values['__CONST0__'] = 0
                        aa = '__CONST0__'
                    else:
                        values['__CONST1__'] = 1
                        aa = '__CONST1__'
                if aa not in values:
                    ready = False
                    break
                adj_args.append(values[aa])
            if ready:
                values[n] = eval_gate(gtype, adj_args)
                unresolved.remove(n); progressed=True
        if not progressed:
            raise RuntimeError(f'Stuck during simulation; unresolved: {sorted(unresolved)[:6]}... (total {len(unresolved)})')
        guard += 1
        if guard > 1000000:
            raise RuntimeError('Simulation exceeded iteration guard.')
    return tuple(values[o] for o in outputs)

def parse_key_assignments(s):
    if s.strip().startswith('{'):
        d = json.loads(s)
        return {k:int(v) for k,v in d.items()}
    out = {}
    if s.strip():
        parts = [p.strip() for p in s.split(',') if p.strip()]
        for p in parts:
            if '=' not in p:
                raise ValueError(f"Bad key assignment '{p}'. Use KEY=0/1 or JSON.")
            k,v = p.split('=',1)
            v = v.strip()
            if v not in ('0','1'):
                raise ValueError(f"Bad bit '{v}' in assignment '{p}' (must be 0 or 1).")
            out[k.strip()] = int(v)
    return out

def main():
    ap = argparse.ArgumentParser(description='Simulate and compare original vs locked .bench netlists.')
    ap.add_argument('original', help='Original .bench path')
    ap.add_argument('locked', help='Locked .bench path')
    ap.add_argument('--key', required=True, help="Key assignments for locked netlist (JSON or 'KEY=bit,KEY=bit,...)'")
    ap.add_argument('--samples', type=int, default=0, help='If >0, sample this many patterns instead of exhaustive')
    args = ap.parse_args()

    o_inputs, o_outputs, o_gates = parse_bench(args.original)
    l_inputs, l_outputs, l_gates = parse_bench(args.locked)

    l_key_inputs = [i for i in l_inputs if i.upper().startswith('KEY')]
    l_data_inputs = [i for i in l_inputs if not i.upper().startswith('KEY')]

    key_map = parse_key_assignments(args.key)
    missing = [k for k in l_key_inputs if k not in key_map]
    if missing:
        print(f'[ERROR] Missing key assignments for: {missing}', file=sys.stderr)
        sys.exit(2)

    import itertools, random
    n = len(o_inputs)
    if args.samples and args.samples > 0 and (1<<n) > args.samples:
        patterns = [tuple(random.randint(0,1) for _ in range(n)) for _ in range(args.samples)]
    else:
        patterns = list(itertools.product([0,1], repeat=n))

    key_map_wrong = {k: 1-v for k,v in key_map.items()}

    match_correct = 0
    match_wrong = 0
    for p in patterns:
        y_orig = simulate(o_inputs, o_outputs, o_gates, p)

        vec_ok = []
        for name in l_inputs:
            if name in l_key_inputs:
                vec_ok.append(key_map[name])
            else:
                try:
                    vec_ok.append(p[o_inputs.index(name)])
                except ValueError:
                    vec_ok.append(0)
        y_ok = simulate(l_inputs, l_outputs, l_gates, tuple(vec_ok))

        vec_bad = []
        for name in l_inputs:
            if name in l_key_inputs:
                vec_bad.append(key_map_wrong[name])
            else:
                try:
                    vec_bad.append(p[o_inputs.index(name)])
                except ValueError:
                    vec_bad.append(0)
        y_bad = simulate(l_inputs, l_outputs, l_gates, tuple(vec_bad))

        if y_orig == y_ok:
            match_correct += 1
        if y_orig == y_bad:
            match_wrong += 1

    total = len(patterns)
    print(f'[RESULT] Patterns={total} | Matches(correct)={match_correct}/{total} | Matches(wrong)={match_wrong}/{total}')

if __name__ == '__main__':
    main()
