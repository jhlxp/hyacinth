#!/usr/bin/env python3

import argparse
import math
import os
import sys
from typing import Dict, List, Optional

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
EXPE_FIG_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = os.path.join(EXPE_FIG_DIR, ".mplconfig")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

if EXPE_FIG_DIR not in sys.path:
    sys.path.insert(0, EXPE_FIG_DIR)

from algorithm_switches import ALGORITHM_COLORS, ALGORITHM_LABELS  # noqa: E402
from common_plot import (  # noqa: E402
    LABEL_FONT_SIZE,
    RELATIVE_BASELINE_LINEWIDTH,
    TICK_FONT_SIZE,
    FileLogger,
    detect_latest_scenario_root,
    load_full_seed_cases,
    read_csv_dict,
    save_png_and_pdf,
    try_float,
)

SCENARIOS = ["frag", "mix", "start_spread", "topo", "workload"]
TARGET_SCHEDULERS = [
    "pure_ocs_pruned",
    "ocs_eps_pruned",
]

TARGET_LABELS = {
    "pure_ocs_pruned": "Optics-pruned",
    "ocs_eps_pruned": "Hyacinth-pruned",
}

TARGET_COLORS = {
    "pure_ocs_pruned": ALGORITHM_COLORS.get("pure_ocs_pruned", "#3DB19E"),
    "ocs_eps_pruned": ALGORITHM_COLORS.get("ocs_eps_pruned", "#FF9900"),
}

TARGET_LINESTYLES = {
    "pure_ocs_pruned": "-",
    "ocs_eps_pruned": "-.",
}

TARGET_MARKERS = {
    "pure_ocs_pruned": "o",
    "ocs_eps_pruned": "s",
}

BASELINE_SCHEDULER = "ocs_eps_pruned"

MERGED_Y_LABEL_FONT_SIZE = LABEL_FONT_SIZE - 1.0
MERGED_X_TICK_FONT_SIZE = TICK_FONT_SIZE - 1
PLOT_GRID_LINEWIDTH = 2.0
PLOT_GRID_COLOR = "#777777"

# Keep one representative base case and drop duplicated aliases.
HARDCODED_DROP_CASES = {
    "mix/mix3L2M1S",
    "start_spread/spread100ms",
    "topo/n80_mix4L3M3S",
    "workload/cdf_fbcoco",
}

# Follow fixed_dynamic case-order style for direct visual comparison.
TABLE_CASE_ORDER = [
    ("frag", "frag0p5"),
    ("frag", "frag0p1"),
    ("frag", "frag0p3"),
    ("frag", "frag0p7"),
    ("frag", "frag0p9"),
    ("mix", "mix5L"),
    ("mix", "mix10S"),
    ("start_spread", "spread0ms"),
    ("start_spread", "spread25ms"),
    ("start_spread", "spread50ms"),
    ("start_spread", "spread75ms"),
    ("workload", "cdf_fbcoco_february_2024"),
    ("workload", "cdf_fbcoco_march_2024"),
]


def extract_coflow_normalized(rows: List[Dict[str, str]], case_base: str) -> Optional[Dict[str, float]]:
    table: Dict[str, float] = {}
    for r in rows:
        cb = (r.get("case_base") or "").strip()
        if cb != case_base:
            continue
        sched = (r.get("scheduler") or "").strip()
        if sched not in TARGET_SCHEDULERS:
            continue
        mv = try_float(r.get("mean_avg_relative_cct_vs_dynamic", ""), float("nan"))
        if math.isnan(mv):
            continue
        table[sched] = mv

    for s in TARGET_SCHEDULERS:
        if s not in table:
            return None

    base = table.get(BASELINE_SCHEDULER, float("nan"))
    if math.isnan(base) or abs(base) < 1e-12:
        return None

    return {s: (table[s] / base) for s in TARGET_SCHEDULERS}


def extract_solve_means(rows: List[Dict[str, str]], case_base: str) -> Optional[Dict[str, float]]:
    table: Dict[str, float] = {}
    for r in rows:
        cb = (r.get("case_base") or "").strip()
        if cb != case_base:
            continue
        sched = (r.get("scheduler") or "").strip()
        if sched not in TARGET_SCHEDULERS:
            continue
        mv = try_float(r.get("mean_avg_solve_time_ms", ""), float("nan"))
        if math.isnan(mv):
            continue
        table[sched] = mv

    for s in TARGET_SCHEDULERS:
        if s not in table:
            return None
    return table


