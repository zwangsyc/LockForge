#!/usr/bin/env python3
import argparse
import random
import re
import sys

IN_RE = re.compile(r'^\s*INPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
OUT_RE = re.compile(r'^\s*OUTPUT\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*$')
GATE_RE = re.compile(
    r'^\s*([A-Za-z0-9_]+)\s*=\s*([A-Z]+)\s*\(\s*([A-Za-z0-9_,\s]+)\s*\)\s*$'
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Insert CAS-Lock into a .bench netlist: input_bench output_bench total_keys"
    )
    p.add_argument("input_bench", help="Input .bench file")
    p.add_argument("output_bench", help="Output .bench file")
    p.add_argument(
        "total_keys",
        type=int,
        help="Total number of key bits (must be even)",
    )
    return p.parse_args()


def parse_bench(path):
    inputs = []
    outputs = []
    gates = []

    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue

                m = IN_RE.match(line)
                if m:
                    inputs.append(m.group(1))
                    continue

                m = OUT_RE.match(line)
                if m:
                    outputs.append(m.group(1))
                    continue

                m = GATE_RE.match(line)
                if m:
                    lhs, gtype, argstr = m.groups()
                    fanins = [a.strip() for a in argstr.split(",") if a.strip()]
                    gates.append((lhs, gtype, fanins))
                    continue

        return inputs, outputs, gates

    except OSError as e:
        sys.stderr.write(f"Error: cannot open bench file '{path}': {e}\n")
        sys.exit(1)


def main():
    args = parse_args()

    total_keys = args.total_keys
    if total_keys % 2 != 0:
        sys.stderr.write("Error: total_keys must be even.\n")
        sys.exit(1)

    N = total_keys // 2
    if N < 4:
        sys.stderr.write("Error: total_keys/2 must be >= 4.\n")
        sys.exit(1)

    inputs, outputs, gates = parse_bench(args.input_bench)

    if not outputs:
        sys.stderr.write("Error: benchmark has no OUTPUT.\n")
        sys.exit(1)

    inputs_set = set(inputs)
    outputs_set = set(outputs)

    candidates = [lhs for (lhs, _, _) in gates
                  if lhs not in inputs_set and lhs not in outputs_set]

    if len(candidates) < N:
        candidates = [lhs for (lhs, _, _) in gates]

    if len(candidates) < N:
        sys.stderr.write(
            f"Error: need at least {N} internal nodes, found {len(candidates)}.\n"
        )
        sys.exit(1)

    targets = candidates[:N]

    key_names = [f"KEYINPUT{i}" for i in range(total_keys)]

    locked_out = outputs[0]
    orig_out_name = locked_out + "_orig"

    existing_nets = set(inputs) | {lhs for (lhs, _, _) in gates}
    if orig_out_name in existing_nets:
        idx = 0
        base = orig_out_name
        while orig_out_name in existing_nets:
            orig_out_name = f"{base}_{idx}"
            idx += 1

    renamed_gates = []
    for lhs, gtype, fanins in gates:
        if lhs == locked_out:
            lhs = orig_out_name
        renamed_gates.append((lhs, gtype, fanins))

    key_bits = ""
    lock_gates = []

    for i in range(N):
        lhs = f"T{i + 1}"
        target = targets[i]
        key = key_names[i]

        if random.randint(0, 1) == 0:
            gtype = "XOR"
            key_bits += "0"
        else:
            gtype = "XNOR"
            key_bits += "1"

        lock_gates.append((lhs, gtype, [target, key]))

    lock_gates.append((f"T{N + 1}", "AND", ["T1", "T2"]))

    for i in range(N - 2):
        out_idx = N + 2 + i
        in1_idx = N + 1 + i
        in2_idx = i + 3
        gate_type = "OR" if i % 5 == 0 else "AND"
        lock_gates.append(
            (f"T{out_idx}", gate_type, [f"T{in1_idx}", f"T{in2_idx}"])
        )

    for i in range(N):
        lhs = f"W{i + 1}"
        target = targets[i]
        key = key_names[N + i]

        if random.randint(0, 1) == 0:
            gtype = "XOR"
            key_bits += "0"
        else:
            gtype = "XNOR"
            key_bits += "1"

        lock_gates.append((lhs, gtype, [target, key]))

    lock_gates.append((f"W{N + 1}", "AND", ["W1", "W2"]))

    for i in range(N - 3):
        out_idx = N + 2 + i
        in1_idx = N + 1 + i
        in2_idx = i + 3
        gate_type = "OR" if i % 5 == 0 else "AND"
        lock_gates.append(
            (f"W{out_idx}", gate_type, [f"W{in1_idx}", f"W{in2_idx}"])
        )

    last_idx = 2 * N - 1
    penultimate_idx = 2 * N - 2

    lock_gates.append(
        (f"W{last_idx}", "NAND", [f"W{penultimate_idx}", f"W{N}"])
    )
    lock_gates.append(
        ("T_out", "AND", [f"W{last_idx}", f"T{last_idx}"])
    )

    lock_gates.append(
        (locked_out, "XOR", [orig_out_name, "T_out"])
    )

    lines_out = []
    lines_out.append(f"# CAS-Lock applied, total_keys={total_keys}, locked_output={locked_out}")
    lines_out.append(f"# KEY = {key_bits}")
    lines_out.append("")

    for name in inputs:
        lines_out.append(f"INPUT({name})")

    for k in key_names:
        lines_out.append(f"INPUT({k})")

    lines_out.append("")

    for name in outputs:
        lines_out.append(f"OUTPUT({name})")

    lines_out.append("")

    for lhs, gtype, fanins in renamed_gates:
        lines_out.append(f"{lhs} = {gtype}({', '.join(fanins)})")

    for lhs, gtype, fanins in lock_gates:
        lines_out.append(f"{lhs} = {gtype}({', '.join(fanins)})")

    try:
        with open(args.output_bench, "w") as f:
            f.write("\n".join(lines_out) + "\n")
    except OSError as e:
        sys.stderr.write(
            f"Error: cannot write output bench file '{args.output_bench}': {e}\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
