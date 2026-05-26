#!/usr/bin/env python3

import argparse
import math
import os
import sys
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
EXPE_FIG_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = os.path.join(EXPE_FIG_DIR, ".mplconfig")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

if EXPE_FIG_DIR not in sys.path:
    sys.path.insert(0, EXPE_FIG_DIR)

from common_plot import (  # noqa: E402
    ANNOT_FONT_SIZE,
    GRID_LINEWIDTH,
    LABEL_FONT_SIZE,
    RELATIVE_BASELINE_LINEWIDTH,
    TICK_FONT_SIZE,
    FileLogger,
    apply_centered_ylim,
    apply_regular_ylim,
    detect_latest_scenario_root,
    load_full_seed_cases,
    read_csv_dict,
    save_png_and_pdf,
    try_float,
)

SCENARIOS = ["frag", "mix", "start_spread", "topo", "workload"]
TARGET_SCHEDULERS = [
    "ocs_eps_preset_dynamic_greedy",
    "ocs_eps_pruned",
    "ocs_eps_preset_greedy_10pct",
    "ocs_eps_preset_greedy_20pct",
    "ocs_eps_preset_greedy_30pct",
]
SCHEDULER_ALIASES = {
    # Preserve backward compatibility with legacy naming in older logs.
    "ocs_eps_preset_greedy_10pct": ["ocs_eps_preset_greedy_10pct"],
    "ocs_eps_preset_greedy_20pct": ["ocs_eps_preset_greedy_20pct", "ocs_eps_preset_greedy"],
    "ocs_eps_preset_greedy_30pct": ["ocs_eps_preset_greedy_30pct"],
}
TARGET_LABELS = {
    "ocs_eps_preset_dynamic_greedy": "Hyacinth-dynamic",
    "ocs_eps_pruned": "Hyacinth-pruned",
    "ocs_eps_preset_greedy_10pct": "Hyacinth-static-10%",
    "ocs_eps_preset_greedy_20pct": "Hyacinth-static-20%",
    "ocs_eps_preset_greedy_30pct": "Hyacinth-static-30%",
}
TARGET_COLORS = {
    "ocs_eps_preset_dynamic_greedy": "#000000",
    "ocs_eps_pruned": "#FF9900",
    "ocs_eps_preset_greedy_10pct": "#6DA8FF",
    "ocs_eps_preset_greedy_20pct": "#3071F4",
    "ocs_eps_preset_greedy_30pct": "#1E4FB8",
}
TARGET_LINESTYLES = {
    "ocs_eps_preset_dynamic_greedy": "-",
    "ocs_eps_pruned": "--",
    "ocs_eps_preset_greedy_10pct": ":",
    "ocs_eps_preset_greedy_20pct": "-.",
    "ocs_eps_preset_greedy_30pct": "--",
}
TARGET_MARKERS = {
    "ocs_eps_preset_dynamic_greedy": "o",
    "ocs_eps_pruned": "s",
    "ocs_eps_preset_greedy_10pct": "^",
    "ocs_eps_preset_greedy_20pct": "D",
    "ocs_eps_preset_greedy_30pct": "P",
}
Y_LABEL_FONT_SIZE = LABEL_FONT_SIZE - 0.5
MERGED_Y_LABEL_FONT_SIZE = Y_LABEL_FONT_SIZE - 0.5
MERGED_X_TICK_FONT_SIZE = TICK_FONT_SIZE - 1
FIXED_DYNAMIC_GRID_LINEWIDTH = 2.0
FIXED_DYNAMIC_GRID_COLOR = "#777777"

# Hardcoded dedup list for repeated base-performance cases across scenarios.
# Keep the representative one in frag/* and drop the following aliases.
HARDCODED_DROP_CASES = {
    "mix/mix4L3M3S",
    "start_spread/spread100ms",
    "topo/n80_mix4L3M3S",
    "workload/cdf_fbcoco",
}

# Explicit order aligned with paper table Case 1..15.
TABLE_CASE_ORDER = [
    ("frag", "frag0p5"),                   # Case 1: Default
    ("frag", "frag0p1"),                   # Case 2
    ("frag", "frag0p3"),                   # Case 3
    ("frag", "frag0p7"),                   # Case 4
    ("frag", "frag0p9"),                   # Case 5
    ("mix", "mix5L"),                      # Case 6
    ("mix", "mix10S"),                     # Case 7
    ("start_spread", "spread0ms"),         # Case 8
    ("start_spread", "spread25ms"),        # Case 9
    ("start_spread", "spread50ms"),        # Case 10
    ("start_spread", "spread75ms"),        # Case 11
    ("workload", "cdf_fbcoco_february_2024"),  # Case 12
    ("workload", "cdf_fbcoco_march_2024"),     # Case 13
]


