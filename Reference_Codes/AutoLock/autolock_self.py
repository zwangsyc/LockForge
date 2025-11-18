
from __future__ import annotations
import argparse
import json
import logging
import os
import random
from pathlib import Path
from typing import Optional

# ============ project imports (must exist in your repo) ============
from ec.impl.kgs_ops.kgss_population_generator import KGSSPopulationGenerator
from ec.impl.kgs_ops.kgss_two_point_crossover import KGSSTwoPointCrossover
from ec.impl.kgs_ops.mux_node_mutation import MuxNodeMutation
from ec.impl.kgs_ops.muxlink_base import MuxLinkBase
from ec.impl.kgs_ops.muxlink_termination_op import MuxLinkTerminationOperator
from ec.model.operator_box import OperatorBox
from ec.impl.algorithms.steady_state_ga import SteadyStateGA
from ec.impl.muxlink_fitness_function import MuxLinkFitnessFunction
from ec.impl.selection_ops.tournament_selection import TournamentSelection
from ec.impl.replacement_operators.replace_worst_operator import ReplaceWorstOperator
from muxlink.muxlink import MuxLink
from utils.bench_parser import BenchParser
from ec.impl.kgs_solution import KGSSolution

# ======================== helpers ========================
DEF_BENCH = "../data/c1355.bench"


def _resolve(p: str | Path) -> Path:
    path = Path(p).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Benchmark not found: {path}")
    return path


def _ensure_out_dir() -> Path:
    out = Path("./out").resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


# ===================== core steps =====================

def test_encode(bench_path: str | Path = DEF_BENCH, key_size: int = 64, alg_type: str = "D-MUX",
                seed: int = 7) -> KGSSolution:
    """Lock benchmark with MuxLink and return encoded KGSSolution.

    Writes the locked netlist to ./out/locked_from_encode.bench for reference.
    """
    random.seed(seed)
    bench_path = _resolve(bench_path)

    netlist = BenchParser.instance().parse_file(str(bench_path))
    netlist_str = netlist.to_string()

    # Perform locking through base (deterministic for given seed)
    locked_bench_str = MuxLinkBase.instance().lock(netlist_str, key_size, alg_type)

    # Save for debugging
    out = _ensure_out_dir()
    (out / "locked_from_encode.bench").write_text(locked_bench_str)

    # Encode to KGSS representation
    muxlink = MuxLink()
    kgss = muxlink.encode(locked_bench_str)
    logging.info("Encoded KGSS with %d entries", len(kgss.data))
    return kgss


