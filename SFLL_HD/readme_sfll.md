# SFLL‑HD Simulator & Locked Netlist Emitter — README

This tool simulates **SFLL‑HD** and can **emit a locked BENCH** netlist (strip–restore via `HD==h` with PO‑wide XORs).

---

## Quick Start

```bash
# Use all PIs as protected domain; h=2
python3 sfll_hd_lock.py C17.bench --h 2 --all

# 32‑bit key on a larger bench, wrong key via one flipped bit
python3 sfll_hd_lock.py c499.bench --h 4 --k 32 --seed 42 --flip-bit 0 --patterns 100000

# Emit a locked netlist
python3 sfll_hd_lock.py your.bench --h 6 --k 32 --secret-key-hex 0xDEADBEEF --emit-locked locked_your.bench

# Explicit PI list + explicit keys
python3 sfll_hd_lock.py foo.bench --h 0 --pi-list N1,N2,N3,N4 --secret-key 1010 --provided-key 1001
```

---

## Key CLI Flags

```
sfll_hd_lock.py BENCH --h H [--all | --k K | --pi-list N1,N2,...]
                      [--secret-key 0101... | --secret-key-hex 0x... | --seed S]
                      [--provided-key 0101... | --flip-bit i]
                      [--max-enum N] [--patterns M]
                      [--emit-locked PATH] [--key-prefix K]
```

- `--h` Hamming distance (0..k).  
- Domain: `--all` or `--k K` (first K PIs) or `--pi-list ...`.  
- Keys: `--secret-key`, `--secret-key-hex`, or randomized via `--seed`.  
- Provided key: `--provided-key` or `--flip-bit i`.  
- Enumeration vs sampling: if `#PIs ≤ --max-enum`, enumerate; else sample `--patterns`.  
- Netlist emission: `--emit-locked locked.bench` writes the SFLL‑HD locked BENCH.  
- `--key-prefix` sets key input names (default `K0..K{k-1}`).

---


Meaning:
- **File**: BENCH path.  
- **Inputs / Outputs**: discovered PIs/POs.  
- **Selected PIs (k=...)**: domain used for HD.  
- **h, secret_key, provided_key**: parameters and keys in effect.  
- **Vectors**: `enumerated` or `random-sampled` and count.  
- The next blocks print corruption metrics for the **correct** key, the **provided** key, and the **FSC** (strip‑only).

Typical metrics:
- `fraction_any_output_wrong` — fraction of inputs where any PO differs from GOLDEN.  
- `avg_output_hamming_per_vector` — average PO bit‑flips per input.  
- FSC removal (full enumeration): expected `C(k,h)/2^k`.

---

## Examples (32‑bit keys)

```bash
# 32-bit domain, reproducible run, wrong key by flipping bit 7
python3 sfll_hd_lock.py your.bench --h 4 --k 32 --seed 123 --flip-bit 7 --patterns 100000

# 32-bit explicit secret (hex), emit locked
python3 sfll_hd_lock.py your.bench --h 6 --k 32 --secret-key-hex 0xCAFEBABE --emit-locked locked_your.bench
```