def resolve_scheduler_key(available_keys: set[str], scheduler: str) -> Optional[str]:
    candidates = SCHEDULER_ALIASES.get(scheduler, [scheduler])
    for c in candidates:
        if c in available_keys:
            return c
    return None


def pick_active_schedulers(repo_root: str, min_success_seeds: int, logger: FileLogger) -> List[str]:
    present_count = {s: 0 for s in TARGET_SCHEDULERS}
    total_cases = 0

    for exp_name in SCENARIOS:
        scenario_root = detect_latest_scenario_root(repo_root, exp_name)
        cases = load_full_seed_cases(scenario_root, min_success_seeds=min_success_seeds, logger=logger)
        seed_avg_dir = os.path.join(scenario_root, "seed_avg_summary")
        coflow_rows = read_csv_dict(os.path.join(seed_avg_dir, "coflow_cct_avg_relative_seed_avg.csv"))

        case_scheds: Dict[str, set[str]] = {}
        for r in coflow_rows:
            case = (r.get("case_base") or "").strip()
            sched = (r.get("scheduler") or "").strip()
            if not case or not sched:
                continue
            case_scheds.setdefault(case, set()).add(sched)

        for case_base in cases:
            case_key = f"{exp_name}/{case_base}"
            if case_key in HARDCODED_DROP_CASES:
                continue
            total_cases += 1
            keys = case_scheds.get(case_base, set())
            for s in TARGET_SCHEDULERS:
                if resolve_scheduler_key(keys, s) is not None:
                    present_count[s] += 1

    if total_cases <= 0:
        logger.log("[fatal] no cases found while selecting active schedulers")
        return []

    active = [s for s in TARGET_SCHEDULERS if present_count[s] == total_cases]
    for s in TARGET_SCHEDULERS:
        if s not in active:
            logger.log(f"[scheduler-drop] scheduler={s} present_cases={present_count[s]}/{total_cases}")
    logger.log(f"[scheduler-active] total_cases={total_cases} schedulers={','.join(active)}")
    return active


def extract_case_values(
    rows: List[Dict[str, str]],
    case_base: str,
    schedulers: List[str],
    mean_col: str,
    std_col: str,
) -> Optional[Tuple[List[float], List[float]]]:
    table: Dict[str, Tuple[float, float]] = {}
    for r in rows:
        cb = (r.get("case_base") or "").strip()
        if cb != case_base:
            continue
        s = (r.get("scheduler") or "").strip()
        mv = try_float(r.get(mean_col, ""), float("nan"))
        sv = try_float(r.get(std_col, ""), 0.0)
        if math.isnan(mv):
            continue
        table[s] = (mv, max(0.0, sv))

    vals: List[float] = []
    errs: List[float] = []
    keys = set(table.keys())
    for s in schedulers:
        resolved = resolve_scheduler_key(keys, s)
        pair = table.get(resolved) if resolved is not None else None
        if pair is None:
            return None
        vals.append(pair[0])
        errs.append(pair[1])
    return vals, errs


def format_relative_percent(value: float, ref_value: float, is_ref: bool) -> str:
    if is_ref:
        return ""
    if abs(ref_value) < 1e-12:
        return "N/A"
    delta_pct = (value / ref_value - 1.0) * 100.0
    return f"{delta_pct:+.1f}%"


