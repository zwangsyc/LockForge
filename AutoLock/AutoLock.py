#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file AutoLock pipeline:
  - Parse ISCAS-85 .bench
  - Enumerate D-MUX candidates
  - Run GA to pick sites (patched GA)
  - Insert MUX-key locks with contiguous KEYINPUT0..K-1
  - Emit locked bench and key artifacts; sanity-checks included.

Dependencies: networkx
    pip install networkx
"""

from __future__ import annotations
import argparse
import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import networkx as nx

# ---------------------------------------------------------------------
# Section 1: .bench helpers (from bench_utils.py)
# ---------------------------------------------------------------------

_GATE_RE = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9_]+)\s*\(\s*([A-Za-z0-9_,\s]+)\s*\)\s*$"
)
_IN_RE = re.compile(r"^\s*INPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$", re.IGNORECASE)
_OUT_RE = re.compile(r"^\s*OUTPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$", re.IGNORECASE)
_COMMENT_RE = re.compile(r"^\s*#")

def parse_bench(path: str) -> Tuple[List[str], List[str], Dict[str, Tuple[str, List[str]]]]:
    """Parse a .bench file."""
    inputs: List[str] = []
    outputs: List[str] = []
    gates: Dict[str, Tuple[str, List[str]]] = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or _COMMENT_RE.match(line):
                continue
            m = _IN_RE.match(line)
            if m:
                inputs.append(m.group(1))
                continue
            m = _OUT_RE.match(line)
            if m:
                outputs.append(m.group(1))
                continue
            m = _GATE_RE.match(line)
            if m:
                out = m.group(1)
                typ = m.group(2).upper()
                args = [t.strip() for t in m.group(3).split(",") if t.strip()]
                gates[out] = (typ, args)
                continue
            # silently ignore unknown lines
    return inputs, outputs, gates

def write_bench(path: str,
                inputs: List[str],
                outputs: List[str],
                gates: Dict[str, Tuple[str, List[str]]],
                keyvec: Optional[List[int]] = None):
    with open(path, "w") as f:
        if keyvec is not None:
            f.write("#key=" + "".join(str(int(b)) for b in keyvec) + "\n")
        for n in inputs:
            f.write(f"INPUT({n})\n")
        for n in outputs:
            f.write(f"OUTPUT({n})\n")
        for out, (typ, args) in gates.items():
            f.write(f"{out} = {typ}({', '.join(args)})\n")

def bench_to_graph(path: str) -> nx.Graph:
    """Structural undirected view: connect each gate's output net to its input nets."""
    _, _, gates = parse_bench(path)
    g = nx.Graph()
    for out, (_typ, args) in gates.items():
        for a in args:
            g.add_edge(out, a)
    return g

def enumerate_dmux_candidates(path: str, max_pairs: int = 50000) -> List[Tuple[str, str, str, str]]:
    """Enumerate legal D-MUX/MUX insertion sites as (fi, fj, gi, gj)."""
    _, _, gates = parse_bench(path)

    # Reverse index: input_net -> list of gate outputs that consume it
    uses: Dict[str, List[str]] = {}
    for out, (_typ, args) in gates.items():
        for a in args:
            uses.setdefault(a, []).append(out)

    cands: List[Tuple[str, str, str, str]] = []
    seen: Set[Tuple[str, str, str, str]] = set()

    inputs_list = list(uses.keys())
    for fi in inputs_list:
        for gi in uses.get(fi, []):
            for fj in inputs_list:
                if fj == fi:
                    continue
                for gj in uses.get(fj, []):
                    if len({fi, fj, gi, gj}) < 4:
                        continue
                    key = (fi, fj, gi, gj)
                    if key in seen:
                        continue
                    seen.add(key)
                    cands.append(key)
                    if len(cands) >= max_pairs:
                        return cands
    return cands

# ---------------------------------------------------------------------
# Section 2: DMUX/MUX locker (from bench_lock_dmux.py; adjusted to reuse parse_bench)
# ---------------------------------------------------------------------

def _unique(base: str, used: set) -> str:
    name = base
    i = 0
    while name in used:
        i += 1
        name = f"{base}_{i}"
    used.add(name)
    return name

