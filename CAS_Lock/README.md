# CAS_Lock.py

A reference implementation of **CAS-Lock** (Cascaded Anti-SAT-style lock) for ISCAS-style BENCH circuits.

- Two keyed literal rails per tap: `s_i = XOR(x_i, KEYA_i)` and `t_i = XNOR(x_i, KEYB_i)`
- Dual cascades (`g`, `gbar`) built by alternating AND/OR (De Morgan duals)
- Trigger: `Y = AND(g, gbar)`
- Output corruption: `PO_locked = PO_orig XOR Y`
- Correct key (XOR/XNOR variant): **`KEYB = KEYA`** → `Y ≡ 0` for all inputs
---

## 1) Installation

```bash
python3 --version   # 3.8+
```

No external packages required.

---

## 2) Quick Start

Lock a circuit (default: tap first N data inputs, corrupt first output):

```bash
python3 CAS_Lock.py lock \
  --input C17.bench \
  --output C17_CAS_locked.bench \
  --N 4 \
  --correct-key 0101 0101
```

Test a **wrong key** (should observe mismatches):

```bash
python3 CAS_Lock.py simulate \
  --input C17_CAS_locked.bench \
  --orig  C17.bench \
  --key   01010100 \
  --random 1000 \
  --seed 1
```

> Key format: concatenate `KEYA0..KEYA(N-1)` then `KEYB0..KEYB(N-1)` as a bitstring: `KEY = KEYA || KEYB`.  
> For the **correct key** in XOR/XNOR mode, **`KEYB == KEYA`**.

---

## 3) CLI

### `lock`
```
python3 CAS_Lock.py lock
  --input PATH                # .bench file
  --output PATH               # output locked .bench (default: <input>_CAS_locked.bench)
  --N INT                     # number of PIs used by CAS-Lock
  --taps name1,name2,...      # optional explicit tap list (subset of primary data inputs)
  --target NAME               # which primary output to corrupt (default: first)
  --correct-key BITSTRING     # provide KEYA||KEYB; if omitted, printed after locking
  --seed INT                  # deterministic tap/ordering choices
```

### `simulate`
```
python3 CAS_Lock.py simulate
  --input PATH                # locked .bench
  --key BITSTRING             # KEYA||KEYB
  --orig PATH                 # golden .bench to compare against
  --random INT                # sample this many random patterns (mutually exclusive with --exhaustive)
  --exhaustive                # evaluate all patterns (small circuits)
  --seed INT                  # RNG seed for reproducibility
```

Outputs (example):
```
[Validation] Patterns=1000 | Matches(correct)=1000/1000 | Mismatches=0/1000
```

---

## 4) Keys, taps, and outputs

- **Taps (`N`)**: by default the first `N` primary **data** inputs (non-`KEY*`). You may pass `--taps` to choose any subset.
- **Keys (2N bits)**: `KEYA0..KEYA(N-1)` and `KEYB0..KEYB(N-1)` are created as new inputs.
- **Correct key rule** (XOR/XNOR): set **`KEYB == KEYA`** so `t_i = ¬s_i` and hence `Y ≡ 0`.
- **Locked outputs**: the corrupted PO is renamed to `<name>_LOCKED` in the locked netlist.

If your external validator matches outputs by name only, normalize names or compare by position.

---