def example_steady_state_ga_for_muxlink(
    bench_path: str | Path = DEF_BENCH,
    key_size: int = 64,
    alg_type: str = "D-MUX",
    population_size: int = 30,
    max_iteration: int = 50,
    tournament_size: int = 5,
    node_mutation_prob: float = 0.05,
    fitness_epochs: int = 10,
    seed: int = 7,
) -> KGSSolution:
    """Run steady‑state GA specialized for MuxLink and return best KGSSolution."""
    random.seed(seed)
    bench_path = _resolve(bench_path)

    # Prepare netlist as string
    netlist = BenchParser.instance().parse_file(str(bench_path))
    netlist_str = netlist.to_string()

    # Operator box tailored to KGS/MuxLink
    operator_box = OperatorBox(
        KGSSPopulationGenerator(population_size, key_size, alg_type, netlist_str),
        TournamentSelection(tournament_size=tournament_size),
        KGSSTwoPointCrossover(netlist_str),
        MuxNodeMutation(netlist_str, node_mutation_probability=node_mutation_prob),
        ReplaceWorstOperator(),
        MuxLinkTerminationOperator(),
    )

    # Fitness function uses the MuxLink attack training internally
    fitness_function = MuxLinkFitnessFunction(str(bench_path), epochs=fitness_epochs)

    evo_alg = SteadyStateGA(operator_box, max_iteration, fitness_function)

    population, children_list = evo_alg.execute()
    logging.info("GA produced %d child pairs across %d iterations", len(children_list)//2, max_iteration)

    best = population.get_best()
    logging.info("Best KGSS size: %d", len(best.data))

    # Optional: persist best KGSS JSON for reuse
    out = _ensure_out_dir()
    (out / "best_kgss.json").write_text(json.dumps(best.get_data()))

    return best


def test_decode(kgss: KGSSolution, bench_path: str | Path = DEF_BENCH,
                attack_epochs: int = 10) -> str:
    """Decode a KGSS back to a locked .bench string using the original netlist.

    Also runs attack metrics (Accuracy/Precision/KPA) and logs them.
    Returns the locked .bench string and writes it to ./out/locked.bench.
    """
    bench_path = _resolve(bench_path)

    netlist = BenchParser.instance().parse_file(str(bench_path))
    netlist_str = netlist.to_string()

    muxlink = MuxLink()
    muxlink.train(netlist_str, epochs=attack_epochs)

    locked_bench_str = muxlink.decode(netlist_str, kgss)

    acc, prec, kpa = muxlink.attack(locked_bench_str)
    logging.info("Attack metrics — Acc: %.4f  Prec: %.4f  KPA: %.4f", acc, prec, kpa)

    out = _ensure_out_dir()
    (out / "locked.bench").write_text(locked_bench_str)
    return locked_bench_str


# ===================== CLI / main =====================

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run MuxLink GA pipeline")
    p.add_argument("--bench", default=DEF_BENCH, help="Path to .bench file")
    p.add_argument("--alg", default="D-MUX", choices=["D-MUX", "eD-MUX"], help="Locking algorithm type")
    p.add_argument("--key-size", type=int, default=64)

    p.add_argument("--pop", type=int, default=30, help="GA population size")
    p.add_argument("--iters", type=int, default=50, help="GA max iterations")
    p.add_argument("--tournament", type=int, default=5)
    p.add_argument("--mut-prob", type=float, default=0.05, help="Node mutation probability")
    p.add_argument("--epochs", type=int, default=10, help="Fitness/attack epochs")

    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--only", choices=["all", "encode", "ga", "decode"], default="all",
                   help="Which stage(s) to run")
    p.add_argument("--kgss-json", type=str, default="", help="If provided with --only decode, read KGSS from JSON")
    p.add_argument("--write-kgss", action="store_true", help="Write intermediate KGSS to ./out/kgss.json")
    p.add_argument("--log", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]) 
    return p


def _load_kgss_from_json(path: str | Path) -> KGSSolution:
    data = json.loads(Path(path).read_text())
    kg = KGSSolution()
    for idx, entry in enumerate(data):
        # Each entry is expected as [f1, f2, g1, g2, key, order]
        kg.append_entry(entry, idx)
    return kg


def main():
    args = _build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log), format="[%(levelname)s] %(message)s")

    bench = args.bench
    alg = args.alg
    key_size = args.key_size

    kgss: Optional[KGSSolution] = None

    if args.only in ("all", "encode"):
        logging.info("Step 1/3: Encoding…")
        kgss = test_encode(bench, key_size, alg, seed=args.seed)
        if args.write_kgss:
            (_ensure_out_dir() / "kgss.json").write_text(json.dumps(kgss.get_data()))

    if args.only in ("all", "ga"):
        logging.info("Step 2/3: Running GA…")
        best_kgss = example_steady_state_ga_for_muxlink(
            bench, key_size, alg,
            population_size=args.pop,
            max_iteration=args.iters,
            tournament_size=args.tournament,
            node_mutation_prob=args.mut_prob,
            fitness_epochs=args.epochs,
            seed=args.seed,
        )
        kgss = best_kgss

    if args.only in ("all", "decode"):
        logging.info("Step 3/3: Decoding and attacking…")
        if kgss is None:
            if not args.kgss_json:
                raise ValueError("No KGSS available. Provide --kgss-json with --only decode, or run encode/ga first.")
            kgss = _load_kgss_from_json(args.kgss_json)
        test_decode(kgss, bench_path=bench, attack_epochs=args.epochs)


if __name__ == "__main__":
    main()