def _replace_input(gates: Dict[str, Tuple[str, List[str]]],
                   gate_out: str, old_in: str, new_in: str) -> bool:
    if gate_out not in gates:
        return False
    typ, args = gates[gate_out]
    changed = False
    new_args = []
    for a in args:
        if a == old_in and not changed:
            new_args.append(new_in)
            changed = True
        else:
            new_args.append(a)
    if changed:
        gates[gate_out] = (typ, new_args)
    return changed

def _insert_mux_key_first(gates: Dict[str, Tuple[str, List[str]]],
                          used: set,
                          out_name_base: str,
                          key_name: str,
                          a: str, b: str,
                          expand_mux: bool) -> str:
    """Create node: <base>_from_mux = MUX(key, a, b) and return that net name."""
    target = out_name_base + "_from_mux"
    if target in used:
        target = _unique(target, used)
    else:
        used.add(target)

    if not expand_mux:
        gates[target] = ("MUX", [key_name, a, b])  # key first!
        return target

    # Expand semantics: out = (NOT key & a) OR (key & b)
    notk = _unique(f"{target}_notk", used); gates[notk] = ("NOT", [key_name])
    a_and = _unique(f"{target}_aand", used); gates[a_and] = ("AND", [a, notk])
    b_and = _unique(f"{target}_band", used); gates[b_and] = ("AND", [b, key_name])
    gates[target] = ("OR", [a_and, b_and])
    return target

def _gate_uses_input(gates: Dict[str, Tuple[str, List[str]]], out_net: str, in_name: str) -> bool:
    return (out_net in gates) and (in_name in gates[out_net][1])

def _enumerate_candidates_from_gates(gates: Dict[str, Tuple[str, List[str]]], limit: int = 200000
) -> List[Tuple[str, str, str, str]]:
    uses: Dict[str, List[str]] = {}
    for out, (_typ, args) in gates.items():
        for a in args:
            uses.setdefault(a, []).append(out)
    cands: List[Tuple[str, str, str, str]] = []
    seen = set()
    inputs_list = list(uses.keys())
    for fi in inputs_list:
        for gi in uses.get(fi, []):
            for fj in inputs_list:
                if fj == fi:
                    continue
                for gj in uses.get(fj, []):
                    if len({fi, fj, gi, gj}) < 4:
                        continue
                    key = (fi, fj, gi, gj)
                    if key in seen:
                        continue
                    seen.add(key)
                    cands.append(key)
                    if len(cands) >= limit:
                        return cands
    return cands

