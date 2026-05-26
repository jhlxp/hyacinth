#!/usr/bin/env python3

import argparse
import csv
import glob
import os
import re
from typing import Dict, List

import matplotlib.pyplot as plt
from matplotlib.patches import Patch


LINE_PATTERNS = {
    "scheduler": re.compile(r"^scheduler\s*=\s*(\S+)\s*$"),
    "topo_file": re.compile(r"^topo_file\s*=\s*(.+?)\s*$"),
    "traffic_in": re.compile(r"^traffic_in\s*=\s*(.+?)\s*$"),
    "traffic_out": re.compile(r"^traffic_out\s*=\s*(.+?)\s*$"),
    "solve_time_ms": re.compile(r"^solveTimeMs\s*=\s*([0-9eE+\-.]+)\s*$"),
    "num_solve_calls": re.compile(r"^numSolveCalls\s*=\s*(\d+)\s*$"),
}

PREFERRED_BASELINE_ORDER = [
    "ocs_eps_global_ksp",
    "pure_ocs_ksp",
    "eps_ecmp",
    "ocs_eps_large_small",
    "pure_ocs_ksp_greedy",
    "ocs_eps_preset_greedy",
    "ocs_eps_preset_dynamic_greedy",
    "pure_ocs_pruned",
    "ocs_eps_pruned",
]

ORDER_INDEX = {name: idx for idx, name in enumerate(PREFERRED_BASELINE_ORDER)}

ALGORITHM_ALIASES = {
    "ocs_eps_global_ksp": "ocs_eps_global_ksp",
    "pure_ocs_ksp": "pure_ocs_ksp",
    "eps_ecmp": "eps_ecmp",
    "ocs_eps_pruned": "ocs_eps_pruned",
    "ocs_eps_large_small": "ocs_eps_large_small",
    "pure_ocs_ksp_greedy": "pure_ocs_ksp_greedy",
    "ocs_eps_preset_greedy": "ocs_eps_preset_greedy",
    "ocs_eps_preset_dynamic_greedy": "ocs_eps_preset_dynamic_greedy",
    "pure_ocs_pruned": "pure_ocs_pruned",
}

ALGORITHM_COLORS = {
    "ocs_eps_global_ksp": "#4E79A7",
    "pure_ocs_ksp": "#F28E2B",
    "eps_ecmp": "#FFBE7D",
    "ocs_eps_pruned": "#FF9DA7",
    "ocs_eps_large_small": "#E15759",
    "pure_ocs_ksp_greedy": "#76B7B2",
    "ocs_eps_preset_greedy": "#59A14F",
    "ocs_eps_preset_dynamic_greedy": "#9C755F",
    "pure_ocs_pruned": "#B07AA1",
}


def scheduler_order_key(row: Dict[str, str]):
    name = row.get("scheduler", "")
    return (ORDER_INDEX.get(name, len(PREFERRED_BASELINE_ORDER)), name)


def parse_log(log_path: str) -> Dict[str, str]:
    row: Dict[str, str] = {
        "log_file": os.path.basename(log_path),
        "scheduler": "",
        "topo_file": "",
        "traffic_in": "",
        "traffic_out": "",
        "solve_time_ms": "",
        "num_solve_calls": "",
        "avg_solve_time_ms": "",
    }

    with open(log_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            for key, pattern in LINE_PATTERNS.items():
                m = pattern.match(line)
                if not m:
                    continue
                row[key] = m.group(1)

    if row.get("scheduler") == "strict_queue_greedy":
        row["scheduler"] = "ocs_eps_pruned"

    return row


def write_csv(rows: List[Dict[str, str]], out_csv: str) -> None:
    fieldnames = [
        "scheduler",
        "avg_solve_time_ms",
        "solve_time_ms",
        "num_solve_calls",
        "topo_file",
        "traffic_in",
        "traffic_out",
        "log_file",
    ]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_markdown(rows: List[Dict[str, str]], out_md: str) -> None:
    headers = [
        "scheduler",
        "avg_solve_time_ms",
        "solve_time_ms",
        "num_solve_calls",
        "topology",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.get("scheduler", ""),
                    row.get("avg_solve_time_ms", ""),
                    row.get("solve_time_ms", ""),
                    row.get("num_solve_calls", ""),
                    os.path.basename(row.get("topo_file", "")),
                ]
            )
            + " |"
        )

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def plot_summary(rows: List[Dict[str, str]], out_png: str) -> None:
    font_size = 20
    plot_rows = sorted(rows, key=scheduler_order_key)

    schedulers = [r["scheduler"] for r in plot_rows]
    x = list(range(len(schedulers)))
    colors = [ALGORITHM_COLORS.get(s, "#9C9C9C") for s in schedulers]
    solve_times = [float(r["avg_solve_time_ms"]) for r in plot_rows]

    fig, ax = plt.subplots(1, 1, figsize=(10, 4), constrained_layout=True)

    ax.bar(x, solve_times, color=colors)
    ax.set_ylabel("Avg Solve Time (ms)", fontsize=font_size)
    ax.set_xticks(x)
    ax.set_xticklabels([""] * len(x))
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", labelsize=font_size)

    legend_handles = [
        Patch(facecolor=ALGORITHM_COLORS.get(s, "#9C9C9C"), label=ALGORITHM_ALIASES.get(s, s))
        for s in schedulers
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 1.45),
        fontsize=font_size,
    )

    plt.savefig(out_png, dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot solve-time-only chart from injector logs.")
    parser.add_argument("--log_dir", type=str, required=True, help="Directory containing *.log files.")
    parser.add_argument("--out_csv", type=str, default="", help="Output CSV path (optional).")
    parser.add_argument("--out_md", type=str, default="", help="Output markdown table path (optional).")
    parser.add_argument("--out_png", type=str, required=True, help="Output PNG chart path.")
    args = parser.parse_args()

    log_paths = sorted(glob.glob(os.path.join(args.log_dir, "*.log")))
    if not log_paths:
        raise RuntimeError(f"No log files found under: {args.log_dir}")

    rows = [parse_log(p) for p in log_paths]
    rows = [r for r in rows if r.get("scheduler")]
    rows.sort(key=scheduler_order_key)

    for row in rows:
        if not row.get("solve_time_ms"):
            raise RuntimeError(f"Missing solveTimeMs in log: {row.get('log_file', '')}")
        total_solve = float(row["solve_time_ms"])
        num_calls = int(row.get("num_solve_calls") or "0")
        avg_solve = (total_solve / num_calls) if num_calls > 0 else total_solve
        row["avg_solve_time_ms"] = f"{avg_solve:.6f}"
        row["solve_time_ms"] = f"{total_solve:.6f}"
        row["num_solve_calls"] = str(num_calls)

    if args.out_csv:
        os.makedirs(os.path.dirname(args.out_csv), exist_ok=True)
        write_csv(rows, args.out_csv)
    if args.out_md:
        os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
        write_markdown(rows, args.out_md)

    os.makedirs(os.path.dirname(args.out_png), exist_ok=True)
    plot_summary(rows, args.out_png)

    if args.out_csv:
        print(f"[summary] csv : {args.out_csv}")
    if args.out_md:
        print(f"[summary] md  : {args.out_md}")
    print(f"[summary] png : {args.out_png}")


if __name__ == "__main__":
    main()
