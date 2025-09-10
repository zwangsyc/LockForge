# AutoLock DMUX GA — CLI Quickstart

```
--in  --k  --pop  --gens  --seed  --out-prefix
```

## Usage
```bash
python autolock.py   --in c2670.bench   --k 64   --pop 200   --gens 100   --seed 13   --out-prefix c2670_autolock
```

## Arguments
- `--in` (required): Input `.bench` file (e.g., `c2670.bench`).
- `--k` (default: 64): Key length (number of key bits).
- `--pop` (default: 200): GA population size.
- `--gens` (default: 100): GA generations.
- `--seed` (default: 13): Random seed.
- `--out-prefix` (default: `<in_basename>_autolock`): Prefix for output files.

## Typical outputs
Given `--out-prefix P`, scripts of this style commonly produce files like:
- `P_locked.bench` — locked netlist
- `P_key.json` — key bits (and possibly `P_best.json`, `P_history.json` if the script emits them)

## Examples
```bash
python autolock.py --in c2670.bench --k 64 --pop 200 --gens 100 --seed 13 --out-prefix c2670_autolock
```