def lock_dmux(
    in_bench: str,
    out_bench: str,
    genes: List[Tuple[str, str, str, str, int]],  # (fi, fj, gi, gj, kbit)
    key_prefix: str = "KEYINPUT",                 # uppercase contiguous KEYINPUT0..N-1
    expand_mux: bool = False,
    enforce_keys: Optional[int] = None,           # ensure final #keys >= this value
) -> Dict[str, object]:
    inputs, outputs, gates = parse_bench(in_bench)
    used = set(inputs) | set(outputs) | set(gates.keys())
    for _, (_typ, args) in gates.items():
        used.update(args)

    keyvec: List[int] = []
    keynames_created: List[str] = []
    inserted_sites = 0
    used_pairs = set()  # (input_net, gate_out) already replaced

    # ---- main pass (two sides independently) ----
    for idx, (fi, fj, gi, gj, kbit) in enumerate(genes):
        left_ok  = _gate_uses_input(gates, gi, fi)
        right_ok = _gate_uses_input(gates, gj, fj)
        if not (left_ok and right_ok):
            if _gate_uses_input(gates, gi, fj) and _gate_uses_input(gates, gj, fi):
                fi, fj = fj, fi
                left_ok  = _gate_uses_input(gates, gi, fi)
                right_ok = _gate_uses_input(gates, gj, fj)
        if not left_ok and not right_ok:
            continue

        key = _unique(f"{key_prefix}{idx}", used)
        if key not in inputs:
            inputs.append(key)
        keyvec.append(int(kbit))
        keynames_created.append(key)

        # gi side: my_f1 = fi, my_f2 = fj ; gj side: my_f1 = fj, my_f2 = fi
        if left_ok and (fi, gi) not in used_pairs:
            f1, f2 = fi, fj
            mux_out = _insert_mux_key_first(
                gates, used, gi, key,
                (f2 if kbit else f1),
                (f1 if kbit else f2),
                expand_mux
            )
            if _replace_input(gates, gi, fi, mux_out):
                inserted_sites += 1
                used_pairs.add((fi, gi))

        if right_ok and (fj, gj) not in used_pairs:
            f1, f2 = fj, fi
            mux_out = _insert_mux_key_first(
                gates, used, gj, key,
                (f2 if kbit else f1),
                (f1 if kbit else f2),
                expand_mux
            )
            if _replace_input(gates, gj, fj, mux_out):
                inserted_sites += 1
                used_pairs.add((fj, gj))

    # ---- fallback fill to reach enforce_keys ----
    filled_keys = 0
    target_keys = enforce_keys if enforce_keys is not None else len(keyvec)
    if len(keyvec) < target_keys:
        cands = _enumerate_candidates_from_gates(gates, limit=200000)
        def site_available(fi: str, gi: str) -> bool:
            return _gate_uses_input(gates, gi, fi) and ((fi, gi) not in used_pairs)
        next_idx = len(genes)
        ci = 0
        while len(keyvec) < target_keys and ci < len(cands):
            fi, fj, gi, gj = cands[ci]
            ci += 1
            left_ok  = site_available(fi, gi)
            right_ok = site_available(fj, gj)
            if not left_ok and not right_ok:
                continue
            kbit = random.randint(0, 1)
            key = _unique(f"{key_prefix}{next_idx}", used)
            next_idx += 1
            if key not in inputs:
                inputs.append(key)
            keyvec.append(int(kbit))
            keynames_created.append(key)
            filled_keys += 1

            if left_ok:
                f1, f2 = fi, fj
                mux_out = _insert_mux_key_first(
                    gates, used, gi, key,
                    (f2 if kbit else f1),
                    (f1 if kbit else f2),
                    expand_mux
                )
                if _replace_input(gates, gi, fi, mux_out):
                    inserted_sites += 1
                    used_pairs.add((fi, gi))
            if right_ok:
                f1, f2 = fj, fi
                mux_out = _insert_mux_key_first(
                    gates, used, gj, key,
                    (f2 if kbit else f1),
                    (f1 if kbit else f2),
                    expand_mux
                )
                if _replace_input(gates, gj, fj, mux_out):
                    inserted_sites += 1
                    used_pairs.add((fj, gj))

    # ---- contiguous rename to KEYINPUT0..KEYINPUT{N-1} and rebuild inputs ----
    rename_map: Dict[str, str] = {old: f"{key_prefix}{i}" for i, old in enumerate(keynames_created)}
    for out, (typ, args) in list(gates.items()):
        gates[out] = (typ, [rename_map.get(x, x) for x in args])
    inputs = [rename_map.get(x, x) for x in inputs]

    # rebuild inputs: non-keys first (dedup), then exact contiguous keys
    key_pat = re.compile(rf"^{re.escape(key_prefix)}\d+$")
    non_key_inputs = [n for n in inputs if not key_pat.match(n)]
    contiguous_keys = [f"{key_prefix}{i}" for i in range(len(keyvec))]
    def _uniq(seq):
        seen = set()
        out = []
        for s in seq:
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out
    inputs = _uniq(non_key_inputs + contiguous_keys)

    write_bench(out_bench, inputs, outputs, gates, keyvec=keyvec)

    return {
        "inserted_mux_sites": inserted_sites,
        "num_keys": len(keyvec),
        "filled_keys": filled_keys,
        "renamed_keys": rename_map,
    }

# ---------------------------------------------------------------------
# Section 3: GA types & classes (patched version) + toy fitness
# ---------------------------------------------------------------------

Genotype = List[Tuple[str, str, str, str, int]]  # (fi, fj, gi, gj, kbit)

