#!/usr/bin/env python3
import argparse, random, sys
from itertools import product
from math import comb
from typing import Dict, List, Tuple

class BenchCircuit:
    def __init__(self, bench_text: str):
        self.inputs: List[str] = []
        self.outputs: List[str] = []
        self.gates: Dict[str, Tuple[str, List[str]]] = {}
        self._parse(bench_text)
        self.eval_order = self._topo_order()

    def _normalize_gate(self, g: str) -> str:
        g = g.upper().strip()
        alias = {"INV": "NOT", "BUFF": "BUF", "BUFFER": "BUF"}
        g = alias.get(g, g)
        while g and g[-1].isdigit():
            g = g[:-1]
        if ("DFF" in g) or ("LATCH" in g) or g in {"FD","FDX","FD1","REG","GREG"}:
            return "DFF"
        return g


    def _parse(self, text: str):
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            # strip inline comments
            for tok in ("//", "#", ";"):
                if tok in line:
                    line = line.split(tok, 1)[0].strip()
            if not line:
                continue

            up = line.upper()
            if up.startswith("INPUT("):
                name = line[line.find("(")+1: line.find(")")].strip()
                if name and name not in self.inputs:
                    self.inputs.append(name)
                continue
            if up.startswith("OUTPUT("):
                name = line[line.find("(")+1: line.find(")")].strip()
                if name and name not in self.outputs:
                    self.outputs.append(name)
                continue

            if "=" not in line:
                # skip stray symbols like "WX83"
                continue

            left, right = [s.strip() for s in line.split("=", 1)]
            if not left or not right:
                continue

            # constants: A = 0 / A = 1
            if right in {"0", "1"}:
                const_node = "__CONST1__" if right == "1" else "__CONST0__"
                if const_node not in self.inputs:
                    self.inputs.append(const_node)
                self.gates[left] = ("BUF", [const_node])
                continue

            # alias: A = B  (no parentheses)
            if "(" not in right or ")" not in right:
                self.gates[left] = ("BUF", [right])
                continue

            gate_name = right[: right.find("(")].strip()
            gate_upper = self._normalize_gate(gate_name)
            args_str = right[right.find("(")+1: right.rfind(")")]
            ins = [a.strip() for a in args_str.split(",") if a.strip()]

            if gate_upper == "DFF":
                if left not in self.inputs:
                    self.inputs.append(left)
                continue

            if gate_upper == "INV":
                gate_upper = "NOT"
            self.gates[left] = (gate_upper, ins)




    def _topo_order(self) -> List[str]:
        deps = {o: set(ins) for o, (_, ins) in self.gates.items()}
        known = set(self.inputs)
        order, rem = [], set(self.gates.keys())
        change = True
        while rem and change:
            change = False
            for o in list(rem):
                if deps[o].issubset(known):
                    order.append(o)
                    known.add(o)
                    rem.remove(o)
                    change = True
        if rem:
            raise ValueError('Topo-sort failed; unknown or cyclic nets remain')
        return order

    @staticmethod
    def _eval_gate(g: str, ins: List[int]) -> int:
        if g == 'BUF': return ins[0]
        if g == 'NOT': return 1 - ins[0]
        if g == 'AND': return int(all(ins))
        if g == 'NAND': return 1 - int(all(ins))
        if g == 'OR':  return int(any(ins))
        if g == 'NOR': return 1 - int(any(ins))
        if g == 'XOR':
            v = 0
            for b in ins: v ^= b
            return v
        if g == 'XNOR':
            v = 0
            for b in ins: v ^= b
            return 1 - v
        raise ValueError(f'Unsupported gate {g}')

    def evaluate(self, input_vec: Dict[str, int]) -> Dict[str, int]:
        vals: Dict[str, int] = {}
        # built-in constants if referenced
        if "__CONST0__" in self.inputs:
            vals["__CONST0__"] = 0
        if "__CONST1__" in self.inputs:
            vals["__CONST1__"] = 1

        for i in self.inputs:
            if i not in input_vec: raise ValueError(f'Missing input {i}')
            b = int(input_vec[i])
            if b not in (0,1): raise ValueError(f'Input {i} must be 0/1')
            vals[i] = b
        for o in self.eval_order:
            g, ins = self.gates[o]
            vals[o] = self._eval_gate(g, [vals[n] for n in ins])
        return {o: vals[o] for o in self.outputs}

def hamming_distance(a: List[int], b: List[int]) -> int:
    return sum(x ^ y for x, y in zip(a, b))

