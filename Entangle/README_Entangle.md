# Entangle Locking & Simulation — Quickstart

This repository contains two standalone Python tools for logic locking and verification using an **ENTANGLE‑HD (split) with restore** workflow.

## Files

- `Entangle.py` — Locks a combinational `.bench` netlist with ENTANGLE‑HD (split perturb & split restore), optional cone‑mixing and dummy cones/keys for structural obfuscation.
- `Simulation_Ent.py` — Targeted simulator that reliably exercises the lock by generating **exact split Hamming‑distance** input patterns; validates golden vs locked for correct and wrong keys.

## Requirements

- Python 3.8+
- No external packages required

## Locking usage (Entangle.py)

Basic:
```bash
python Entangle.py \
  --in  /path/to/golden/C7552.bench \
  --out /path/to/locked/C7552_locked.bench \
  --h   2 \
  --seed 7
```

With structural hardening (cone‑mixing + dummy cones/keys):
```bash
python Entangle.py \
  --in  C7552.bench \
  --out C7552_locked.bench \
  --h 2 --seed 7 \
  --mix-per-bit 2 \
  --dummy-cones 3 \
  --dummy-keys 8
```

**Outputs**
- A locked `.bench` at `--out` whose `INPUT(...)` list equals:
  - `[original PIs] + [KEY0..KEY{k-1}] + [DKEY0..DKEY{d-1}]` (if `--dummy-keys > 0`)
- Console lines with the chosen parameters and the real KEY length.

**Notes**
- The baked‑in secret key is deterministically derived from `--seed` and the input filename.
- DKEY inputs drive only dummy cones (functional no‑ops) but are present in the locked netlist for structural obfuscation.

## Simulation usage (Simulation_Ent.py)

Targeted validation (forces the perturb trigger set):
```bash
# Prepare KEY bits as a continuous string "0101..."
python Simulation_Ent.py \
  --golden /path/to/golden/C7552.bench \
  --locked /path/to/locked/C7552_locked.bench \
  --key    010101... \
  --h 2 --num 40 --seed 1
```

With an explicit wrong key to observe flips:
```bash
python Simulation_Ent.py \
  --golden C7552.bench \
  --locked C7552_locked.bench \
  --key   0101... \
  --wrong 1101... \
  --h 2 --num 40 --seed 7
```

**Key length**
- `--key` must provide exactly **#original PIs** bits (the correct secret).  
- The simulator auto‑maps those bits as values for the KEY inputs in the locked file.  
- If your locked file includes DKEY inputs, they are ignored by the validator (no need to pass them).

**Expected results**
- Correct key: `"[OK] Correct key: N / N patterns matched"`
- Wrong key: `"[INFO] Wrong key: M / N patterns flipped"` (M > 0)

## Examples

Lock with obfuscation and then validate:
```bash
python Entangle.py --in C5315.bench --out C5315_locked.bench --h 2 --seed 5 --mix-per-bit 2 --dummy-cones 2 --dummy-keys 6

python Simulation_Ent.py \
  --golden C5315.bench \
  --locked C5315_locked.bench \
  --key    001011... \
  --wrong  101011... \
  --h 2 --num 40 --seed 5
```