@dataclass
class AutoLockConfig:
    key_length: int = 8
    population_size: int = 30
    generations: int = 40
    tournament_k: int = 3
    cx_prob: float = 0.9
    mut_prob: float = 0.2
    elitism: int = 2
    random_seed: Optional[int] = 42
    mutate_flip_keybit_prob: float = 0.5
    per_gene_mut_prob: float = 0.2

class Netlist:
    def __init__(self, g: nx.Graph):
        self.g = g
    @staticmethod
    def from_edges(edges: List[Tuple[str, str]]) -> "Netlist":
        g = nx.Graph()
        g.add_edges_from(edges)
        return Netlist(g)
    def copy(self) -> "Netlist":
        return Netlist(nx.Graph(self.g))
    def nodes(self) -> List[str]:
        return list(self.g.nodes())
    def edges(self) -> List[Tuple[str, str]]:
        return list(self.g.edges())
    def candidate_localities(self, max_pairs: int = 2000) -> List[Tuple[str, str, str, str]]:
        cands: Set[Tuple[str, str, str, str]] = set()
        for fi in self.g.nodes():
            for gi in self.g.neighbors(fi):
                for fj in self.g.nodes():
                    if fj == fi:
                        continue
                    for gj in self.g.neighbors(fj):
                        if len({fi, fj, gi, gj}) < 4:
                            continue
                        deg_ok = abs(self.g.degree[gi] - self.g.degree[gj]) <= 2
                        if not deg_ok:
                            continue
                        key = (fi, fj, gi, gj) if (fi, gi, fj, gj) < (fj, gj, fi, gi) else (fj, gi, fi, gj)
                        cands.add(key)
                        if len(cands) >= max_pairs:
                            break
                    if len(cands) >= max_pairs:
                        break
            if len(cands) >= max_pairs:
                break
        return list(cands)

