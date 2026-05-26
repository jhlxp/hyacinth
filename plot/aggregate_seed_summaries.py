#!/usr/bin/env python3

import argparse
import csv
import os
import re
import statistics
from collections import defaultdict
from typing import DefaultDict, Dict, List, Tuple

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


def parse_case_base(case_tag: str) -> str:
    # Accept both "..._seed42" and "..._seed_42".
    m = re.match(r"^(.*)_seed_?\d+$", case_tag)
    if m:
        return m.group(1)
    return case_tag


def parse_seed_id(case_tag: str, seed_raw: str) -> str:
    seed = (seed_raw or "").strip()
    if seed:
        return seed
    m = re.search(r"_seed_?(\d+)$", case_tag)
    if m:
        return m.group(1)
    return "NA"


def fmt3(v: float) -> str:
    return f"{v:.3f}"


def seed_order_key(seed: str) -> Tuple[int, str]:
    try:
        return (int(seed), seed)
    except Exception:
        return (10**9, seed)


def scheduler_order_key(name: str) -> Tuple[int, str]:
    return (ORDER_INDEX.get(name, len(PREFERRED_BASELINE_ORDER)), name)


def safe_float(x: str):
    try:
        return float(x)
    except Exception:
        return None


def read_csv_dict(path: str) -> List[Dict[str, str]]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize_values(values: List[float]) -> Tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], 0.0)
    return (statistics.mean(values), statistics.pstdev(values))