def plot_merged_line(
    x_labels: List[str],
    series: Dict[str, List[float]],
    y_label: str,
    out_png: str,
    logger: FileLogger,
    is_relative: bool,
) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)
    x = list(range(len(x_labels)))
    case_ticks = [str(i) for i in range(1, len(x_labels) + 1)]

    for s in TARGET_SCHEDULERS:
        y = series.get(s, [])
        if not y:
            continue
        ax.plot(
            x,
            y,
            linewidth=2.0,
            linestyle=TARGET_LINESTYLES.get(s, "-"),
            marker=TARGET_MARKERS.get(s, "o"),
            markersize=5.0,
            color=TARGET_COLORS.get(s, "#9C9C9C"),
            label=TARGET_LABELS.get(s, ALGORITHM_LABELS.get(s, s)),
        )

    if is_relative:
        ax.axhline(1.0, linestyle="--", linewidth=RELATIVE_BASELINE_LINEWIDTH, color="#444444", alpha=0.8)
        all_y = [v for ys in series.values() for v in ys]
        if all_y:
            data_min = min(all_y)
            data_max = max(all_y)
            span = max(1e-9, data_max - data_min)

            y_top = max(data_max, 1.0) + max(0.10 * span, 0.03 * max(data_max, 1.0))
            ideal_bottom = 1.0 - (y_top - 1.0) / 3.0
            data_bottom = data_min - 0.06 * max(span, abs(data_min))
            y_bottom = min(ideal_bottom, data_bottom)
            y_bottom = max(0.0, y_bottom)
            if y_top <= y_bottom:
                y_top = y_bottom + 1e-3
            ax.set_ylim(y_bottom, y_top)
            pos = (1.0 - y_bottom) / (y_top - y_bottom)
            logger.log(
                f"[ylim] relative target_baseline=0.25 actual_baseline={pos:.3f} range=({y_bottom:.6g},{y_top:.6g})"
            )
    else:
        all_y = [v for ys in series.values() for v in ys]
        if all_y:
            y_max = max(all_y)
            y_min = min(all_y)
            span = max(1e-9, y_max - y_min)
            y_top = y_max + max(0.10 * span, 0.03 * max(y_max, 1e-9))
            if y_top <= 0.0:
                y_top = 1e-3
            ax.set_ylim(0.0, y_top)
            logger.log(f"[ylim] nonrelative_from_zero range=(0,{y_top:.6g})")

    ax.set_xticks(x)
    ax.set_xticklabels(case_ticks, fontsize=MERGED_X_TICK_FONT_SIZE)
    ax.set_xlabel("Case", fontsize=LABEL_FONT_SIZE)
    ax.set_ylabel(y_label, fontsize=MERGED_Y_LABEL_FONT_SIZE)
    ax.tick_params(axis="y", labelsize=TICK_FONT_SIZE)
    ax.grid(
        True,
        axis="y",
        linestyle="--",
        linewidth=PLOT_GRID_LINEWIDTH,
        color=PLOT_GRID_COLOR,
        alpha=0.25,
    )
    ax.set_axisbelow(True)

    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def plot_shared_legend_strip(out_png: str, logger: FileLogger) -> None:
    fig_w = 4.2
    fig_h = 0.42
    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), constrained_layout=False)
    ax.axis("off")

    handles = [
        Line2D(
            [0],
            [0],
            linestyle=TARGET_LINESTYLES.get(s, "-"),
            linewidth=2.0,
            marker=TARGET_MARKERS.get(s, "o"),
            markersize=9.0,
            color=TARGET_COLORS.get(s, "#9C9C9C"),
            markerfacecolor=TARGET_COLORS.get(s, "#9C9C9C"),
            markeredgecolor=TARGET_COLORS.get(s, "#9C9C9C"),
            label=TARGET_LABELS.get(s, ALGORITHM_LABELS.get(s, s)),
        )
        for s in TARGET_SCHEDULERS
    ]
    ax.legend(
        handles=handles,
        loc="center",
        ncol=len(handles),
        frameon=False,
        fontsize=TICK_FONT_SIZE - 1,
        handlelength=1.15,
        columnspacing=0.55,
        handletextpad=0.28,
        borderaxespad=0.0,
    )

    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def run_merged_line_plots(repo_root: str, out_root: str, min_success_seeds: int) -> None:
    out_dir = os.path.join(out_root, "figures")
    os.makedirs(out_dir, exist_ok=True)
    logger = FileLogger(os.path.join(out_dir, "topo_search.log"))

    try:
        logger.log("[merged] start")
        logger.log(f"[algorithms] enabled={','.join(TARGET_SCHEDULERS)}")
        logger.log(f"[baseline] scheduler={BASELINE_SCHEDULER}")

        plot_shared_legend_strip(
            out_png=os.path.join(out_dir, "00_topo_search_legend.png"),
            logger=logger,
        )

        points_map: Dict[tuple[str, str], Dict[str, object]] = {}

        for exp_name in SCENARIOS:
            scenario_root = detect_latest_scenario_root(repo_root, exp_name)
            cases = load_full_seed_cases(scenario_root, min_success_seeds=min_success_seeds, logger=logger)
            seed_avg_dir = os.path.join(scenario_root, "seed_avg_summary")
            coflow_rows = read_csv_dict(os.path.join(seed_avg_dir, "coflow_cct_avg_relative_seed_avg.csv"))
            solve_rows = read_csv_dict(os.path.join(seed_avg_dir, "solve_time_seed_avg.csv"))

            for case_base in cases:
                case_key = f"{exp_name}/{case_base}"
                if case_key in HARDCODED_DROP_CASES:
                    logger.log(f"[dedup-hardcoded] drop {case_key}")
                    continue

                coflow = extract_coflow_normalized(coflow_rows, case_base)
                solve = extract_solve_means(solve_rows, case_base)
                if coflow is None or solve is None:
                    logger.log(f"[warn] skip incomplete case: {exp_name}/{case_base}")
                    continue

                key = (exp_name, case_base)
                points_map[key] = {
                    "scene": exp_name,
                    "case": case_base,
                    "label": case_base,
                    "coflow": coflow,
                    "solve": solve,
                }

        points: List[Dict[str, object]] = []
        for idx, key in enumerate(TABLE_CASE_ORDER, start=1):
            point = points_map.get(key)
            if point is None:
                logger.log(f"[warn] missing_case_in_data case={idx} key={key[0]}/{key[1]}")
                continue
            points.append(point)

        table_case_keys = set(TABLE_CASE_ORDER)
        extra_keys = [k for k in points_map.keys() if k not in table_case_keys]
        if extra_keys:
            logger.log(f"[order] drop_unlisted_cases={['%s/%s' % (k[0], k[1]) for k in extra_keys]}")

        logger.log("[order] case_sequence=" + str([f"{p['scene']}/{p['case']}" for p in points]))
        logger.log(f"[merged] unique_cases={len(points)}")

        x_labels = [str(p["label"]) for p in points]
        coflow_series = {s: [float(p["coflow"][s]) for p in points] for s in TARGET_SCHEDULERS}
        solve_series = {s: [float(p["solve"][s]) for p in points] for s in TARGET_SCHEDULERS}

        plot_merged_line(
            x_labels=x_labels,
            series=coflow_series,
            y_label="Norm. Avg CCT",
            out_png=os.path.join(out_dir, "all_cases_case_order_coflow_line.png"),
            logger=logger,
            is_relative=True,
        )
        plot_merged_line(
            x_labels=x_labels,
            series=solve_series,
            y_label="Avg. Solve Time (ms)",
            out_png=os.path.join(out_dir, "all_cases_case_order_solve_time_line.png"),
            logger=logger,
            is_relative=False,
        )

        logger.log("[merged] done")
    finally:
        logger.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot topology-search figures with fixed_dynamic style (legend + 2 lines).")
    parser.add_argument("--out_root", default="", help="Default: expe_fig/topo_search")
    parser.add_argument("--min_success_seeds", type=int, default=10)
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(EXPE_FIG_DIR, "..", ".."))
    out_root = args.out_root or SCRIPT_DIR

    run_merged_line_plots(repo_root=repo_root, out_root=os.path.abspath(out_root), min_success_seeds=args.min_success_seeds)


if __name__ == "__main__":
    main()