@dataclass
class AutoLockGA:
    netlist: Netlist
    attacker_fitness: Callable[[Netlist, Genotype], float]
    config: AutoLockConfig = field(default_factory=AutoLockConfig)
    candidates: List[Tuple[str, str, str, str]] = field(default_factory=list)

    def __post_init__(self):
        if self.config.random_seed is not None:
            random.seed(self.config.random_seed)
        if not self.candidates:
            self.candidates = self.netlist.candidate_localities()

    def _dedup_and_refill(self, geno: Genotype) -> Genotype:
        seen: Set[Tuple[str, str, str, str]] = set()
        new: Genotype = []
        for (fi, fj, gi, gj, k) in geno:
            key = (fi, fj, gi, gj)
            if key in seen:
                continue
            seen.add(key)
            new.append((fi, fj, gi, gj, k))
        available = [c for c in self.candidates if c not in seen]
        while len(new) < self.config.key_length and available:
            fi, fj, gi, gj = available.pop(random.randrange(len(available)))
            new.append((fi, fj, gi, gj, random.randint(0, 1)))
            seen.add((fi, fj, gi, gj))
        while len(new) < self.config.key_length and self.candidates:
            fi, fj, gi, gj = random.choice(self.candidates)
            if (fi, fj, gi, gj) in seen:
                continue
            new.append((fi, fj, gi, gj, random.randint(0, 1)))
            seen.add((fi, fj, gi, gj))
        return new[:self.config.key_length]

    def random_genotype(self) -> Genotype:
        assert len(self.candidates) >= self.config.key_length, (
            f"Not enough candidate localities ({len(self.candidates)}) for key_length={self.config.key_length}."
        )
        picks = random.sample(self.candidates, self.config.key_length)
        return [(fi, fj, gi, gj, random.randint(0, 1)) for (fi, fj, gi, gj) in picks]

    def tournament_select(self, pop: List[Genotype], fits: List[float]) -> Genotype:
        k = min(self.config.tournament_k, len(pop))
        idxs = random.sample(range(len(pop)), k)
        best = min(idxs, key=lambda i: fits[i])
        return [tuple(g) for g in pop[best]]  # deep copy of tuples

    def crossover(self, p1: Genotype, p2: Genotype) -> Tuple[Genotype, Genotype]:
        if random.random() > self.config.cx_prob:
            return list(p1), list(p2)
        c1, c2 = [], []
        for g1, g2 in zip(p1, p2):
            if random.random() < 0.5:
                c1.append(g1)
                c2.append(g2)
            else:
                c1.append(g2)
                c2.append(g1)
        return c1, c2

    def mutate(self, geno: Genotype) -> Genotype:
        if random.random() > self.config.mut_prob:
            return geno
        out: Genotype = []
        for (fi, fj, gi, gj, k) in geno:
            if random.random() < self.config.per_gene_mut_prob:
                if random.random() < self.config.mutate_flip_keybit_prob:
                    k = 1 - k
                else:
                    nfi, nfj, ngi, ngj = random.choice(self.candidates)
                    slot = random.choice([0, 1, 2, 3])
                    if   slot == 0: fi = nfi
                    elif slot == 1: fj = nfj
                    elif slot == 2: gi = ngi
                    else: gj = ngj
            if len({fi, fj, gi, gj}) < 4:
                fi, fj, gi, gj = random.choice(self.candidates)
                k = random.randint(0, 1)
            out.append((fi, fj, gi, gj, k))
        return out

    def evolve(self) -> Dict[str, Any]:
        pop: List[Genotype] = [self.random_genotype() for _ in range(self.config.population_size)]
        pop = [self._dedup_and_refill(g) for g in pop]
        fits: List[float] = [self.attacker_fitness(self.netlist, g) for g in pop]

        history = []
        for gen in range(self.config.generations):
            best_idx = min(range(len(pop)), key=lambda i: fits[i])
            worst_idx = max(range(len(pop)), key=lambda i: fits[i])
            history.append({
                "gen": gen,
                "best_fitness": fits[best_idx],
                "avg_fitness": sum(fits) / len(fits),
                "worst_fitness": fits[worst_idx],
            })

            elites = [list(pop[i]) for i in sorted(range(len(pop)), key=lambda i: fits[i])[:self.config.elitism]]

            offspring: List[Genotype] = []
            while len(offspring) < (self.config.population_size - self.config.elitism):
                p1 = self.tournament_select(pop, fits)
                p2 = self.tournament_select(pop, fits)
                c1, c2 = self.crossover(p1, p2)
                c1 = self.mutate(c1); c2 = self.mutate(c2)
                c1 = self._dedup_and_refill(c1); c2 = self._dedup_and_refill(c2)
                offspring.extend([c1, c2])
            offspring = offspring[: self.config.population_size - self.config.elitism]

            new_pop = elites + offspring
            new_fits = [self.attacker_fitness(self.netlist, g) for g in new_pop]
            pop, fits = new_pop, new_fits

        best_idx = min(range(len(pop)), key=lambda i: fits[i])
        return {"best_genotype": pop[best_idx], "best_fitness": fits[best_idx], "history": history}

# -- toy fitness from autolock_ga.py (simple structural proxy)
def toy_muxlink_attack(netlist: Netlist, genotype: Genotype) -> float:
    g = netlist.g
    acc_terms = []
    for (fi, fj, gi, gj, k) in genotype:
        if gi not in g or gj not in g:
            continue
        deg_diff = abs(g.degree[gi] - g.degree[gj])
        nei_i = set(g.neighbors(gi)); nei_j = set(g.neighbors(gj))
        nei_i.discard(fi); nei_i.discard(fj); nei_j.discard(fi); nei_j.discard(fj)
        inter = len(nei_i & nei_j); union = len(nei_i | nei_j) or 1
        jacc = inter / union
        deg_penalty = min(1.0, deg_diff / 5.0)
        term = 0.6 * deg_penalty + 0.4 * (1 - jacc)
        acc_terms.append(term)
    if not acc_terms:
        return 1.0
    return max(0.0, min(1.0, sum(acc_terms) / len(acc_terms)))

# ---------------------------------------------------------------------
# Section 4: End-to-end driver (from run_c1355_autolock.py; generalized)
# ---------------------------------------------------------------------