class SFLLHD:
    def __init__(self, circuit: BenchCircuit, selected_pis: List[str], h: int, secret_key_bits: List[int]):
        self.circ = circuit
        self.sel = selected_pis
        self.k = len(selected_pis)
        self.h = int(h)
        self.secret_key = [int(b) for b in secret_key_bits]
        if len(self.secret_key) != self.k: raise ValueError('key length mismatch')
        if not (0 <= self.h <= self.k): raise ValueError('h out of range')

    def _proj(self, iv: Dict[str,int]) -> List[int]:
        return [int(iv[n]) for n in self.sel]

    def strip_pred(self, iv: Dict[str,int]) -> int:
        return int(hamming_distance(self._proj(iv), self.secret_key) == self.h)

    @staticmethod
    def restore_pred(x_bits: List[int], key_bits: List[int], h: int) -> int:
        return int(hamming_distance(x_bits, key_bits) == h)

    def fsc_outputs(self, iv: Dict[str,int]) -> Dict[str,int]:
        gold = self.circ.evaluate(iv)
        p = self.strip_pred(iv)
        return {o: gold[o] ^ p for o in gold}

    def locked_outputs(self, iv: Dict[str,int], provided_key_bits: List[int]) -> Dict[str,int]:
        gold = self.circ.evaluate(iv)
        p = self.strip_pred(iv)
        r = self.restore_pred(self._proj(iv), [int(b) for b in provided_key_bits], self.h)
        return {o: gold[o] ^ p ^ r for o in gold}

def bits_from_str(s: str) -> List[int]:
    bs = []
    for ch in s.strip().lower():
        if ch in '01': bs.append(int(ch))
        elif ch in ' _-': continue
        else: raise ValueError('invalid bit')
    return bs

def hex_to_bits(hex_str: str, k: int) -> List[int]:
    s = hex_str.strip().lower()
    if s.startswith('0x'): s = s[2:]
    v = int(s, 16)
    return [(v >> i) & 1 for i in range(k)][::-1]

def emit_locked_bench(bench_text: str, selected_pis: List[str], h: int, secret_key_bits: List[int],
                      key_prefix: str = 'K') -> str:
    circ = BenchCircuit(bench_text)
    k = len(selected_pis)
    if not (0 <= h <= k): raise ValueError('h out of range')
    if len(secret_key_bits) != k: raise ValueError('secret key length mismatch')
    import itertools
    counter = itertools.count()
    def w(prefix): return f"SFLL_{prefix}_{next(counter)}"
    lines = []
    for i in circ.inputs: lines.append(f"INPUT({i})")
    for i in range(k): lines.append(f"INPUT({key_prefix}{i})")
    for out,(g,ins) in circ.gates.items():
        lines.append(f"{out} = {g}({', '.join(ins)})")
    mp = []
    for i, pi in enumerate(selected_pis):
        if int(secret_key_bits[i]) == 0:
            t = w("PBUF"); lines.append(f"{t} = BUF({pi})")
        else:
            t = w("PNOT"); lines.append(f"{t} = NOT({pi})")
        mp.append(t)
    mr = []
    for i, pi in enumerate(selected_pis):
        ki = f"{key_prefix}{i}"
        t = w("RXOR"); lines.append(f"{t} = XOR({pi}, {ki})")
        mr.append(t)
    def popcount(bits: List[str], width: int) -> List[str]:
        acc = [w("ACC0") for _ in range(width)]
        zero = [w("Z0") for _ in range(width)]
        lines.append(f"{zero[0]} = BUF({bits[0]})")
        for i in range(1,width): lines.append(f"{zero[i]} = BUF({zero[i-1]})")
        for i in range(width): lines.append(f"{acc[i]} = BUF({zero[i]})")
        for b in bits[1:]:
            carry = b
            for i in range(width):
                s = w("SUM"); c = w("CARRY")
                lines.append(f"{s} = XOR({acc[i]}, {carry})")
                lines.append(f"{c} = AND({acc[i]}, {carry})")
                acc[i] = s
                carry = c
        return acc
    width = max(1, k.bit_length())
    sumP = popcount(mp, width)
    sumR = popcount(mr, width)
    def eq_to_const(sum_bits: List[str], value: int, width: int) -> str:
        terms = []
        for i in range(width):
            bit = (value >> i) & 1
            if bit == 1:
                terms.append(sum_bits[i])
            else:
                nb = w("NB"); lines.append(f"{nb} = NOT({sum_bits[i]})")
                terms.append(nb)
        if len(terms) == 1:
            return terms[0]
        eq = w("EQ")
        lines.append(f"{eq} = AND({', '.join(terms)})")
        return eq
    P_eq = eq_to_const(sumP, h, width)
    R_eq = eq_to_const(sumR, h, width)
    locked_outs = []
    for o in circ.outputs:
        t1 = w("XO1"); lines.append(f"{t1} = XOR({o}, {P_eq})")
        t2 = w("XO2"); lines.append(f"{t2} = XOR({t1}, {R_eq})")
        locked_outs.append((o, t2))
    for _, lo in locked_outs:
        lines.append(f"OUTPUT({lo})")
    return "\n".join(lines) + "\n"

def enumerate_inputs(names: List[str]) -> List[Dict[str,int]]:
    return [{n:b for n,b in zip(names,t)} for t in product([0,1], repeat=len(names))]

def sample_inputs(names: List[str], n: int, rng: random.Random) -> List[Dict[str,int]]:
    return [{name: rng.randint(0,1) for name in names} for _ in range(n)]

