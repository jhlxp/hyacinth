#!/usr/bin/env python3

import argparse
import csv
import os
import statistics
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt


PREFERRED_BASELINE_ORDER = [
    "ocs_eps_global_ksp",
    "pure_ocs_ksp",
    "eps_ecmp",
    "ocs_eps_large_small_10pct",
    "ocs_eps_large_small_20pct",
    "ocs_eps_large_small_30pct",
    "pure_ocs_ksp_greedy",
    "ocs_eps_preset_greedy_10pct",
    "ocs_eps_preset_greedy_20pct",
    "ocs_eps_preset_greedy_30pct",
    "ocs_eps_preset_dynamic_greedy",
    "pure_ocs_pruned",
    "ocs_eps_pruned",
    # legacy keys for backward compatibility
    "ocs_eps_large_small",
    "ocs_eps_preset_greedy",
]

ORDER_INDEX = {name: idx for idx, name in enumerate(PREFERRED_BASELINE_ORDER)}

ALGORITHM_ALIASES = {
    "ocs_eps_global_ksp": "ocs_eps_global_ksp",
    "pure_ocs_ksp": "pure_ocs_ksp",
    "eps_ecmp": "eps_ecmp",
    "ocs_eps_pruned": "ocs_eps_pruned",
    "ocs_eps_large_small_10pct": "ocs_eps_large_small-10%",
    "ocs_eps_large_small_20pct": "ocs_eps_large_small-20%",
    "ocs_eps_large_small_30pct": "ocs_eps_large_small-30%",
    "pure_ocs_ksp_greedy": "pure_ocs_ksp_greedy",
    "ocs_eps_preset_greedy_10pct": "ocs_eps_preset_greedy-10%",
    "ocs_eps_preset_greedy_20pct": "ocs_eps_preset_greedy-20%",
    "ocs_eps_preset_greedy_30pct": "ocs_eps_preset_greedy-30%",
    "ocs_eps_preset_dynamic_greedy": "ocs_eps_preset_dynamic_greedy",
    "pure_ocs_pruned": "pure_ocs_pruned",
    # legacy keys
    "ocs_eps_large_small": "ocs_eps_large_small",
    "ocs_eps_preset_greedy": "ocs_eps_preset_greedy",
}

ALGORITHM_COLORS = {
    "ocs_eps_global_ksp": "#4E79A7",
    "pure_ocs_ksp": "#F28E2B",
    "eps_ecmp": "#FFBE7D",
    "ocs_eps_pruned": "#FF9DA7",
    "ocs_eps_large_small_10pct": "#FF7B72",
    "ocs_eps_large_small_20pct": "#E15759",
    "ocs_eps_large_small_30pct": "#C92A2A",
    "pure_ocs_ksp_greedy": "#76B7B2",
    "ocs_eps_preset_greedy_10pct": "#6DA8FF",
    "ocs_eps_preset_greedy_20pct": "#59A14F",
    "ocs_eps_preset_greedy_30pct": "#1E4FB8",
    "ocs_eps_preset_dynamic_greedy": "#9C755F",
    "pure_ocs_pruned": "#B07AA1",
    # legacy keys
    "ocs_eps_large_small": "#E15759",
    "ocs_eps_preset_greedy": "#59A14F",
}


def scheduler_order_key(name: str) -> Tuple[int, str]:
    return (ORDER_INDEX.get(name, len(PREFERRED_BASELINE_ORDER)), name)


def load_curve_csv(path: str, selected: set) -> Dict[str, List[Tuple[float, float, int]]]:
    curves: Dict[str, List[Tuple[float, float, int]]] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            scheduler = str(row.get("scheduler", "")).strip()
            if not scheduler:
                continue
            if selected and scheduler not in selected:
                continue
            try:
                b = float(row.get("bytes", "0"))
                fct = float(row.get("fct_ms", "0"))
                cnt = int(float(row.get("num_flows_in_bin", "0")))
            except ValueError:
                continue
            curves.setdefault(scheduler, []).append((b, fct, cnt))
    for scheduler in list(curves.keys()):
        curves[scheduler] = sorted(curves[scheduler], key=lambda x: x[0])
        if not curves[scheduler]:
            del curves[scheduler]
    return curves


