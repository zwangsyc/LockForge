# DK-Lock — README

## Overview
`DK_Lock.py` locks a BENCH netlist with a dual-key scheme and validates the locked design against the original.

- **lock**: produce a locked `.bench` netlist
- **validate**: simulate original vs locked and report agreement for cycles `t ≥ m`

## Requirements
- Python 3.8+
- Circuit in `.bench` format

## Quick Start
```bash
# 1) Lock (prints the correct keys)
python3 DK_Lock.py lock --in s15850.bench --out s15850_DK_Locked.bench --keys 10 --m 9 --seed 7

# 2) Validate with the printed keys
python3 DK_Lock.py validate   --orig s15850.bench   --locked s15850_DK_Locked.bench   --cycles 500   --m 9   --act-key <10-bit-from-lock>   --func-key <10-bit-from-lock-or-padded>   --seed 1
```

## Commands

### lock
```
python3 DK_Lock.py lock --in <infile.bench> --out <outfile.bench> [--keys N] [--m M] [--seed S]
```
- `--in` (required): input BENCH file
- `--out` (required): output locked BENCH file
- `--keys` (default: 10): number of KEY pins and outputs to wrap (up to N)
- `--m` (default: 9): activation length (cycles)
- `--seed` (default: 7): seed for deterministic locking

### validate
```
python3 DK_Lock.py validate --orig <orig.bench> --locked <locked.bench>   --cycles C --m M --act-key <N bits> --func-key <N bits> [--seed S]
```
- `--orig` (required): original BENCH
- `--locked` (required): locked BENCH from `lock`
- `--cycles` (default: 300): simulation length
- `--m` (required): must match the `--m` used in `lock`
- `--act-key` (required): N-bit activation key (exact length = number of KEY pins)
- `--func-key` (required): N-bit functional key (use padded N-bit if shown by `lock`)
- `--seed` (default: 1): seed for random primary-input vectors

## Examples
```bash
# Defaults
python3 DK_Lock.py lock --in s298.bench --out s298_DK_Locked.bench

# Small design
python3 DK_Lock.py lock --in C17.bench --out C17_DK_Locked.bench --keys 2 --m 3 --seed 42

# Validate
python3 DK_Lock.py validate   --orig C17.bench   --locked C17_DK_Locked.bench   --cycles 50   --m 3   --act-key 10   --func-key 00   --seed 1
```
