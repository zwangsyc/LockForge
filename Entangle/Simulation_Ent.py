#!/usr/bin/env python3
"""
SimulatorTargeted.py — Targeted validator for ENTANGLE-HD locked circuits.

It generates PI vectors that are EXACTLY h mismatches from the (correct) key,
split as h1 on the first half of PIs and h2 on the second (matching the Entangle split).
This reliably triggers the perturb path.

Usage:
  python SimulatorTargeted.py \
    --golden  /path/golden/C5315.bench \
    --locked  /path/locked/C5315_locked.bench \
    --key     0 1 0 1 ...        # correct key (space separated or single 0/1 string)
    --wrong   1 1 0 1 ...        # (optional) wrong key to test flips
    --h       2                  # target Hamming distance (default 2)
    --num     50                 # number of targeted vectors to test (randomly sampled)
    --seed    123

It prints match stats for the correct key and (if provided) the wrong key.
"""

import argparse, random, re, sys
from typing import List, Tuple

# ---------- parsing ----------
def _strip_inline_comment(s: str) -> str:
    for tok in ("//", "#"):
        if tok in s:
            s = s.split(tok, 1)[0]
    return s.strip()

def parse_bench(path: str) -> Tuple[List[str], List[str], List[dict]]:
    PIs, POs, gates = [], [], []
    with open(path) as f:
        for raw in f:
            line = _strip_inline_comment(raw)
            if not line: continue
            u = line.upper()
            if u.startswith("INPUT("):
                PIs.append(line[line.find("(")+1: line.find(")")].strip())
            elif u.startswith("OUTPUT("):
                POs.append(line[line.find("(")+1: line.find(")")].strip())
            elif "=" in line:
                out, rhs = line.split("=", 1)
                out = out.strip()
                typ = rhs[:rhs.find("(")].strip().upper()
                ins = [s.strip() for s in rhs[rhs.find("(")+1: rhs.rfind(")")].split(",")]
                gates.append({"out": out, "type": typ, "ins": ins})
    return PIs, POs, gates

# ---------- simulator (topological, robust) ----------
CONST1 = {"1","CONST1","VDD"}
CONST0 = {"0","CONST0","GND"}

def norm_type(t: str) -> str:
    t = t.upper()
    t = re.sub(r"\d+$","",t)  # AND3->AND, OR4->OR, etc.
    return "NOT" if t=="INV" else t

def reduce_bool(op: str, ins: List[int]) -> int:
    if op in ("AND","NAND"):
        v=1
        for x in ins: v &= x
        return v if op=="AND" else (0 if v==1 else 1)
    if op in ("OR","NOR"):
        v=0
        for x in ins: v |= x
        return v if op=="OR" else (0 if v==1 else 1)
    if op in ("XOR","XNOR"):
        v=0
        for x in ins: v ^= x
        return v if op=="XOR" else (v ^ 1)
    if op=="BUF":
        assert len(ins)==1; return ins[0]
    raise ValueError(f"Unsupported op: {op}")

def simulate(PIs: List[str], POs: List[str], gates: List[dict], values: dict) -> List[int]:
    env = dict(values)
    pending = [{"out":g["out"], "type":norm_type(g["type"]), "ins":list(g["ins"])} for g in gates]
    while pending:
        progressed=False; nxt=[]
        for g in pending:
            ins_vals=[]; ready=True
            for w in g["ins"]:
                if w in env: ins_vals.append(env[w])
                elif w in CONST1: ins_vals.append(1)
                elif w in CONST0: ins_vals.append(0)
                else: ready=False; break
            if not ready: nxt.append(g); continue
            t=g["type"]
            if t=="NOT":
                if len(ins_vals)!=1: raise ValueError(f"NOT expects 1 input, got {len(ins_vals)}")
                v=0 if ins_vals[0] else 1
            else:
                v=reduce_bool(t, ins_vals)
            env[g["out"]]=v; progressed=True
        if not progressed:
            g=nxt[0]
            missing=[w for w in g["ins"] if w not in env and w not in CONST0 and w not in CONST1]
            raise ValueError(f"Stuck; missing nets (first few): {missing[:8]} in gate {g}")
        pending=nxt
    return [env[o] for o in POs]

# ---------- utils ----------
def bits_from_cli(seq: List[str]) -> List[int]:
    return [int(ch) for ch in seq[0]] if (len(seq)==1 and set(seq[0])<={"0","1"}) else [int(x) for x in seq]

