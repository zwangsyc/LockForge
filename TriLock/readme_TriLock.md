# TriLock — Usage & Parameters (Current CLI)

```
--bench --ks --kf --alpha --po-fraction --validate --wrong-keys --seed
--extra-count --reencode-pairs --out-bench --emit-keyed-bench
```

---

## Quick Start

```bash
python TriLock.py \
  --bench ./benches/s9234.bench \
  --extra-count 6 --reencode-pairs 6 \
  --ks 3 --kf 3 --alpha 0.30 --po-fraction 1.0 --seed 1 \
  --emit-keyed-bench ./locked/s9234_trilock_keyed.bench
```

- Produces a **keyed** locked BENCH with `KEY_*` inputs and active ES/EF/ESF logic.
- Uses M‑SCG re‑encoding to form Mixed SCCs.

To emit a structural, M‑SCG‑only lock (no key behavior in the netlist):

```bash
python TriLock.py \
  --bench ./benches/s15850.bench \
  --extra-count 6 --reencode-pairs 6 \
  --out-bench ./locked/s15850_trilock_locked.bench
```

---

## Command-Line Parameters

| Flag | Required | Type | Default | Description |
|---|---:|---|---:|---|
| `--bench` | **Yes** | path | — | Input BENCH file to lock |
| `--ks` | No | int | 3 | ES prefix length (history depth for SAT hardness) |
| `--kf` | No | int | 3 | EF suffix length (size of tunable error space) |
| `--alpha` | No | float [0,1] | 0.2 | Target corruptibility used to form EF threshold |
| `--po-fraction` | No | float (0–1] | 1.0 | Fraction of POs flipped when ESF=1 |
| `--validate` | No | int | 200 | Behavioral validation pattern count (sim overlay) |
| `--wrong-keys` | No | int | 4 | Number of wrong keys sampled in validation |
| `--seed` | No | int | 2025 | RNG seed for reproducibility |
| `--extra-count` | No | int | 3 | Number of extra DFFs inserted for M‑SCG |
| `--reencode-pairs` | No | int | 3 | Number of O/E register pairs re‑encoded |
| `--out-bench` | No | path | — | Write M‑SCG‑only locked BENCH (no key effects) |
| `--emit-keyed-bench` | No | path | — | Write keyed locked BENCH with `KEY_*` ports and ES/EF/ESF |

> Note: `--emit-key-map` is **not** in this build; drive key bits in the exact `INPUT(...)` order found in the emitted BENCH.

---

## Outputs

- `*_trilock_locked.bench` — M‑SCG only (functional behavior preserved; no `KEY_*` pins).
- `*_trilock_keyed.bench` — Keyed lock with `KEY_*` inputs and ES/EF/ESF hardware.

---

## Typical Workflows

### Keyed Lock
```bash
python TriLock.py \
  --bench ./benches/b14.bench \
  --extra-count 6 --reencode-pairs 6 \
  --ks 3 --kf 3 --alpha 0.30 --po-fraction 1.0 --seed 7 \
  --emit-keyed-bench ./locked/b14_trilock_keyed.bench
```


---

## Parameter Guidance

- **`ks`**: raises SAT resilience by extending the prefix window; increases state/history hardware.
- **`kf`**, **`alpha`**: tune wrong‑key error rate; larger values increase corruption.
- **`extra-count`**, **`reencode-pairs`**: strengthen mixing for removal resistance.
- **`po-fraction`**: flip a subset of POs if you want partial corruption.

---
