# LockForge Artifact Check: 10-Scheme Before/After Summary

## Scope

This report summarizes artifact-level checks for the 10 LockForge-generated logic-locking schemes. It separates:

1. **Before:** issues found in the originally generated artifacts.
2. **After:** status after patching selected generators and rerunning structural smoke checks.

The checks combine Python structural extraction, generated JSON/report artifacts, and Lean certificates for local Boolean obligations. These checks characterize the generated artifacts and patched generators. They do **not** prove or disprove the original published logic-locking algorithms.

## Important caveat

The post-fix checks confirm that the specific reported structural issues were removed on the available test inputs. Full regression on clean original benchmarks is still required before claiming complete repair.

## Coverage Matrix

| Scheme | Before: original artifact finding | After: patched/rechecked status | Fixed status |
|---|---|---|---|
| CAS-Lock | Partial only: key table checked; key length matched `KEYA || KEYB = 2N`. Locked netlists were not available. | Not rechecked; locked netlists still needed. | Undetermined beyond key-file format. |
| SARO | Acyclic and key-live, but the same structurally recoverable key-polarity pattern appeared across all checked artifacts. | Not patched/rechecked. | Issue remains. |
| SRLL | Acyclic/key-live, but used simple `KEY_ALT` output muxes instead of Eq.(5)-style `KEY_ABF/KEY_ABG` alternative blocks; shipped keys bypassed important paths. | Patched `SRLL.py` rechecked: no cycles, no undefined outputs/args, `KEY_ABF/KEY_ABG` present, `KEY_ALT` absent, all 53 keys live. | Fixed for reported structural issue under smoke test. |
| TriLock | Acyclic, but several emitted artifacts had undefined `POLOCK_*` outputs; local output form was `POLOCK_y = y XOR ESF_FLAG` where defined. | Patched `TriLock.py` rechecked: no cycles, no undefined outputs/args, all keys live, `POLOCK_XOR_ESF` covers all outputs, reencoding no longer fails on tested cases. | Fixed for reported structural/emission issue under smoke test. |
| DK-Lock | Activation key was structurally recoverable and fixed across checked artifacts: `1010001000`; one artifact had undefined outputs. | Patched `DK_Lock.py` rechecked: no cycles, no undefined outputs/args, all keys live, activation key varied across tested inputs and direct literal AND-chain issue was removed. | Fixed for reported fixed-key/recoverability issue under smoke test. |
| DECOR | Acyclic, but emitted explicit golden/locked copies and readable `ISCORR` membership logic through `EQ_KEY/ISCORR` cones. | Not patched/rechecked. | Issue remains. |
| Entangle | Acyclic, but every output reduced to `source_output_i XOR common_CTRL`, with one global control shared across all outputs. | Not patched/rechecked. | Issue remains. |
| HARPOON | Output corruption was structurally regular, but OBF/AUTH sequence was readable and sequential encoding was ambiguous/nonstandard. An earlier attempt also had undefined temporary nets. | Patched `Harpoon.py` rechecked: no cycles, no undefined outputs/args, standard `Q = DFF(D)` emitted, output correction covers all outputs, `KEY` and `CORR_G` are live. | Fixed for reported structural/sequential-emission issue under smoke test. |
| SFLL-HD | Acyclic/key-live, but emitted HD-popcount logic was structurally flawed; embedded key recoverable from polarity structure. | Not patched/rechecked. | Issue remains. |
| AutoLock | Uploaded subset was acyclic/key-live, but D-MUX reciprocal pairing was sparse. | Not patched/rechecked. | Issue remains; subset only. |

---

## Per-Scheme Details

### 1. CAS-Lock

**Before errors / limitations**

- Only the key table was available.
- Lean key-length certificate passed: each `KEYA || KEYB` entry has length `2N`.
- No locked `.bench` files were available for structural checking.

**After**

- No patch/recheck performed.
- Full CAS-Lock check still requires locked netlists.

**Current status:** Partial only.

---

### 2. SARO

**Before errors / findings**

- Checked 9 locked netlists.
- All checked netlists were acyclic.
- All exposed 32 key inputs.
- All 32 key inputs structurally reached outputs.
- Same structurally recoverable key-polarity pattern across all checked artifacts:

```text
11010000110100001101000100000000
```

**After**

- No patch/recheck performed.

**Current status:** Structurally valid/key-live, but key-polarity recoverability and fixed pattern remain.

---

### 3. SRLL

**Before errors / findings**

- Checked 7 locked netlists.
- All checked netlists were acyclic.
- No undefined outputs or undefined gate arguments were found.
- All key inputs structurally reached outputs.
- However, the emitted artifacts did not contain the expected Eq.(5)-style `KEY_ABF/KEY_ABG` alternative-block structures.
- The artifacts instead used simple `KEY_ALT` output muxing.
- Available key files set every `KEY_ENT` and `KEY_ALT` bit to `0`, bypassing entanglement/alternative-select behavior.

**After patched `SRLL.py` smoke check**

```text
comb_cycles=0
undefined_outputs=0
undefined_gate_args=0
key_inputs=53
live_keys=53/53
KEY_ABF present=true
KEY_ABG present=true
KEY_ALT present=false
```

**Current status:** Fixed for the reported alternative-block/dead-key structural issue under smoke testing.

---

### 4. TriLock

**Before errors / findings**

- Checked 8 keyed TriLock netlists.
- All checked netlists were acyclic.
- Several emitted artifacts had undefined `POLOCK_*` outputs:

```text
s1196   : undefined_outputs=0/14
s1488   : undefined_outputs=0/19
s5378   : undefined_outputs=39/49
s13207  : undefined_outputs=144/152
s15850  : undefined_outputs=149/150
s35932  : undefined_outputs=32/320
s38417  : undefined_outputs=49/106
s38584  : undefined_outputs=0/304
```

- Where defined, outputs followed:

```text
POLOCK_y = y XOR ESF_FLAG
```

**After patched `TriLock.py` smoke check**

```text
comb_cycles=0
undefined_outputs=0
undefined_gate_args=0
all keys live=true
POLOCK_XOR_ESF covers all outputs=true
ES/EF/ESF present=true
reencoding no longer fails on tested cases
```

**Current status:** Fixed for the reported undefined-output/reencoding structural issue under smoke testing. Full temporal ES/EF verification still requires sequential unrolling.

---

### 5. DK-Lock

**Before errors / findings**

- Checked 6 locked netlists and key logs.
- Activation key was structurally recoverable from the netlist comparator.
- Same activation key appeared across all uploaded artifacts:

```text
1010001000
```

- Functional keys varied, so the fixed value was specifically the activation key.
- One artifact had undefined outputs:

```text
s38417_DK_Locked.bench: undefined_outputs=45/106
```

**After patched `DK_Lock.py` smoke check**

```text
comb_cycles=0
undefined_outputs=0
undefined_gate_args=0
KEY0..KEY9 live=10/10
activation key varied across tested inputs
stand-in activation keys observed:
  s1488 : 0001111100
  c3540 : 1110010011
```

**Current status:** Fixed for the reported fixed activation-key and direct literal-comparator issue under smoke testing. Full-suite regression is still needed.

---

### 6. DECOR

**Before errors / findings**

- Checked 8 DECOR netlists.
- All checked netlists were acyclic.
- Every output matched:

```text
out = L XOR (ISCORR AND (L XOR G))
```

- The artifacts explicitly contained golden/locked copies.
- `EQ_KEY/ISCORR` membership logic was readable, exposing promoted-key structure.

**After**

- No patch/recheck performed.

**Current status:** Not a combinational validity failure, but a fidelity/security issue remains.

---

### 7. Entangle

**Before errors / findings**

- Checked 5 locked netlists.
- All checked netlists were acyclic.
- Every output reduced to:

```text
locked_output_i = source_output_i XOR common_CTRL
```

- A single global control was shared across all outputs.

**After**

- No patch/recheck performed.

**Current status:** Structurally valid, but simplified into global perturb/restore control rather than distributed Entangle-style signal entanglement.

---

### 8. HARPOON

**Before errors / findings**

- Checked 6 HARPOON netlists.
- `KEY` reached outputs in all artifacts.
- Outputs reduced to:

```text
OUT = OUT_ORIG XOR CORR_G
```

- OBF/AUTH sequences were structurally recoverable from `EQ_OBF/EQ_AUTH` polarity gates.
- Sequential encoding was ambiguous/nonstandard: inserted state was emitted as bare `DFF(Q)` declarations rather than explicit `Q = DFF(D)` next-state wiring.
- An earlier patched attempt still had undefined temporary XOR nets.

**After patched `Harpoon.py` smoke check**

```text
comb_cycles=0
undefined_outputs=0
undefined_gate_args=0
bare_dff=0
standard Q = DFF(D) form emitted=true
output_xor_corrg covers all outputs=true
KEY live to outputs=true
CORR_G live to outputs=true
```

**Current status:** Fixed for the reported structural/sequential-emission issue under smoke testing. Full HARPOON temporal protocol verification still requires sequential unrolling.

---

### 9. SFLL-HD

**Before errors / findings**

- Checked 5 locked netlists.
- All checked netlists were acyclic.
- No undefined outputs were found.
- All 32 key inputs structurally reached outputs.
- Every output followed:

```text
OUT = XOR(XOR(source, P_eq), R_eq)
```

- The emitted Hamming-distance comparator/popcount was structurally flawed: the accumulator duplicated the first mismatch bit across accumulator positions.
- The embedded secret key was recoverable from `SFLL_PBUF/SFLL_PNOT` polarity.

**After**

- No patch/recheck performed.

**Current status:** Code-generation bug remains in the original generated artifact.

---

### 10. AutoLock

**Before errors / findings**

- Checked 4 uploaded AutoLock locked netlists.
- All uploaded checked netlists were acyclic.
- No undefined outputs were found.
- All 64 key inputs structurally reached outputs.
- D-MUX reciprocal pairing was sparse:

```text
c2670: paired=9,  unpaired=55
c5315: paired=6,  unpaired=58
c6288: paired=8,  unpaired=56
c7552: paired=7,  unpaired=57
```

**After**

- No patch/recheck performed.

**Current status:** Fidelity issue remains for the uploaded subset. Missing `c1355`, `c1908`, and `c3540` for full parity with earlier AutoLock coverage.

---

## Lean Certificate Status

Lean certificates were generated for the artifact-level/local Boolean obligations. Passing Lean means the encoded proof certificate was accepted; it does **not** mean full algorithmic fidelity was proven.

| Scheme | Lean status | Certificate type |
|---|---|---|
| CAS-Lock | Passed | Key-length format only |
| SARO | Passed | Encoded structural facts/key-polarity pattern |
| SRLL | Passed | Encoded structural facts/key-liveness |
| TriLock | Passed | Local output flip/preserve obligation |
| DK-Lock | Passed | Exact activation-key obligation for extracted comparator |
| DECOR | Passed | `ISCORR` output-correction identity |
| Entangle | Passed | Global control/dummy-cancellation identities |
| HARPOON | Passed | Local output correction; post-fix structural certificate also passed |
| SFLL-HD | Passed | Output correction/extracted structural facts |
| AutoLock | Passed | Encoded structural facts/pairing counts |

## Overall Conclusion

Across the original LockForge-generated artifacts, many designs were executable or structurally valid but still failed scheme-specific fidelity/security checks. The recurring issues were:

- fixed or structurally recoverable keys;
- simplified global correction structures;
- missing scheme-specific structures;
- undefined emitted outputs;
- sparse D-MUX reciprocal pairing;
- flawed Hamming-distance/popcount construction;
- ambiguous sequential encoding.

After patching selected generators, the reported structural issues for **SRLL**, **TriLock**, **DK-Lock**, and **HARPOON** were cleared under the current smoke tests. The patched files can be uploaded under the original generator names in the repository.

Recommended wording for the repository:

```text
This report documents artifact-level structural checks before and after selected generator fixes. The original generated artifacts exposed several reproducible fidelity issues. The patched generators for SRLL, TriLock, DK-Lock, and HARPOON clear the reported structural issues under smoke testing, but full benchmark-suite regression and temporal verification remain future work.
```
