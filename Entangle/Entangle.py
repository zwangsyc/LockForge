#!/usr/bin/env python3
"""
entangle_hd_strong.py
---------------------

ENTANGLE-HD (split) with:
  • Split perturb  : PP = (HD(first_half, key1)==h1) ∧ (HD(second_half, key2)==h2)
  • Split restore  : RS = (HD(first_half, KEY1)==h1) ∧ (HD(second_half, KEY2)==h2)
  • CTRL + outputs : CTRL = PP ⊕ RS;  PO_locked = PO ⊕ CTRL
  • Cone mixing    : each protected bit is XOR'ed with a small function of *external* nets
  • Dummy cones    : D dummy (constant vs DKEY) HD cones injected via a canceling path
                      so behavior is unchanged but structure is much harder to isolate

Inputs order in locked .bench:  [original PIs] + [KEY0..KEY{k-1}] + [DKEY0..DKEY{d-1}]

Usage example
  python entangle_hd_strong.py \
      --in  /path/in.bench \
      --out /path/out_locked.bench \
      --h 2 --seed 7 \
      --mix-per-bit 2 \
      --dummy-cones 2 --dummy-keys 4
"""

import argparse, random, os
from typing import List, Tuple

# -------------------- parsing/writing --------------------
def _strip(line: str) -> str:
    for t in ("//", "#"):
        if t in line: line = line.split(t, 1)[0]
    return line.strip()

def parse_bench(path: str):
    PIs, POs, gates = [], [], []
    with open(path) as f:
        for raw in f:
            s = _strip(raw)
            if not s: continue
            u = s.upper()
            if u.startswith("INPUT("):
                PIs.append(s[s.find("(")+1:s.find(")")].strip())
            elif u.startswith("OUTPUT("):
                POs.append(s[s.find("(")+1:s.find(")")].strip())
            elif "=" in s:
                out, rhs = s.split("=", 1)
                out = out.strip()
                typ = rhs[:rhs.find("(")].strip().upper()
                ins = [x.strip() for x in rhs[rhs.find("(")+1:rhs.rfind(")")].split(",")]
                gates.append({"out": out, "type": typ, "ins": ins})
    return PIs, POs, gates

def write_bench(path: str, PIs: List[str], POs: List[str], gates: List[dict]):
    with open(path, "w") as f:
        for pi in PIs: f.write(f"INPUT({pi})\n")
        for po in POs: f.write(f"OUTPUT({po})\n")
        for g in gates: f.write(f"{g['out']} = {g['type']}({','.join(g['ins'])})\n")

# -------------------- builder --------------------
class NetlistBuilder:
    def __init__(self, PIs, POs, gates):
        self.PIs   = list(PIs)
        self.POs   = list(POs)
        self.gates = list(gates)
        self._ctr  = 0
    def fresh(self, prefix="n"):
        self._ctr += 1
        return f"{prefix}{self._ctr}"
    def add(self, typ: str, ins: List[str]) -> str:
        out = self.fresh(typ.lower())
        self.gates.append({"out": out, "type": typ, "ins": ins})
        return out

# -------------------- helpers: popcount == const --------------------
def popcount(builder: NetlistBuilder, bits: List[str]) -> List[str]:
    """Return vector of sum bits (LSB first) using XOR/AND ripple with a CONST0 seed."""
    width = (len(bits) + 1).bit_length()
    acc = ["CONST0"] * width
    for m in bits:
        carry = m
        nxt = []
        for a in acc:
            if a == "CONST0":
                s, c = carry, "CONST0"
            else:
                s = builder.add("XOR", [a, carry])
                c = builder.add("AND", [a, carry])
            nxt.append(s); carry = c
        acc = nxt
    return acc

def eq_const(builder: NetlistBuilder, sumv: List[str], const: int) -> str:
    terms = []
    for i, b in enumerate(sumv):
        want = (const >> i) & 1
        terms.append(b if want else builder.add("NOT", [b]))
    out = terms[0]
    for t in terms[1:]:
        out = builder.add("AND", [out, t])
    return out

