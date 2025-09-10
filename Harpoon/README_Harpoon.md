# HARPOON Emitter (flattened)

This script **emits a HARPOON‑locked ISCAS‑89 `.bench`** circuit. It inserts an entrance controller (OBF→AUTH→UNLOCKED with TRAP), SE/LFSR, state‑conditioned corruption/restore (E/R), scan/test hooks, and *flattens* every gate to a single assignment (no nested calls).

## Usage
```bash
python harpoon.py \
  --in <input.bench> \
  --out <locked_output.bench> \
  --obf-seq <csv_bits> \
  --auth-seq <csv_bits> \
  --num-se <int> \
  --seed <int>
```

### Arguments
- `--in` (required): path to the source `.bench`.
- `--out` (required): where to write the locked `.bench`.
- `--obf-seq` (default `1,0,1`): comma‑separated bits for the **obfuscation** phase key.
- `--auth-seq` (default `1,1`): comma‑separated bits for the **authentication** phase key.
- `--num-se` (default `4`): number of SE/LFSR bits inserted.
- `--seed` (default `2025`): PRNG seed for deterministic structure/wiring.

## What the locked netlist adds
- Inputs: `KEY`, `RST`, `SCAN_EN`, `TEST_MODE`, `TEST_KEY_OK`
- State: `OBF_S*`, `AUTH_S*`, `UNLOCKED`, `TRAP`, `SE*`
- Gating: `R_EFF`, `E_EFF`, and corruption nets `CORR`, `CORR_G`
- Primary outputs are rewritten as `PO = BUF(XOR(PO_ORIG, CORR_G))`

## Quick examples
```bash
# s5378 with one key
python harpoon.py --in s5378.bench --out s5378_harp.bench   --obf-seq 1,1,0,1 --auth-seq 1,0,1 --num-se 6 --seed 5378

# s9234 with a different key
python harpoon.py --in s9234.bench --out s9234_harp.bench   --obf-seq 0,1,1,0,1,0 --auth-seq 1,0,0,1 --num-se 8 --seed 9234

# s1238 smaller configuration
python harpoon.py --in s1238.bench --out s1238_harp.bench   --obf-seq 1,0,0,1 --auth-seq 1,1 --num-se 5 --seed 1238
```