def parse_args():
    p = argparse.ArgumentParser(description='SFLL-HD simulator + locked netlist emitter')
    p.add_argument('bench', help='Path to .bench')
    p.add_argument('--h', type=int, required=True)
    sel = p.add_mutually_exclusive_group()
    sel.add_argument('--k', type=int)
    sel.add_argument('--all', action='store_true')
    p.add_argument('--pi-list', type=str)
    key = p.add_mutually_exclusive_group()
    key.add_argument('--secret-key', type=str)
    key.add_argument('--secret-key-hex', type=str)
    p.add_argument('--seed', type=int, default=7)
    prov = p.add_mutually_exclusive_group()
    prov.add_argument('--provided-key', type=str)
    prov.add_argument('--flip-bit', type=int)
    p.add_argument('--max-enum', type=int, default=20)
    p.add_argument('--patterns', type=int, default=10000)
    p.add_argument('--emit-locked', type=str, help='Write locked BENCH to this path')
    p.add_argument('--key-prefix', type=str, default='K')
    return p.parse_args()

def bits_from_opt(val: str, k: int, rng: random.Random) -> List[int]:
    if val is None:
        return [rng.randint(0,1) for _ in range(k)]
    s = val.strip().lower()
    if s.startswith('0x'):
        return hex_to_bits(s, k)
    return bits_from_str(s)

def main():
    args = parse_args()
    bench_text = open(args.bench, 'r').read()
    circ = BenchCircuit(bench_text)
    if args.pi_list:
        selected = [t.strip() for t in args.pi_list.split(',') if t.strip()]
        for n in selected:
            if n not in circ.inputs: raise ValueError(f'unknown PI {n!r}')
    elif args.all:
        selected = circ.inputs[:]
    elif args.k is not None:
        if args.k <= 0 or args.k > len(circ.inputs): raise ValueError(f'--k must be in 1..{len(circ.inputs)}')
        selected = circ.inputs[:args.k]
    else:
        selected = circ.inputs[:]
    k = len(selected)
    rng = random.Random(args.seed)
    if args.secret_key:
        secret_key = bits_from_opt(args.secret_key, k, rng)
    elif args.secret_key_hex:
        secret_key = hex_to_bits(args.secret_key_hex, k)
    else:
        secret_key = [rng.randint(0,1) for _ in range(k)]
    if args.provided_key:
        provided_key = bits_from_opt(args.provided_key, k, rng)
    elif args.flip_bit is not None:
        if not (0 <= args.flip_bit < k): raise ValueError('flip index out of range')
        provided_key = secret_key[:]
        provided_key[args.flip_bit] ^= 1
    else:
        provided_key = secret_key[:]
    sfll = SFLLHD(circ, selected, args.h, secret_key)
    if len(circ.inputs) <= args.max_enum:
        vectors = enumerate_inputs(circ.inputs); enum = True
    else:
        vectors = sample_inputs(circ.inputs, args.patterns, rng); enum = False
    def stats(key_bits: List[int]):
        mism, total, avg = 0, 0, 0.0
        for iv in vectors:
            g = circ.evaluate(iv)
            y = sfll.locked_outputs(iv, key_bits)
            d = sum(g[o] ^ y[o] for o in circ.outputs)
            avg += d; total += 1
            if d > 0: mism += 1
        return dict(fraction_any_output_wrong=(mism/total if total else 0.0),
                    avg_output_hamming_per_vector=(avg/total if total else 0.0),
                    num_vectors=total)
    stats_ck = stats(secret_key)
    stats_pk = stats(provided_key)
    rem_wrong = 0
    for iv in vectors:
        if any(circ.evaluate(iv)[o] != sfll.fsc_outputs(iv)[o] for o in circ.outputs):
            rem_wrong += 1
    removal_frac = rem_wrong / len(vectors) if vectors else 0.0
    mode = "enumerated" if enum else "random-sampled"
    print(f"File: {args.bench}")
    print(f"Inputs: {circ.inputs}")
    print(f"Outputs: {circ.outputs}")
    print(f"Selected PIs (k={k}): {selected}")
    print(f"h={args.h}, secret_key={secret_key}, provided_key={provided_key}")
    print(f"Vectors: {mode} ({len(vectors)})\n")
    print("[Correct Key] (should be zero corruption):")
    for k_,v in stats_ck.items():
        print(f"  {k_}: {v:.6f}" if isinstance(v,float) else f"  {k_}: {v}")
    print("\n[Provided Key] Global corruption:")
    for k_,v in stats_pk.items():
        print(f"  {k_}: {v:.6f}" if isinstance(v,float) else f"  {k_}: {v}")
    print("\n[Removal-Resilience] FSC-only corruption fraction:")
    if enum:
        exp = comb(k, args.h) / (2 ** k)
        print(f"  Observed: {removal_frac:.6f}")
        print(f"  Expected: {exp:.6f} (= C(k,h)/2^k)")
    else:
        print(f"  Observed (on sample): {removal_frac:.6f}")
        print("  Expected = C(k,h)/2^k (exact value shown only for full enumeration)")
    if args.emit_locked:
        locked_text = emit_locked_bench(bench_text, selected, args.h, secret_key, key_prefix=args.key_prefix)
        with open(args.emit_locked, 'w') as f:
            f.write(locked_text)
        print(f"\nLocked BENCH written to: {args.emit_locked}")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