def sample_target_vectors(key_bits: List[int], h: int, num: int, seed: int) -> List[List[int]]:
    """
    ENTANGLE split: h1 on first half, h2 on second.
    Returns 'num' PI vectors produced by flipping those many bits from the key.
    """
    rnd = random.Random(seed)
    n = len(key_bits)
    n1 = n//2; n2 = n - n1
    h1 = h//2; h2 = h - h1
    if h1>n1 or h2>n2:
        raise ValueError(f"h split (h1={h1}, h2={h2}) exceeds half sizes (n1={n1}, n2={n2})")
    idx1 = list(range(n1)); idx2 = list(range(n1, n))
    vecs=[]
    for _ in range(num):
        flip1 = rnd.sample(idx1, h1) if h1>0 else []
        flip2 = rnd.sample(idx2, h2) if h2>0 else []
        v = key_bits.copy()
        for i in flip1+flip2: v[i]^=1
        vecs.append(v)
    return vecs

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Targeted ENTANGLE-HD validator (exact HD=h vectors)")
    ap.add_argument("--golden", required=True, help="Path to golden/original .bench")
    ap.add_argument("--locked", required=True, help="Path to locked .bench")
    ap.add_argument("--key",    nargs="+", required=True, help="Correct key bits (space-separated or single string)")
    ap.add_argument("--wrong",  nargs="+", help="Optional WRONG key bits to test flips")
    ap.add_argument("--h",      type=int, default=2, help="Target Hamming distance h (default 2)")
    ap.add_argument("--num",    type=int, default=32, help="Number of targeted vectors (default 32)")
    ap.add_argument("--seed",   type=int, default=0,  help="PRNG seed (default 0)")
    args = ap.parse_args()

    # parse nets
    PIs_g, POs_g, gates_g = parse_bench(args.golden)
    PIs_l, POs_l, gates_l = parse_bench(args.locked)

    # sanity: IO sizes
    n_pi = len(PIs_g)
    if len(POs_g)!=len(POs_l):
        print(f"[ERROR] Outputs differ: golden={len(POs_g)} locked={len(POs_l)}", file=sys.stderr); sys.exit(2)
    if len(PIs_l) < n_pi:
        print(f"[ERROR] Locked has fewer INPUTs than golden", file=sys.stderr); sys.exit(2)
    n_keys = len(PIs_l) - n_pi

    key_bits = bits_from_cli(args.key)
    if len(key_bits)!=n_pi:
        print(f"[ERROR] Correct key length {len(key_bits)} must equal #golden PIs {n_pi}", file=sys.stderr); sys.exit(2)

    wrong_bits = None
    if args.wrong:
        wrong_bits = bits_from_cli(args.wrong)
        if len(wrong_bits)!=n_keys:
            print(f"[ERROR] Wrong key length {len(wrong_bits)} must equal #locked KEY inputs {n_keys}", file=sys.stderr); sys.exit(2)

    # Generate EXACT-HD vectors around the (correct) key, respecting the split
    pi_vecs = sample_target_vectors(key_bits, args.h, args.num, args.seed)

    # Run with correct key: should all MATCH
    mism_ok=0
    for v in pi_vecs:
        env_g = {n:b for n,b in zip(PIs_g, v)}
        env_l = {n:b for n,b in zip(PIs_l[:n_pi], v)}
        # KEY inputs appended at end in locked file:
        for name, bit in zip(PIs_l[n_pi:], key_bits): env_l[name]=bit
        if simulate(PIs_g, POs_g, gates_g, env_g) != simulate(PIs_l, POs_l, gates_l, env_l):
            mism_ok += 1
    if mism_ok==0:
        print(f"[OK] Correct key: {len(pi_vecs)} / {len(pi_vecs)} patterns matched ✅")
    else:
        print(f"[WARN] Correct key mismatches: {mism_ok} / {len(pi_vecs)} ❌")

    # Run with wrong key (if provided): expect MANY NON-matches
    if wrong_bits is not None:
        mism_bad=0
        for v in pi_vecs:
            env_g = {n:b for n,b in zip(PIs_g, v)}
            env_l = {n:b for n,b in zip(PIs_l[:n_pi], v)}
            for name, bit in zip(PIs_l[n_pi:], wrong_bits): env_l[name]=bit
            if simulate(PIs_g, POs_g, gates_g, env_g) != simulate(PIs_l, POs_l, gates_l, env_l):
                mism_bad += 1
        print(f"[INFO] Wrong key: {mism_bad} / {len(pi_vecs)} patterns flipped (expected > 0)")

if __name__ == "__main__":
    main()