def run_pipeline(
    in_bench: Path,
    out_locked: Path,
    out_hist: Path,
    out_best: Path,
    out_keytxt: Path,
    out_keyjson: Path,
    key_len: int,
    pop: int,
    gens: int,
    seed: int,
) -> None:
    t0 = time.time()
    if not in_bench.exists():
        raise FileNotFoundError(f"Missing input bench: {in_bench.resolve()}")

    print("[1/5] Enumerating candidates ...")
    candidates = enumerate_dmux_candidates(str(in_bench), max_pairs=50000)
    print(f"    Candidates found: {len(candidates)}")

    print("[2/5] GA ...")
    g = bench_to_graph(str(in_bench))
    nl = Netlist(g)
    cfg = AutoLockConfig(key_length=key_len, population_size=pop, generations=gens, random_seed=seed)
    ga = AutoLockGA(nl, attacker_fitness=toy_muxlink_attack, config=cfg, candidates=candidates)
    res = ga.evolve()
    out_hist.write_text(json.dumps(res["history"], indent=2))
    out_best.write_text(json.dumps({"best_fitness": res["best_fitness"], "best_genotype": res["best_genotype"]}, indent=2))

    print("[3/5] Lock with enforce_keys and contiguous rename ...")
    best_genes = [tuple(g) for g in res["best_genotype"]]
    summary = lock_dmux(
        str(in_bench), str(out_locked), best_genes,
        key_prefix="KEYINPUT",
        expand_mux=False,
        enforce_keys=key_len
    )
    print(f"    Inserted pins: {summary['inserted_mux_sites']}, keys: {summary['num_keys']}, filled: {summary['filled_keys']}")
    print(f"    Renamed keys (old->new) count: {len(summary['renamed_keys'])}")

    print("[4/5] Verify #key= and names ...")
    lines = out_locked.read_text().splitlines()
    assert lines and lines[0].startswith("#key="), "Missing #key= line"
    key_str = lines[0][len('#key='):].strip()
    assert len(key_str) == key_len, f"Key length {len(key_str)} != {key_len}"
    inputs, outputs, _ = parse_bench(str(out_locked))
    expected = [f"KEYINPUT{i}" for i in range(key_len)]
    missing = [k for k in expected if k not in inputs]
    assert not missing, f"Missing contiguous keys: {missing}"

    out_keytxt.write_text(key_str + "\n")
    out_keyjson.write_text(json.dumps({"key": [int(c) for c in key_str]}, indent=2))

    print(f"[5/5] Done in {time.time()-t0:.2f}s. Locked -> {out_locked.resolve()}")

def main():
    p = argparse.ArgumentParser(description="Single-file AutoLock DMUX GA pipeline")
    p.add_argument("--in", dest="in_bench", required=True, help="Input .bench file (e.g., c2670.bench)")
    p.add_argument("--k", dest="key_len", type=int, default=64, help="Key length (default: 64)")
    p.add_argument("--pop", type=int, default=200, help="GA population size (default: 200)")
    p.add_argument("--gens", type=int, default=100, help="GA generations (default: 100)")
    p.add_argument("--seed", type=int, default=13, help="Random seed (default: 13)")
    p.add_argument("--out-prefix", default=None, help="Output prefix (default: <in_basename>_autolock)")
    args = p.parse_args()

    in_bench = Path(args.in_bench)
    prefix = args.out_prefix or (in_bench.stem + "_autolock")

    out_locked  = Path(f"{prefix}_locked.bench")
    out_hist    = Path(f"{prefix}_history.json")
    out_best    = Path(f"{prefix}_best.json")
    out_keytxt  = Path(f"{prefix}_key.txt")
    out_keyjson = Path(f"{prefix}_key.json")

    run_pipeline(
        in_bench=in_bench,
        out_locked=out_locked,
        out_hist=out_hist,
        out_best=out_best,
        out_keytxt=out_keytxt,
        out_keyjson=out_keyjson,
        key_len=args.key_len,
        pop=args.pop,
        gens=args.gens,
        seed=args.seed,
    )

if __name__ == "__main__":
    main()
