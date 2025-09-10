
# SARO Logic Locker — `SARO.py`

A Python implementation of a SARO-style logic locking flow using a **rename-then-wrap** strategy with multiple T3 transforms, optional sequential slicing, and built‑in sanity checks.

---

## Features
- **Rename‑then‑wrap** locking at selected nodes
- **T3 transforms**: invert, substitute, gated‑xor, random; optional pairwise shuffle/arithmetic
- **Partitioning** via topo‑aware chunking and boundary targeting
- **Sequential support**: one‑frame cut for DFFs (Q→PI*, D→PO*)
- **Validation**: compares golden vs locked(+correct key) and probes with a wrong key
- Deterministic runs with `--seed`; configurable key length

> Produces a locked `.bench` that matches the original with the correct key and corrupts outputs for wrong keys.

---

## Requirements
- Python **3.8+**
- No external packages required

---

## Quickstart

```bash
python3 SARO.py \
  --in  ./c7552.bench \
  --out ./c7552_locked.bench \
  --key-size 32 \
  --seed 7 \
  --validate \
  --patterns 256
```

**Stdout includes:**
- Locked file path
- Printed **correct key (K\*)** (0/1 string)
- Validation summary, e.g. `Matches(correct)=256/256 | Matches(wrong)=0/256`

---

## Command‑line options

| Flag | Description |
|-----:|-------------|
| `--in` | Input `.bench` netlist (combinational or sequential) |
| `--out` | Output locked `.bench` path |
| `--key-size` | Number of key bits (e.g., 32/64) |
| `--seed` | RNG seed for deterministic locking |
| `--validate` | Enable simulation checks vs golden |
| `--patterns` | Number of random patterns for validation |
| `--enable-width` | Approx. number of key bits mixed per site |
| `--couple-locals` | Local signals to mix into enables |
| `--no-pairwise` | Disable pairwise T3 (shuffle/arithmetic) |

---

## Examples

### Small ISCAS’85
```bash
python3 SARO.py \
  --in ./C17.bench \
  --out ./C17_locked.bench \
  --key-size 8 \
  --seed 1 \
  --validate --patterns 128
```

### Larger netlist with stronger mixing
```bash
python3 SARO.py \
  --in ./c7552.bench \
  --out ./c7552_locked.bench \
  --key-size 32 \
  --seed 7 \
  --enable-width 7 \
  --couple-locals 4 \
  --validate --patterns 512
```

### Sequential designs (ISCAS’89)
The script applies a one‑frame **sequential cut** automatically. DFF Q pins become extra PIs and D pins extra POs for locking.

```bash
python3 SARO.py \
  --in ./s5378.bench \
  --out ./s5378_locked.bench \
  --key-size 32 \
  --seed 5 \
  --validate --patterns 256
```

---