def compute_avg_relative_rows(
    curves: Dict[str, List[Tuple[float, float, int]]], baseline: str
) -> List[Dict[str, str]]:
    if baseline not in curves:
        raise RuntimeError(
            f"Baseline scheduler '{baseline}' not found in curve CSV. "
            f"Available: {', '.join(sorted(curves.keys(), key=scheduler_order_key))}"
        )

    base_curve = curves[baseline]
    if not base_curve:
        raise RuntimeError(f"Baseline scheduler '{baseline}' has empty curve.")

    rows: List[Dict[str, str]] = []
    for scheduler in sorted(curves.keys(), key=scheduler_order_key):
        pts = curves[scheduler]
        match_bins = min(len(pts), len(base_curve))
        ratios: List[float] = []
        for i in range(match_bins):
            base_fct = base_curve[i][1]
            cur_fct = pts[i][1]
            if base_fct <= 0.0:
                continue
            ratios.append(cur_fct / base_fct)

        if not ratios:
            continue

        avg_ratio = statistics.mean(ratios)
        rows.append(
            {
                "scheduler": scheduler,
                "avg_relative_fct_vs_dynamic": f"{avg_ratio:.3f}",
                "matched_bins": str(len(ratios)),
                "self_bins": str(len(pts)),
                "dynamic_bins": str(len(base_curve)),
            }
        )
    return rows


def write_rows_csv(rows: List[Dict[str, str]], out_csv: str) -> None:
    fieldnames = [
        "scheduler",
        "avg_relative_fct_vs_dynamic",
        "matched_bins",
        "self_bins",
        "dynamic_bins",
    ]
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def plot_bar(rows: List[Dict[str, str]], out_png: str, title: str) -> None:
    rows_sorted = sorted(rows, key=lambda r: scheduler_order_key(r["scheduler"]))

    schedulers = [r["scheduler"] for r in rows_sorted]
    values = [float(r["avg_relative_fct_vs_dynamic"]) for r in rows_sorted]
    colors = [ALGORITHM_COLORS.get(s, "#9C9C9C") for s in schedulers]
    labels = [ALGORITHM_ALIASES.get(s, s) for s in schedulers]

    fig, ax = plt.subplots(1, 1, figsize=(10, 4), constrained_layout=True)
    x = list(range(len(schedulers)))
    bars = ax.bar(x, values, color=colors, edgecolor="none")

    ax.axhline(1.0, linestyle="--", linewidth=1.2, color="#444444", alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="center")
    ax.set_ylabel("Avg Relative FCT (dynamic=1)")
    ax.set_title(title)
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    for rect, val in zip(bars, values):
        ax.text(
            rect.get_x() + rect.get_width() * 0.5,
            val,
            f"{val:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Plot avg relative FCT bar chart using fct_vs_bytes curve CSV. "
            "Relative baseline is ocs_eps_preset_dynamic_greedy (=1)."
        )
    )
    parser.add_argument("--curve_csv", required=True, help="Input curve CSV from plot_fct_vs_bytes.py.")
    parser.add_argument(
        "--baseline",
        default="ocs_eps_preset_dynamic_greedy",
        help="Baseline scheduler for normalization (default: ocs_eps_preset_dynamic_greedy).",
    )
    parser.add_argument("--schedulers", default="", help="Optional comma-separated scheduler subset.")
    parser.add_argument(
        "--title",
        default="Avg Relative FCT by Scheduler (dynamic=1)",
        help="Figure title.",
    )
    parser.add_argument("--out_png", required=True, help="Output PNG path.")
    parser.add_argument("--out_csv", default="", help="Optional output CSV path.")
    args = parser.parse_args()

    selected = {x.strip() for x in args.schedulers.split(",") if x.strip()}
    curves = load_curve_csv(args.curve_csv, selected=selected)
    if not curves:
        raise RuntimeError("No valid rows loaded from curve CSV.")

    rows = compute_avg_relative_rows(curves, baseline=args.baseline)
    if not rows:
        raise RuntimeError("No schedulers produced valid relative averages.")
    plot_bar(rows, args.out_png, args.title)
    if args.out_csv:
        write_rows_csv(rows, args.out_csv)

    print(f"[summary] baseline : {args.baseline}")
    print(f"[summary] schedulers: {', '.join([r['scheduler'] for r in rows])}")
    if args.out_csv:
        print(f"[summary] csv : {args.out_csv}")
    print(f"[summary] png : {args.out_png}")


if __name__ == "__main__":
    main()