# -------------------- mixing: build per-bit external XOR salt --------------------
def build_mixers(builder: NetlistBuilder, protected: List[str], externals: List[str],
                 mix_per_bit: int, rnd: random.Random) -> List[str]:
    """
    For each protected bit P, create MIX_i = XOR of small functions of external nets.
    If externals is small, we fall back to XOR among a few (possibly repeated) externals.
    Returns list MIX_i nets aligned to 'protected'.
    """
    if mix_per_bit <= 0 or not externals:
        return ["CONST0"] * len(protected)

    mixers = []
    for _ in protected:
        picks = [externals[rnd.randrange(len(externals))] for _ in range(mix_per_bit)]
        # Optionally non-linearize with an AND on two picks, then XOR the rest
        base = None
        if len(picks) >= 2:
            base = builder.add("AND", [picks[0], picks[1]])
            for w in picks[2:]:
                base = builder.add("XOR", [base, w])
        else:
            base = picks[0]
        mixers.append(base)
    return mixers

# -------------------- ENTANGLE-HD + split restore + mixing + dummies --------------------
def add_entangle_hd_strong(builder: NetlistBuilder,
                           key_bits: List[int],  # baked-in secret (length = #protected)
                           h: int,
                           mix_per_bit: int = 2,
                           dummy_cones: int = 0,
                           dummy_keys: int = 0,
                           seed: int = 0):
    """
    Protect ALL original PIs by default; add KEY inputs (for real restore) and DKEY for dummies.
    Entanglement:
      - mix each protected bit with a cone-external salt before HD checks: P' = P ⊕ MIX_i
      - split both PP and RS across halves with h1/h2; AND to combine
      - inject D dummy cones via a canceling pair (XOR T early, XOR (CTRL ⊕ T) late) so behavior is unchanged
    """
    rnd = random.Random(seed)
    orig_PIs = builder.PIs[:]        # protected set = all PIs
    k = len(orig_PIs)
    if k == 0:
        raise ValueError("No primary inputs to protect.")

    # Split parameters (same for PP and RS)
    n1 = k // 2; n2 = k - n1
    h1 = h // 2; h2 = h - h1
    if not (0 <= h1 <= n1 and 0 <= h2 <= n2):
        raise ValueError(f"Infeasible (h1={h1} vs n1={n1}, h2={h2} vs n2={n2}).")

    # Add real key inputs
    key_nets = [f"KEY{i}" for i in range(k)]
    builder.PIs.extend(key_nets)

    # Add dummy key inputs (structural only)
    dkey_nets = [f"DKEY{i}" for i in range(dummy_keys)]
    builder.PIs.extend(dkey_nets)

    # Gather "external" nets to mix: all existing gate outputs (cone-external to PIs)
    externals = [g["out"] for g in builder.gates]
    # Build per-bit mixers
    mixers = build_mixers(builder, orig_PIs, externals, mix_per_bit, rnd)

    # --- derive mixed protected bits (same for PP and RS paths) ---
    # Pmix_i = P_i XOR MIX_i
    pmix = [builder.add("XOR", [p, m]) if m != "CONST0" else p
            for p, m in zip(orig_PIs, mixers)]

    # ---------- PERTURB (constant key) ----------
    # mism_i = Pmix_i XOR constbit
    def mismatches_const(bits: List[str], const_bits: List[int]) -> List[str]:
        out = []
        for bnet, cb in zip(bits, const_bits):
            out.append(builder.add("NOT", [bnet]) if cb == 1 else bnet)
        return out

    pmix1, pmix2 = pmix[:n1], pmix[n1:]
    kfix1, kfix2 = key_bits[:n1], key_bits[n1:]

    mm1 = mismatches_const(pmix1, kfix1)
    mm2 = mismatches_const(pmix2, kfix2)
    PP1 = eq_const(builder, popcount(builder, mm1), h1)
    PP2 = eq_const(builder, popcount(builder, mm2), h2)
    PP  = builder.add("AND", [PP1, PP2])

    # ---------- RESTORE (dynamic key mirrors split) ----------
    kin1, kin2 = key_nets[:n1], key_nets[n1:]
    mmr1 = [builder.add("XOR", [a, b]) for a, b in zip(pmix1, kin1)]
    mmr2 = [builder.add("XOR", [a, b]) for a, b in zip(pmix2, kin2)]
    RS1  = eq_const(builder, popcount(builder, mmr1), h1)
    RS2  = eq_const(builder, popcount(builder, mmr2), h2)
    RS   = builder.add("AND", [RS1, RS2])

    CTRL = builder.add("XOR", [PP, RS])

    # ---------- DUMMY CONES (optional, canceling injection) ----------
    T_terms = []
    for j in range(dummy_cones):
        # choose a small random subset of PIs (size s), and a dummy target hd dj (0..s)
        s  = max(2, min(6, k // 8 or 2))
        idx = sorted(rnd.sample(range(k), s))
        subP = [orig_PIs[i] for i in idx]

        # Mix these too (use same mixers for those indices)
        subMix = [mixers[i] for i in idx]
        subPmix = [builder.add("XOR", [p, m]) if m != "CONST0" else p
                   for p, m in zip(subP, subMix)]

        # pick dummy key *constants* (baked-in) and dummy dynamic *dkey* inputs
        dconst = [rnd.randint(0,1) for _ in range(s)]
        if not dkey_nets:
            # If no DKEY nets, still build dynamic side against a pseudo net made from externals
            # (keeps structure; functionally arbitrary)
            if externals:
                dyn = externals[rnd.randrange(len(externals))]
                dkin = [dyn for _ in range(s)]
            else:
                # fallback: just reuse first PI (structural noise)
                dkin = [orig_PIs[0] for _ in range(s)]
        else:
            # map each to a DKEY (wrap if needed)
            dkin = [dkey_nets[(j+i) % len(dkey_nets)] for i in range(s)]

        dj = rnd.randint(0, min(2, s))  # small target distance (0..2)
        # CONST branch
        mmc = [builder.add("NOT", [b]) if cb==1 else b for b, cb in zip(subPmix, dconst)]
        DPP = eq_const(builder, popcount(builder, mmc), dj)
        # DKEY branch
        mmr = [builder.add("XOR", [a, b]) for a, b in zip(subPmix, dkin)]
        DRS = eq_const(builder, popcount(builder, mmr), dj)
        T_terms.append(builder.add("XOR", [DPP, DRS]))

    T = None
    for t in T_terms:
        T = t if T is None else builder.add("XOR", [T, t])

    # For canceling injection: for each PO do PO1 = PO XOR T  (if T exists)
    # then compute C1 = CTRL if no T, else C1 = CTRL XOR T, and final PO' = PO1 XOR C1
    new_POs = []
    if T is None:
        for po in builder.POs:
            new_POs.append(builder.add("XOR", [po, CTRL]))
    else:
        C1 = builder.add("XOR", [CTRL, T])
        for po in builder.POs:
            po1 = builder.add("XOR", [po, T])
            new_POs.append(builder.add("XOR", [po1, C1]))
    builder.POs[:] = new_POs

# -------------------- main --------------------
def main():
    ap = argparse.ArgumentParser(description="ENTANGLE-HD with split restore, cone mixing, and dummy cones")
    ap.add_argument("--in",  required=True, dest="in_path",  help="Input .bench (combinational)")
    ap.add_argument("--out", required=True, dest="out_path", help="Output locked .bench")
    ap.add_argument("--h",   type=int, default=2, help="Target Hamming distance")
    ap.add_argument("--seed", type=int, default=0, help="Seed for deterministic choices")
    ap.add_argument("--mix-per-bit", type=int, default=2, help="Number of external nets mixed into each protected bit")
    ap.add_argument("--dummy-cones", type=int, default=0, help="Number of dummy cones to insert")
    ap.add_argument("--dummy-keys", type=int, default=0, help="Number of DKEY inputs to add")
    args = ap.parse_args()

    PIs, POs, gates = parse_bench(args.in_path)
    nb = NetlistBuilder(PIs, POs, gates)

    # Derive a deterministic baked-in key equal to #PIs (you can swap in your own)
    rnd = random.Random(f"{args.seed}:{os.path.basename(args.in_path)}")
    key_bits = [rnd.randint(0,1) for _ in nb.PIs]  # one key bit per protected PI

    add_entangle_hd_strong(
        nb,
        key_bits=key_bits,
        h=args.h,
        mix_per_bit=args.mix_per_bit,
        dummy_cones=args.dummy_cones,
        dummy_keys=args.dummy_keys,
        seed=args.seed
    )

    write_bench(args.out_path, nb.PIs, nb.POs, nb.gates)
    print(f"[OK] Locked → {args.out_path}")
    print(f"[INFO] KEY length={len(key_bits)}  DKEY={args.dummy_keys}  h={args.h}  mix_per_bit={args.mix_per_bit}")

if __name__ == "__main__":
    main()
