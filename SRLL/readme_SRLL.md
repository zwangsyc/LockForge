# SRLL.py — Secure Logic Locking Tool

`SRLL.py` locks combinational `.bench` circuits using a layered SRLL pipeline:
- LUT-based withholding with truth‑table key bits
- Entanglement via key‑controlled MUXes
- Eq.(5)-style Alternative Blocks (AntiSAT-like) with a no‑corruption trigger for the correct key
- Optional scattered XOR locks and structure-only obfuscation

> This README matches the CLI you showed (no `--ab-*` flags). Any AntiSAT tap/window sizing is fixed internally in this build.

---

## Requirements
- Python 3.8+
- `.bench` netlists with canonical gates: AND, OR, NAND, NOR, XOR, XNOR, NOT/INV, BUF
- If `DFF` appears, its outputs are treated as pseudo PIs

---

## Usage

### Command
```bash
python SRLL.py <input.bench> <output_locked.bench>   --blocks <int> --ent <int> --alt <int> --lock <int> --obf <int> --seed <int>
```

### Arguments
- `input` (positional): path to input `.bench`
- `output` (positional): path to write locked `.bench`
- `--blocks` (int, default 1): number of withheld LUT blocks
- `--ent` (int, default 1): entangled LUT inputs per block
- `--alt` (int, default 1): POs protected with Eq.(5) Alternative Blocks
- `--lock` (int, default 0): scattered XOR key locks
- `--obf` (int, default 0): double‑NOT obfuscation inserts
- `--seed` (int, default 1337): RNG seed for deterministic choices

### Example
```bash
python SRLL.py ./bench/c432.bench ./bench/c432_locked_srll.bench   --blocks 6 --ent 1 --alt 2 --lock 0 --obf 0 --seed 1337
```

On completion the program prints the **correct key** as a single CSV line:
```
KEY_TT0_0=0,KEY_TT0_1=1,KEY_ENT0_0=0,KEY_ABF_0=1,KEY_ABG_0=1,KEY_LCK_0=0, ...
```

Save that line for simulation.

---

## Verifying correctness

Use your simulator to compare original vs. locked with the printed key.

```bash
python simulate_bench.py ./bench/c432.bench ./bench/c432_locked_srll.bench   --key "KEY_TT0_0=0,KEY_TT0_1=1,KEY_ENT0_0=0,KEY_ABF_0=1,KEY_ABG_0=1" --samples 20000
```

Expected: **Matches(correct)=Total**, **Matches(wrong)** small (point‑function flips).

---

## Outputs
- Locked netlist: the `output` path you provided
- Key (stdout): CSV of `KEY=bit` pairs (TT, ENT, AB, optional LCK)

