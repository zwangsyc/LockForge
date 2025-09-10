#!/usr/bin/env python3
"""
DECOR full structural implementation (research / functional).
- Builds G (golden) and L (locked) copies.
- Inserts XOR/XNOR key gates (structural k* consistent).
- Promotes multiple correct keys and synthesizes ISCORR membership logic.
- Wires outputs with correction: out = L XOR (ISCORR AND (L XOR G)).
- Emits a .bench that when supplied with any promoted key yields golden outputs.
"""
import argparse
import copy
import json
import random
import re
from collections import defaultdict, deque

# bench parsing regexes
GATE_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*([A-Za-z]+)\s*\(\s*([A-Za-z0-9_,\s]*)\s*\)\s*$', re.I)
INPUT_RE = re.compile(r'^\s*INPUT\(\s*([A-Za-z0-9_]+)\s*\)\s*$', re.I)
OUTPUT_RE = re.compile(r'^\s*OUTPUT\(\s*([A-Za-z0-9_]+)\s*\)\s*$', re.I)

def parse_bench(path):
    inputs = []
    outputs = []
    gates = {}
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            m = INPUT_RE.match(s)
            if m:
                inputs.append(m.group(1))
                continue
            m = OUTPUT_RE.match(s)
            if m:
                outputs.append(m.group(1))
                continue
            m = GATE_RE.match(s)
            if m:
                out = m.group(1)
                op = m.group(2).upper()
                args = [a.strip() for a in m.group(3).split(',') if a.strip()]
                gates[out] = (op, args)
    return {'inputs': inputs, 'outputs': outputs, 'gates': gates}

def write_bench(net, path):
    with open(path, 'w', encoding='utf-8') as f:
        for inp in net['inputs']:
            f.write(f"INPUT({inp})\n")
        for outp in net['outputs']:
            f.write(f"OUTPUT({outp})\n")
        for out, (op, args) in net['gates'].items():
            args_s = ", ".join(args)
            f.write(f"{out} = {op}({args_s})\n")