def write_metric_csv(out_path: str, header: List[str], rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def plot_metric_bar(
    rows: List[Dict[str, str]],
    *,
    value_key: str,
    std_key: str,
    ylabel: str,
    title: str,
    out_png: str,
    relative: bool,
) -> None:
    rows = sorted(rows, key=lambda r: scheduler_order_key(r["scheduler"]))
    if not rows:
        return

    sched = [r["scheduler"] for r in rows]
    vals = [float(r[value_key]) for r in rows]
    stds = [float(r[std_key]) for r in rows]
    colors = [ALGORITHM_COLORS.get(s, "#9C9C9C") for s in sched]

    fig, ax = plt.subplots(1, 1, figsize=(10, 4), constrained_layout=True)
    x = list(range(len(sched)))

    bars = ax.bar(
        x,
        vals,
        yerr=stds,
        capsize=3,
        color=colors,
        edgecolor="none",
        ecolor="#444444",
        linewidth=0.8,
    )

    if relative:
        ax.axhline(1.0, linestyle="--", linewidth=1.2, color="#444444", alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(sched, rotation=20, ha="center")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    for rect, val in zip(bars, vals):
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


def plot_metric_box(
    values_by_scheduler: Dict[str, List[float]],
    *,
    ylabel: str,
    title: str,
    out_png: str,
    relative: bool,
) -> None:
    sched = [
        s
        for s in sorted(values_by_scheduler.keys(), key=scheduler_order_key)
        if values_by_scheduler.get(s)
    ]
    if not sched:
        return

    data = [values_by_scheduler[s] for s in sched]
    colors = [ALGORITHM_COLORS.get(s, "#9C9C9C") for s in sched]

    fig, ax = plt.subplots(1, 1, figsize=(10, 4), constrained_layout=True)
    bp = ax.boxplot(
        data,
        patch_artist=True,
        showmeans=True,
        meanline=False,
        showfliers=False,  # hide outlier circles
        widths=0.6,
    )

    for box, c in zip(bp["boxes"], colors):
        box.set_facecolor(c)
        box.set_alpha(0.55)
        box.set_edgecolor("#444444")
        box.set_linewidth(1.0)
    for med in bp["medians"]:
        med.set_color("#222222")
        med.set_linewidth(1.2)
    for mean in bp["means"]:
        mean.set_marker("D")
        mean.set_markerfacecolor("#111111")
        mean.set_markeredgecolor("#111111")
        mean.set_markersize(3.5)
    for line in bp["whiskers"] + bp["caps"]:
        line.set_color("#555555")
        line.set_linewidth(1.0)

    flat_vals = [v for arr in data for v in arr]
    y_min = min(flat_vals)
    y_max = max(flat_vals)
    y_span = max(y_max - y_min, 1e-9)
    y_off = 0.02 * y_span
    for i, vals in enumerate(data, start=1):
        if not vals:
            continue
        if len(vals) == 1:
            q3 = vals[0]
        else:
            q3 = statistics.quantiles(vals, n=4, method="inclusive")[2]
        mean_v = statistics.mean(vals)
        ax.text(
            i,
            q3 + y_off,
            f"{mean_v:.3f}",
            ha="center",
            va="bottom",
            fontsize=8,
            color="#111111",
        )

    if relative:
        ax.axhline(1.0, linestyle="--", linewidth=1.2, color="#444444", alpha=0.8)

    ax.set_xticks(list(range(1, len(sched) + 1)))
    ax.set_xticklabels(sched, rotation=20, ha="center")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate per-seed summaries into per-case averages")
    ap.add_argument("--batch_summary", required=True, help="batch_summary.csv generated by sweep script")
    ap.add_argument("--out_dir", required=True, help="batch output directory (scenario root)")
    args = ap.parse_args()

    batch_rows = read_csv_dict(args.batch_summary)
    if not batch_rows:
        raise RuntimeError(f"No rows in batch summary: {args.batch_summary}")

    solve_vals: DefaultDict[str, DefaultDict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    fct_rel_vals: DefaultDict[str, DefaultDict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    cct_rel_vals: DefaultDict[str, DefaultDict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    cct_p99_rel_vals: DefaultDict[str, DefaultDict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    cct_p95_rel_vals: DefaultDict[str, DefaultDict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    cct_avg_rel_vals: DefaultDict[str, DefaultDict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    solve_seed_rows_by_case: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)
    fct_seed_rows_by_case: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)
    cct_p100_seed_rows_by_case: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)
    cct_p99_seed_rows_by_case: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)
    cct_p95_seed_rows_by_case: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)
    cct_avg_seed_rows_by_case: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)

    case_success: Dict[str, int] = defaultdict(int)
    case_total: Dict[str, int] = defaultdict(int)
    case_dir_by_base: Dict[str, str] = {}

    for row in batch_rows:
        case_tag = (row.get("case_tag") or "").strip()
        seed_id = parse_seed_id(case_tag, (row.get("seed") or "").strip())
        status = (row.get("status") or "").strip().lower()
        run_dir = (row.get("run_dir") or "").strip()
        if not case_tag:
            continue

        case_base = parse_case_base(case_tag)
        case_total[case_base] += 1

        if run_dir:
            rd = os.path.normpath(run_dir)
            if os.path.basename(rd).startswith("seed_"):
                case_dir_by_base.setdefault(case_base, os.path.dirname(rd))
            else:
                case_dir_by_base.setdefault(case_base, os.path.join(args.out_dir, case_base))

        if status == "ok":
            case_success[case_base] += 1
        else:
            continue

        if not run_dir:
            continue

        summary_dir = os.path.join(run_dir, "summary")

        for r in read_csv_dict(os.path.join(summary_dir, "solve_time_summary.csv")):
            scheduler = (r.get("scheduler") or "").strip()
            v = safe_float((r.get("avg_solve_time_ms") or "").strip())
            if scheduler and v is not None:
                solve_vals[case_base][scheduler].append(v)
                solve_seed_rows_by_case[case_base].append(
                    {
                        "seed": seed_id,
                        "scheduler": scheduler,
                        "avg_solve_time_ms": fmt3(v),
                    }
                )

        for r in read_csv_dict(os.path.join(summary_dir, "fct_avg_relative_summary.csv")):
            scheduler = (r.get("scheduler") or "").strip()
            v = safe_float((r.get("avg_relative_fct_vs_dynamic") or "").strip())
            if scheduler and v is not None:
                fct_rel_vals[case_base][scheduler].append(v)
                fct_seed_rows_by_case[case_base].append(
                    {
                        "seed": seed_id,
                        "scheduler": scheduler,
                        "avg_relative_fct_vs_dynamic": fmt3(v),
                    }
                )

        # P100 file was renamed to coflow_p100_relative_summary.csv.
        # Keep a fallback for old runs that still used coflow_avg_relative_summary.csv.
        p100_csv = os.path.join(summary_dir, "coflow_p100_relative_summary.csv")
        if not os.path.isfile(p100_csv):
            p100_csv = os.path.join(summary_dir, "coflow_avg_relative_summary.csv")
        for r in read_csv_dict(p100_csv):
            scheduler = (r.get("scheduler") or "").strip()
            v = safe_float((r.get("avg_relative_cct_vs_dynamic") or "").strip())
            if scheduler and v is not None:
                cct_rel_vals[case_base][scheduler].append(v)
                cct_p100_seed_rows_by_case[case_base].append(
                    {
                        "seed": seed_id,
                        "scheduler": scheduler,
                        "avg_relative_cct_vs_dynamic": fmt3(v),
                    }
                )

        for r in read_csv_dict(os.path.join(summary_dir, "coflow_p99_relative_summary.csv")):
            scheduler = (r.get("scheduler") or "").strip()
            v = safe_float((r.get("avg_relative_cct_vs_dynamic") or "").strip())
            if scheduler and v is not None:
                cct_p99_rel_vals[case_base][scheduler].append(v)
                cct_p99_seed_rows_by_case[case_base].append(
                    {
                        "seed": seed_id,
                        "scheduler": scheduler,
                        "avg_relative_cct_vs_dynamic": fmt3(v),
                    }
                )

        for r in read_csv_dict(os.path.join(summary_dir, "coflow_p95_relative_summary.csv")):
            scheduler = (r.get("scheduler") or "").strip()
            v = safe_float((r.get("avg_relative_cct_vs_dynamic") or "").strip())
            if scheduler and v is not None:
                cct_p95_rel_vals[case_base][scheduler].append(v)
                cct_p95_seed_rows_by_case[case_base].append(
                    {
                        "seed": seed_id,
                        "scheduler": scheduler,
                        "avg_relative_cct_vs_dynamic": fmt3(v),
                    }
                )

        for r in read_csv_dict(os.path.join(summary_dir, "coflow_cct_avg_relative_summary.csv")):
            scheduler = (r.get("scheduler") or "").strip()
            v = safe_float((r.get("avg_relative_cct_vs_dynamic") or "").strip())
            if scheduler and v is not None:
                cct_avg_rel_vals[case_base][scheduler].append(v)
                cct_avg_seed_rows_by_case[case_base].append(
                    {
                        "seed": seed_id,
                        "scheduler": scheduler,
                        "avg_relative_cct_vs_dynamic": fmt3(v),
                    }
                )

    # Global summary across all cases in this scenario folder.
    global_dir = os.path.join(args.out_dir, "seed_avg_summary")
    os.makedirs(global_dir, exist_ok=True)

    coverage_rows = []
    for case_base in sorted(case_total.keys()):
        coverage_rows.append(
            {
                "case_base": case_base,
                "num_success_seeds": str(case_success.get(case_base, 0)),
                "num_total_seeds": str(case_total.get(case_base, 0)),
            }
        )
    write_metric_csv(
        os.path.join(global_dir, "seed_coverage.csv"),
        ["case_base", "num_success_seeds", "num_total_seeds"],
        coverage_rows,
    )

    solve_seed_rows_global: List[Dict[str, str]] = []
    fct_seed_rows_global: List[Dict[str, str]] = []
    cct_p100_seed_rows_global: List[Dict[str, str]] = []
    cct_p99_seed_rows_global: List[Dict[str, str]] = []
    cct_p95_seed_rows_global: List[Dict[str, str]] = []
    cct_avg_seed_rows_global: List[Dict[str, str]] = []

    for case_base in sorted(case_total.keys()):
        for r in solve_seed_rows_by_case.get(case_base, []):
            solve_seed_rows_global.append(
                {
                    "case_base": case_base,
                    "seed": r["seed"],
                    "scheduler": r["scheduler"],
                    "avg_solve_time_ms": r["avg_solve_time_ms"],
                }
            )
        for r in fct_seed_rows_by_case.get(case_base, []):
            fct_seed_rows_global.append(
                {
                    "case_base": case_base,
                    "seed": r["seed"],
                    "scheduler": r["scheduler"],
                    "avg_relative_fct_vs_dynamic": r["avg_relative_fct_vs_dynamic"],
                }
            )
        for r in cct_p100_seed_rows_by_case.get(case_base, []):
            cct_p100_seed_rows_global.append(
                {
                    "case_base": case_base,
                    "seed": r["seed"],
                    "scheduler": r["scheduler"],
                    "avg_relative_cct_vs_dynamic": r["avg_relative_cct_vs_dynamic"],
                }
            )
        for r in cct_p99_seed_rows_by_case.get(case_base, []):
            cct_p99_seed_rows_global.append(
                {
                    "case_base": case_base,
                    "seed": r["seed"],
                    "scheduler": r["scheduler"],
                    "avg_relative_cct_vs_dynamic": r["avg_relative_cct_vs_dynamic"],
                }
            )
        for r in cct_p95_seed_rows_by_case.get(case_base, []):
            cct_p95_seed_rows_global.append(
                {
                    "case_base": case_base,
                    "seed": r["seed"],
                    "scheduler": r["scheduler"],
                    "avg_relative_cct_vs_dynamic": r["avg_relative_cct_vs_dynamic"],
                }
            )
        for r in cct_avg_seed_rows_by_case.get(case_base, []):
            cct_avg_seed_rows_global.append(
                {
                    "case_base": case_base,
                    "seed": r["seed"],
                    "scheduler": r["scheduler"],
                    "avg_relative_cct_vs_dynamic": r["avg_relative_cct_vs_dynamic"],
                }
            )

    solve_seed_rows_global = sorted(
        solve_seed_rows_global,
        key=lambda r: (r["case_base"], seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
    )
    fct_seed_rows_global = sorted(
        fct_seed_rows_global,
        key=lambda r: (r["case_base"], seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
    )
    cct_p100_seed_rows_global = sorted(
        cct_p100_seed_rows_global,
        key=lambda r: (r["case_base"], seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
    )
    cct_p99_seed_rows_global = sorted(
        cct_p99_seed_rows_global,
        key=lambda r: (r["case_base"], seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
    )
    cct_p95_seed_rows_global = sorted(
        cct_p95_seed_rows_global,
        key=lambda r: (r["case_base"], seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
    )
    cct_avg_seed_rows_global = sorted(
        cct_avg_seed_rows_global,
        key=lambda r: (r["case_base"], seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
    )

    write_metric_csv(
        os.path.join(global_dir, "solve_time_per_seed.csv"),
        ["case_base", "seed", "scheduler", "avg_solve_time_ms"],
        solve_seed_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "fct_relative_per_seed.csv"),
        ["case_base", "seed", "scheduler", "avg_relative_fct_vs_dynamic"],
        fct_seed_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_p100_relative_per_seed.csv"),
        ["case_base", "seed", "scheduler", "avg_relative_cct_vs_dynamic"],
        cct_p100_seed_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_p99_relative_per_seed.csv"),
        ["case_base", "seed", "scheduler", "avg_relative_cct_vs_dynamic"],
        cct_p99_seed_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_p95_relative_per_seed.csv"),
        ["case_base", "seed", "scheduler", "avg_relative_cct_vs_dynamic"],
        cct_p95_seed_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_cct_avg_relative_per_seed.csv"),
        ["case_base", "seed", "scheduler", "avg_relative_cct_vs_dynamic"],
        cct_avg_seed_rows_global,
    )

    solve_rows_global: List[Dict[str, str]] = []
    fct_rows_global: List[Dict[str, str]] = []
    cct_rows_global: List[Dict[str, str]] = []
    cct_p99_rows_global: List[Dict[str, str]] = []
    cct_p95_rows_global: List[Dict[str, str]] = []
    cct_avg_rows_global: List[Dict[str, str]] = []

    for case_base in sorted(case_total.keys()):
        for scheduler in sorted(solve_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(solve_vals[case_base][scheduler])
            solve_rows_global.append(
                {
                    "case_base": case_base,
                    "scheduler": scheduler,
                    "seed_count": str(len(solve_vals[case_base][scheduler])),
                    "mean_avg_solve_time_ms": f"{mean_v:.3f}",
                    "std_avg_solve_time_ms": f"{std_v:.3f}",
                }
            )

        for scheduler in sorted(fct_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(fct_rel_vals[case_base][scheduler])
            fct_rows_global.append(
                {
                    "case_base": case_base,
                    "scheduler": scheduler,
                    "seed_count": str(len(fct_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_fct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_fct_vs_dynamic": f"{std_v:.3f}",
                }
            )

        for scheduler in sorted(cct_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_rel_vals[case_base][scheduler])
            cct_rows_global.append(
                {
                    "case_base": case_base,
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )

        for scheduler in sorted(cct_p99_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_p99_rel_vals[case_base][scheduler])
            cct_p99_rows_global.append(
                {
                    "case_base": case_base,
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_p99_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )

        for scheduler in sorted(cct_p95_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_p95_rel_vals[case_base][scheduler])
            cct_p95_rows_global.append(
                {
                    "case_base": case_base,
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_p95_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )

        for scheduler in sorted(cct_avg_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_avg_rel_vals[case_base][scheduler])
            cct_avg_rows_global.append(
                {
                    "case_base": case_base,
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_avg_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )

    write_metric_csv(
        os.path.join(global_dir, "solve_time_seed_avg.csv"),
        ["case_base", "scheduler", "seed_count", "mean_avg_solve_time_ms", "std_avg_solve_time_ms"],
        solve_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "fct_relative_seed_avg.csv"),
        [
            "case_base",
            "scheduler",
            "seed_count",
            "mean_avg_relative_fct_vs_dynamic",
            "std_avg_relative_fct_vs_dynamic",
        ],
        fct_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_p100_relative_seed_avg.csv"),
        [
            "case_base",
            "scheduler",
            "seed_count",
            "mean_avg_relative_cct_vs_dynamic",
            "std_avg_relative_cct_vs_dynamic",
        ],
        cct_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_p99_relative_seed_avg.csv"),
        [
            "case_base",
            "scheduler",
            "seed_count",
            "mean_avg_relative_cct_vs_dynamic",
            "std_avg_relative_cct_vs_dynamic",
        ],
        cct_p99_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_p95_relative_seed_avg.csv"),
        [
            "case_base",
            "scheduler",
            "seed_count",
            "mean_avg_relative_cct_vs_dynamic",
            "std_avg_relative_cct_vs_dynamic",
        ],
        cct_p95_rows_global,
    )
    write_metric_csv(
        os.path.join(global_dir, "coflow_cct_avg_relative_seed_avg.csv"),
        [
            "case_base",
            "scheduler",
            "seed_count",
            "mean_avg_relative_cct_vs_dynamic",
            "std_avg_relative_cct_vs_dynamic",
        ],
        cct_avg_rows_global,
    )

    # Per-case summaries and plots: <case>/seed_avg_summary/*
    for case_base in sorted(case_total.keys()):
        case_dir = case_dir_by_base.get(case_base, os.path.join(args.out_dir, case_base))
        case_seed_avg_dir = os.path.join(case_dir, "seed_avg_summary")
        os.makedirs(case_seed_avg_dir, exist_ok=True)
        case_solve_seed_rows = sorted(
            solve_seed_rows_by_case.get(case_base, []),
            key=lambda r: (seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
        )
        case_fct_seed_rows = sorted(
            fct_seed_rows_by_case.get(case_base, []),
            key=lambda r: (seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
        )
        case_cct_p100_seed_rows = sorted(
            cct_p100_seed_rows_by_case.get(case_base, []),
            key=lambda r: (seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
        )
        case_cct_p99_seed_rows = sorted(
            cct_p99_seed_rows_by_case.get(case_base, []),
            key=lambda r: (seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
        )
        case_cct_p95_seed_rows = sorted(
            cct_p95_seed_rows_by_case.get(case_base, []),
            key=lambda r: (seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
        )
        case_cct_avg_seed_rows = sorted(
            cct_avg_seed_rows_by_case.get(case_base, []),
            key=lambda r: (seed_order_key(r["seed"]), scheduler_order_key(r["scheduler"])),
        )

        write_metric_csv(
            os.path.join(case_seed_avg_dir, "seed_coverage.csv"),
            ["case_base", "num_success_seeds", "num_total_seeds"],
            [
                {
                    "case_base": case_base,
                    "num_success_seeds": str(case_success.get(case_base, 0)),
                    "num_total_seeds": str(case_total.get(case_base, 0)),
                }
            ],
        )

        write_metric_csv(
            os.path.join(case_seed_avg_dir, "solve_time_per_seed.csv"),
            ["seed", "scheduler", "avg_solve_time_ms"],
            case_solve_seed_rows,
        )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "fct_relative_per_seed.csv"),
            ["seed", "scheduler", "avg_relative_fct_vs_dynamic"],
            case_fct_seed_rows,
        )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_p100_relative_per_seed.csv"),
            ["seed", "scheduler", "avg_relative_cct_vs_dynamic"],
            case_cct_p100_seed_rows,
        )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_p99_relative_per_seed.csv"),
            ["seed", "scheduler", "avg_relative_cct_vs_dynamic"],
            case_cct_p99_seed_rows,
        )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_p95_relative_per_seed.csv"),
            ["seed", "scheduler", "avg_relative_cct_vs_dynamic"],
            case_cct_p95_seed_rows,
        )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_cct_avg_relative_per_seed.csv"),
            ["seed", "scheduler", "avg_relative_cct_vs_dynamic"],
            case_cct_avg_seed_rows,
        )

        solve_rows_case: List[Dict[str, str]] = []
        for scheduler in sorted(solve_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(solve_vals[case_base][scheduler])
            solve_rows_case.append(
                {
                    "scheduler": scheduler,
                    "seed_count": str(len(solve_vals[case_base][scheduler])),
                    "mean_avg_solve_time_ms": f"{mean_v:.3f}",
                    "std_avg_solve_time_ms": f"{std_v:.3f}",
                }
            )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "solve_time_seed_avg.csv"),
            ["scheduler", "seed_count", "mean_avg_solve_time_ms", "std_avg_solve_time_ms"],
            solve_rows_case,
        )
        if solve_rows_case:
            plot_metric_bar(
                solve_rows_case,
                value_key="mean_avg_solve_time_ms",
                std_key="std_avg_solve_time_ms",
                ylabel="Avg Solve Time (ms)",
                title=f"Solve Time Seed Average ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "solve_time_seed_avg.png"),
                relative=False,
            )
            plot_metric_box(
                solve_vals[case_base],
                ylabel="Avg Solve Time (ms)",
                title=f"Solve Time Seed Distribution ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "solve_time_seed_box.png"),
                relative=False,
            )

        fct_rows_case: List[Dict[str, str]] = []
        for scheduler in sorted(fct_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(fct_rel_vals[case_base][scheduler])
            fct_rows_case.append(
                {
                    "scheduler": scheduler,
                    "seed_count": str(len(fct_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_fct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_fct_vs_dynamic": f"{std_v:.3f}",
                }
            )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "fct_relative_seed_avg.csv"),
            [
                "scheduler",
                "seed_count",
                "mean_avg_relative_fct_vs_dynamic",
                "std_avg_relative_fct_vs_dynamic",
            ],
            fct_rows_case,
        )
        if fct_rows_case:
            plot_metric_bar(
                fct_rows_case,
                value_key="mean_avg_relative_fct_vs_dynamic",
                std_key="std_avg_relative_fct_vs_dynamic",
                ylabel="Avg Relative FCT (dynamic=1)",
                title=f"Relative FCT Seed Average ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "fct_relative_seed_avg.png"),
                relative=True,
            )
            plot_metric_box(
                fct_rel_vals[case_base],
                ylabel="Relative FCT (dynamic=1)",
                title=f"Relative FCT Seed Distribution ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "fct_relative_seed_box.png"),
                relative=True,
            )

        cct_rows_case: List[Dict[str, str]] = []
        for scheduler in sorted(cct_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_rel_vals[case_base][scheduler])
            cct_rows_case.append(
                {
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_p100_relative_seed_avg.csv"),
            [
                "scheduler",
                "seed_count",
                "mean_avg_relative_cct_vs_dynamic",
                "std_avg_relative_cct_vs_dynamic",
            ],
            cct_rows_case,
        )
        if cct_rows_case:
            plot_metric_bar(
                cct_rows_case,
                value_key="mean_avg_relative_cct_vs_dynamic",
                std_key="std_avg_relative_cct_vs_dynamic",
                ylabel="Avg Relative Coflow CCT (dynamic=1)",
                title=f"Relative Coflow CCT P100.0 Seed Average ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_p100_relative_seed_avg.png"),
                relative=True,
            )
            plot_metric_box(
                cct_rel_vals[case_base],
                ylabel="Relative Coflow CCT P100.0 (dynamic=1)",
                title=f"Relative Coflow CCT P100.0 Seed Distribution ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_p100_relative_seed_box.png"),
                relative=True,
            )

        cct_p99_rows_case: List[Dict[str, str]] = []
        for scheduler in sorted(cct_p99_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_p99_rel_vals[case_base][scheduler])
            cct_p99_rows_case.append(
                {
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_p99_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_p99_relative_seed_avg.csv"),
            [
                "scheduler",
                "seed_count",
                "mean_avg_relative_cct_vs_dynamic",
                "std_avg_relative_cct_vs_dynamic",
            ],
            cct_p99_rows_case,
        )
        if cct_p99_rows_case:
            plot_metric_bar(
                cct_p99_rows_case,
                value_key="mean_avg_relative_cct_vs_dynamic",
                std_key="std_avg_relative_cct_vs_dynamic",
                ylabel="P99 Relative Coflow CCT (dynamic=1)",
                title=f"Relative Coflow CCT P99.0 Seed Average ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_p99_relative_seed_avg.png"),
                relative=True,
            )
            plot_metric_box(
                cct_p99_rel_vals[case_base],
                ylabel="Relative Coflow CCT P99.0 (dynamic=1)",
                title=f"Relative Coflow CCT P99.0 Seed Distribution ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_p99_relative_seed_box.png"),
                relative=True,
            )

        cct_p95_rows_case: List[Dict[str, str]] = []
        for scheduler in sorted(cct_p95_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_p95_rel_vals[case_base][scheduler])
            cct_p95_rows_case.append(
                {
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_p95_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_p95_relative_seed_avg.csv"),
            [
                "scheduler",
                "seed_count",
                "mean_avg_relative_cct_vs_dynamic",
                "std_avg_relative_cct_vs_dynamic",
            ],
            cct_p95_rows_case,
        )
        if cct_p95_rows_case:
            plot_metric_bar(
                cct_p95_rows_case,
                value_key="mean_avg_relative_cct_vs_dynamic",
                std_key="std_avg_relative_cct_vs_dynamic",
                ylabel="P95 Relative Coflow CCT (dynamic=1)",
                title=f"Relative Coflow CCT P95.0 Seed Average ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_p95_relative_seed_avg.png"),
                relative=True,
            )
            plot_metric_box(
                cct_p95_rel_vals[case_base],
                ylabel="Relative Coflow CCT P95.0 (dynamic=1)",
                title=f"Relative Coflow CCT P95.0 Seed Distribution ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_p95_relative_seed_box.png"),
                relative=True,
            )

        cct_avg_rows_case: List[Dict[str, str]] = []
        for scheduler in sorted(cct_avg_rel_vals[case_base].keys(), key=scheduler_order_key):
            mean_v, std_v = summarize_values(cct_avg_rel_vals[case_base][scheduler])
            cct_avg_rows_case.append(
                {
                    "scheduler": scheduler,
                    "seed_count": str(len(cct_avg_rel_vals[case_base][scheduler])),
                    "mean_avg_relative_cct_vs_dynamic": f"{mean_v:.3f}",
                    "std_avg_relative_cct_vs_dynamic": f"{std_v:.3f}",
                }
            )
        write_metric_csv(
            os.path.join(case_seed_avg_dir, "coflow_cct_avg_relative_seed_avg.csv"),
            [
                "scheduler",
                "seed_count",
                "mean_avg_relative_cct_vs_dynamic",
                "std_avg_relative_cct_vs_dynamic",
            ],
            cct_avg_rows_case,
        )
        if cct_avg_rows_case:
            plot_metric_bar(
                cct_avg_rows_case,
                value_key="mean_avg_relative_cct_vs_dynamic",
                std_key="std_avg_relative_cct_vs_dynamic",
                ylabel="AVG Relative Coflow CCT (dynamic=1)",
                title=f"Relative Coflow CCT AVG Seed Average ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_cct_avg_relative_seed_avg.png"),
                relative=True,
            )
            plot_metric_box(
                cct_avg_rel_vals[case_base],
                ylabel="Relative Coflow CCT AVG (dynamic=1)",
                title=f"Relative Coflow CCT AVG Seed Distribution ({case_base})",
                out_png=os.path.join(case_seed_avg_dir, "coflow_cct_avg_relative_seed_box.png"),
                relative=True,
            )

    print(f"[seed-avg] batch_summary   : {args.batch_summary}")
    print(f"[seed-avg] scenario_root  : {args.out_dir}")
    print(f"[seed-avg] global_dir     : {global_dir}")
    print("[seed-avg] per-case dir   : <case>/seed_avg_summary")


if __name__ == "__main__":
    main()