def plot_two_bar_case(
    vals: List[float],
    errs: List[float],
    schedulers: List[str],
    y_label: str,
    out_png: str,
    is_relative: bool,
    use_centered_ylim: bool,
    show_value_labels: bool,
    logger: FileLogger,
) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)

    x = list(range(len(schedulers)))
    colors = [TARGET_COLORS.get(s, "#9C9C9C") for s in schedulers]
    labels = [TARGET_LABELS.get(s, s) for s in schedulers]
    ax.bar(x, vals, yerr=errs, capsize=2, color=colors, edgecolor="none", width=0.56)

    if is_relative:
        ax.axhline(1.0, linestyle="--", linewidth=RELATIVE_BASELINE_LINEWIDTH, color="#444444", alpha=0.8)

    target_sched = "ocs_eps_pruned"
    target_index = schedulers.index(target_sched) if target_sched in schedulers else len(schedulers) - 1
    if use_centered_ylim:
        apply_centered_ylim(
            ax=ax,
            vals=vals,
            errs=errs,
            target_index=target_index,
            is_relative=is_relative,
            logger=logger,
            out_png=out_png,
        )
    else:
        apply_regular_ylim(
            ax=ax,
            vals=vals,
            errs=errs,
            is_relative=is_relative,
            force_zero_baseline=(not is_relative),
            logger=logger,
            out_png=out_png,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=TICK_FONT_SIZE)
    ax.set_ylabel(y_label, fontsize=Y_LABEL_FONT_SIZE)
    ax.tick_params(axis="y", labelsize=TICK_FONT_SIZE)
    ax.grid(
        True,
        axis="y",
        linestyle="--",
        linewidth=FIXED_DYNAMIC_GRID_LINEWIDTH,
        color=FIXED_DYNAMIC_GRID_COLOR,
        alpha=0.25,
    )
    ax.set_axisbelow(True)

    if show_value_labels:
        ref_value = vals[target_index]
        y_low, y_high = ax.get_ylim()
        y_span = max(1e-9, y_high - y_low)
        text_gap = 0.015 * y_span
        for i, v in enumerate(vals):
            label = format_relative_percent(v, ref_value, is_ref=(i == target_index))
            if not label:
                continue
            y_text = v + max(0.0, errs[i]) + text_gap
            va = "bottom"
            if y_text > y_high - 0.005 * y_span:
                y_text = y_high - 0.01 * y_span
                va = "top"
            ax.text(i, y_text, label, ha="center", va=va, fontsize=ANNOT_FONT_SIZE)

    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def plot_merged_line(
    x_labels: List[str],
    series: Dict[str, List[float]],
    schedulers: List[str],
    y_label: str,
    out_png: str,
    logger: FileLogger,
    is_relative: bool,
) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)
    x = list(range(len(x_labels)))
    case_ticks = [str(i) for i in range(1, len(x_labels) + 1)]

    for s in schedulers:
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
            label=TARGET_LABELS.get(s, s),
        )

    if is_relative:
        ax.axhline(1.0, linestyle="--", linewidth=RELATIVE_BASELINE_LINEWIDTH, color="#444444", alpha=0.8)
        all_y = [v for ys in series.values() for v in ys]
        if all_y:
            data_min = min(all_y)
            data_max = max(all_y)
            span = max(1e-9, data_max - data_min)

            # Put y=1.0 around the lower quartile (about 25% from bottom)
            # while still covering all points with small padding.
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
        linewidth=FIXED_DYNAMIC_GRID_LINEWIDTH,
        color=FIXED_DYNAMIC_GRID_COLOR,
        alpha=0.25,
    )
    ax.set_axisbelow(True)

    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def plot_shared_legend_strip(schedulers: List[str], out_png: str, logger: FileLogger) -> None:
    fig_w = 5.6 if len(schedulers) <= 3 else max(8.5, 2.0 * len(schedulers))
    fig_h = 0.55 if len(schedulers) <= 3 else 1.35
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
            label=TARGET_LABELS.get(s, s),
        )
        for s in schedulers
    ]
    ax.legend(
        handles=handles,
        loc="center",
        ncol=len(handles),
        frameon=False,
        fontsize=TICK_FONT_SIZE - 2,
        handlelength=1.15,
        columnspacing=0.55,
        handletextpad=0.28,
        borderaxespad=0.0,
    )

    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def run_main_plots(repo_root: str, out_root: str, min_success_seeds: int) -> None:
    bootstrap_logger = FileLogger(os.path.join(out_root, "fixed_dynamic_main_scheduler_scan.log"))
    try:
        active_schedulers = pick_active_schedulers(repo_root, min_success_seeds, bootstrap_logger)
    finally:
        bootstrap_logger.close()
    if not active_schedulers:
        raise RuntimeError("No active schedulers available for fixed_dynamic per-case plots.")

    for exp_name in SCENARIOS:
        scenario_root = detect_latest_scenario_root(repo_root, exp_name)
        out_dir = os.path.join(out_root, exp_name, "figures")
        os.makedirs(out_dir, exist_ok=True)

        logger = FileLogger(os.path.join(out_dir, f"{exp_name}.log"))
        try:
            logger.log(f"[section] exp_name={exp_name}")
            logger.log(f"[section] scenario_root={scenario_root}")
            logger.log(f"[section] out_dir={out_dir}")
            logger.log(f"[algorithms] enabled={','.join(active_schedulers)}")

            cases = load_full_seed_cases(scenario_root, min_success_seeds=min_success_seeds, logger=logger)
            logger.log(f"[cases] selected={cases}")

            seed_avg_dir = os.path.join(scenario_root, "seed_avg_summary")
            coflow_rows = read_csv_dict(os.path.join(seed_avg_dir, "coflow_cct_avg_relative_seed_avg.csv"))
            solve_rows = read_csv_dict(os.path.join(seed_avg_dir, "solve_time_seed_avg.csv"))

            for case_base in cases:
                coflow = extract_case_values(
                    coflow_rows,
                    case_base,
                    active_schedulers,
                    "mean_avg_relative_cct_vs_dynamic",
                    "std_avg_relative_cct_vs_dynamic",
                )
                if coflow is None:
                    logger.log(f"[warn] missing coflow rows: case={case_base}")
                else:
                    out_png = os.path.join(out_dir, f"coflow_cct_fixed_dynamic_{case_base}.png")
                    plot_two_bar_case(
                        vals=coflow[0],
                        errs=coflow[1],
                        schedulers=active_schedulers,
                        y_label="Norm. Avg CCT",
                        out_png=out_png,
                        is_relative=True,
                        use_centered_ylim=True,
                        show_value_labels=True,
                        logger=logger,
                    )

                solve = extract_case_values(
                    solve_rows,
                    case_base,
                    active_schedulers,
                    "mean_avg_solve_time_ms",
                    "std_avg_solve_time_ms",
                )
                if solve is None:
                    logger.log(f"[warn] missing solve rows: case={case_base}")
                else:
                    out_png = os.path.join(out_dir, f"solve_time_fixed_dynamic_{case_base}.png")
                    plot_two_bar_case(
                        vals=solve[0],
                        errs=solve[1],
                        schedulers=active_schedulers,
                        y_label="Avg. Solve Time (ms)",
                        out_png=out_png,
                        is_relative=False,
                        use_centered_ylim=False,
                        show_value_labels=False,
                        logger=logger,
                    )

            logger.log(f"[done] section={exp_name}")
        finally:
            logger.close()