def topo_order(net):
    gates = net['gates']
    produced = set(gates.keys())
    indeg = {n: 0 for n in gates}
    rev = defaultdict(list)
    for n, (_, args) in gates.items():
        for a in args:
            if a in produced:
                indeg[n] += 1
                rev[a].append(n)
    q = deque([n for n, d in indeg.items() if d == 0])
    order = []
    while q:
        u = q.popleft()
        order.append(u)
        for v in rev[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return order

def eval_gate(op, args):
    op = op.upper()
    if op == 'AND':
        return int(all(args))
    if op == 'OR':
        return int(any(args))
    if op == 'NAND':
        return int(not all(args))
    if op == 'NOR':
        return int(not any(args))
    if op == 'XOR':
        return int(sum(args) % 2)
    if op == 'XNOR':
        return int((sum(args) % 2) == 0)
    if op == 'NOT':
        return int(not args[0])
    if op in ('BUFF', 'BUF'):
        return int(args[0])
    return 0

def simulate(net, input_vals, key_vals=None):
    env = {}
    env.update(input_vals)
    if key_vals:
        env.update(key_vals)
    gates = net['gates']
    order = topo_order(net)
    for node in order:
        op, args = gates[node]
        argvals = []
        for a in args:
            if a in env:
                argvals.append(env[a])
            elif a == '0':
                argvals.append(0)
            elif a == '1':
                argvals.append(1)
            else:
                argvals.append(0)
        env[node] = eval_gate(op, argvals)
    out_map = {}
    for o in net['outputs']:
        out_map[o] = env.get(o, 0)
    return out_map

def insert_key_gates(net_orig, m, rng, prefer_xor_prob=0.8):
    net = copy.deepcopy(net_orig)
    key_inputs = [f"KEY{i}" for i in range(m)]
    for k in key_inputs:
        if k not in net['inputs']:
            net['inputs'].append(k)
    candidates = [n for n in net['gates'].keys()]
    rng.shuffle(candidates)
    chosen = candidates[:min(m, len(candidates))]
    structural_kstar = []
    for idx, target in enumerate(chosen):
        orig = target + "_orig"
        net['gates'][orig] = net['gates'][target]
        if rng.random() < prefer_xor_prob:
            new_op = 'XOR'
            structural_kstar.append(0)
        else:
            new_op = 'XNOR'
            structural_kstar.append(1)
        net['gates'][target] = (new_op, [orig, key_inputs[idx]])
    # if fewer than m chosen (small circuit), pad structural_kstar with zeros and still create KEY inputs
    while len(structural_kstar) < m:
        structural_kstar.append(0)
    return net, key_inputs, structural_kstar

def generate_promoted_keys(structural_kstar, n_total, m, rng, max_attempts=100000):
    corrects = [tuple(structural_kstar)]
    need = max(0, n_total - 1)
    attempts = 0
    while len(corrects) - 1 < need and attempts < max_attempts:
        cand = tuple(rng.randint(0, 1) for _ in range(m))
        if cand not in corrects:
            corrects.append(cand)
        attempts += 1
    return corrects

def build_decor_net(net_orig, net_locked, key_inputs, promoted_keys):
    net = {'inputs': [], 'outputs': [], 'gates': {}}
    for inp in net_orig['inputs']:
        if inp not in key_inputs:
            net['inputs'].append(inp)
    for k in key_inputs:
        net['inputs'].append(k)

    for name, (op, args) in net_orig['gates'].items():
        pref = "G_" + name
        mapped_args = [("G_" + a) if a in net_orig['gates'] else a for a in args]
        net['gates'][pref] = (op, mapped_args)

    for name, (op, args) in net_locked['gates'].items():
        pref = "L_" + name
        mapped_args = [("L_" + a) if a in net_locked['gates'] else a for a in args]
        net['gates'][pref] = (op, mapped_args)

    eq_names = []
    for j, pk in enumerate(promoted_keys):
        term_names = []
        for i, bit in enumerate(pk):
            term = f"EQ_k{j}_b{i}"
            const = '1' if bit == 1 else '0'
            net['gates'][term] = ('XNOR', [key_inputs[i], const])
            term_names.append(term)
        and_name = f"EQ_KEY_{j}"
        if len(term_names) == 0:
            net['gates'][and_name] = ('BUFF', ['0'])
        elif len(term_names) == 1:
            net['gates'][and_name] = ('BUFF', [term_names[0]])
        else:
            net['gates'][and_name] = ('AND', term_names)
        eq_names.append(and_name)

    if len(eq_names) == 0:
        net['gates']['ISCORR'] = ('BUFF', ['0'])
    elif len(eq_names) == 1:
        net['gates']['ISCORR'] = ('BUFF', [eq_names[0]])
    else:
        net['gates']['ISCORR'] = ('OR', eq_names)

    for out in net_orig['outputs']:
        lnode = "L_" + out
        gnode = "G_" + out

        if gnode not in net['gates']:
            net['gates'][gnode] = ('BUFF', [out])
        if lnode not in net['gates']:
            net['gates'][lnode] = ('BUFF', [out])

        xor_lg = f"XOR_LG_{out}"
        net['gates'][xor_lg] = ('XOR', [lnode, gnode])
        and_node = f"AND_ISC_{out}"
        net['gates'][and_node] = ('AND', ['ISCORR', xor_lg])
        out_final = out
        net['gates'][out_final] = ('XOR', [lnode, and_node])
        net['outputs'].append(out_final)

    return net


def structural_key_to_map(key_inputs, structural_kstar):
    return {k: structural_kstar[i] for i, k in enumerate(key_inputs)}

def validate_promoted_keys(net_orig, net_decor, key_inputs, promoted_keys, samples=200, rng=None):
    if rng is None:
        rng = random.Random()
    results = []
    primary_inputs = [i for i in net_orig['inputs'] if not i.startswith('KEY')]
    for pk in promoted_keys:
        ok = True
        mismatches = 0
        for _ in range(samples):
            iv = {inp: rng.randint(0, 1) for inp in primary_inputs}
            key_map = {k: pk[i] for i, k in enumerate(key_inputs)}
            out_g = simulate(net_orig, iv, None)
            out_d = simulate(net_decor, iv, key_map)
            if out_g != out_d:
                ok = False
                mismatches += 1
        results.append((tuple(pk), ok, mismatches))
    return results

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--keys", type=int, default=16)
    ap.add_argument("--n_correct", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--emit", help="emit DECORed bench")
    ap.add_argument("--validate_samples", type=int, default=200)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    net_orig = parse_bench(args.bench)
    net_locked, key_inputs, structural_kstar = insert_key_gates(net_orig, args.keys, rng)
    promoted_keys = generate_promoted_keys(structural_kstar, args.n_correct, args.keys, rng)
    net_decor = build_decor_net(net_orig, net_locked, key_inputs, promoted_keys)
    if args.emit:
        write_bench(net_decor, args.emit)
    print("STRUCTURAL_kstar (first 64):", structural_kstar[:64])
    print("N_PROMOTED_KEYS:", len(promoted_keys))
    print("First promoted key sample:", promoted_keys[0])
    print("Validating promoted keys with", args.validate_samples, "random inputs per key...")
    res = validate_promoted_keys(net_orig, net_decor, key_inputs, promoted_keys, samples=args.validate_samples, rng=rng)
    all_ok = True
    for pk, ok, mism in res:
        print("KEY:", pk[:min(64,len(pk))], "OK:", ok, "mismatches:", mism)
        if not ok:
            all_ok = False
    print("ALL_PROMOTED_OK:", all_ok)

if __name__ == "__main__":
    main()