def run_merged_line_plots(repo_root: str, out_root: str, min_success_seeds: int) -> None:
    out_dir = os.path.join(out_root, "figures")
    os.makedirs(out_dir, exist_ok=True)
    logger = FileLogger(os.path.join(out_dir, "fixed_dynamic.log"))

    try:
        active_schedulers = pick_active_schedulers(repo_root, min_success_seeds, logger)
        if not active_schedulers:
            raise RuntimeError("No active schedulers available for fixed_dynamic plots.")

        logger.log("[merged] start")
        logger.log(f"[algorithms] enabled={','.join(active_schedulers)}")

        plot_shared_legend_strip(
            schedulers=active_schedulers,
            out_png=os.path.join(out_dir, "00_fixed_dynamic_legend.png"),
            logger=logger,
        )

        points_map: Dict[Tuple[str, str], Dict[str, object]] = {}

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

                coflow = extract_case_values(
                    coflow_rows,
                    case_base,
                    active_schedulers,
                    "mean_avg_relative_cct_vs_dynamic",
                    "std_avg_relative_cct_vs_dynamic",
                )
                solve = extract_case_values(
                    solve_rows,
                    case_base,
                    active_schedulers,
                    "mean_avg_solve_time_ms",
                    "std_avg_solve_time_ms",
                )
                if coflow is None or solve is None:
                    logger.log(f"[warn] skip incomplete case: {exp_name}/{case_base}")
                    continue

                key = (exp_name, case_base)
                points_map[key] = {
                    "scene": exp_name,
                    "case": case_base,
                    "label": case_base,
                    "coflow": {s: coflow[0][i] for i, s in enumerate(active_schedulers)},
                    "solve": {s: solve[0][i] for i, s in enumerate(active_schedulers)},
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

        logger.log(
            "[order] case_sequence="
            + str([f"{p['scene']}/{p['case']}" for p in points])
        )
        logger.log(f"[merged] unique_cases={len(points)}")

        x_labels = [str(p["label"]) for p in points]
        coflow_series = {
            s: [float(p["coflow"][s]) for p in points] for s in active_schedulers
        }
        solve_series = {
            s: [float(p["solve"][s]) for p in points] for s in active_schedulers
        }

        plot_merged_line(
            x_labels=x_labels,
            series=coflow_series,
            schedulers=active_schedulers,
            y_label="Norm. Avg CCT",
            out_png=os.path.join(out_dir, "all_cases_case_order_coflow_line.png"),
            logger=logger,
            is_relative=True,
        )
        plot_merged_line(
            x_labels=x_labels,
            series=solve_series,
            schedulers=active_schedulers,
            y_label="Avg. Solve Time (ms)",
            out_png=os.path.join(out_dir, "all_cases_case_order_solve_time_line.png"),
            logger=logger,
            is_relative=False,
        )

        logger.log("[merged] done")
    finally:
        logger.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot fixed-vs-dynamic all_scenarios line figures only.")
    parser.add_argument("--out_root", default="", help="Default: expe_fig/fixed_dynamic")
    parser.add_argument("--min_success_seeds", type=int, default=10)
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(EXPE_FIG_DIR, "..", ".."))
    out_root = args.out_root or SCRIPT_DIR

    run_merged_line_plots(repo_root=repo_root, out_root=os.path.abspath(out_root), min_success_seeds=args.min_success_seeds)


if __name__ == "__main__":
    main()
