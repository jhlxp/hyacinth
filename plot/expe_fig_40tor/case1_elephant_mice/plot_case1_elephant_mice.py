#!/usr/bin/env python3

import argparse
import os
import shutil
import sys
from typing import Dict, List, Tuple

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
    GRID_LINEWIDTH,
    LABEL_FONT_SIZE,
    LEGEND_FONT_SIZE,
    TICK_FONT_SIZE,
    FileLogger,
    aggregate_case_fct_curve,
    detect_latest_scenario_root,
    derive_pdf_output_path,
    save_png_and_pdf,
)

CASE1_SCENARIO = "frag"
CASE1_BASE = "frag0p5"
CASE1_TARGET_SCHEDULERS = [
    "ocs_eps_global_ksp",            # Hybrid-ksp
    "pure_ocs_ksp",                  # Optics-ksp
    "ocs_eps_large_small",           # Helios
    "pure_ocs_ksp_greedy",           # Optics-greedy
    "ocs_eps_preset_dynamic_greedy", # Hyacinth
]
PAPER_NODE_LABEL = "2560nodes"
PAPER_CDF_DIR = os.path.abspath(
    os.path.join(EXPE_FIG_DIR, "..", "..", "..", "ToN-paper", "experiment", "cdf_40_80")
)


def pick_indices(common_len: int, points_per_group: int, pick_tail: bool) -> List[int]:
    k = max(1, points_per_group)
    if common_len <= 0:
        return []
    if not pick_tail:
        return list(range(min(k, common_len)))
    start = max(0, common_len - k)
    return list(range(start, common_len))


def make_subset(
    curves: Dict[str, List[Tuple[float, float, int]]],
    schedulers: List[str],
    indices: List[int],
) -> Dict[str, List[Tuple[float, float, int]]]:
    out: Dict[str, List[Tuple[float, float, int]]] = {}
    for s in schedulers:
        pts = curves.get(s, [])
        if not pts:
            continue
        out[s] = [pts[i] for i in indices if 0 <= i < len(pts)]
    return out


def plot_subset(
    curves: Dict[str, List[Tuple[float, float, int]]],
    schedulers: List[str],
    out_png: str,
    logger: FileLogger,
) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)

    dynamic_name = "ocs_eps_preset_dynamic_greedy"
    draw_order = [s for s in schedulers if s in curves]
    if dynamic_name in draw_order:
        draw_order = [s for s in draw_order if s != dynamic_name] + [dynamic_name]

    for s in draw_order:
        pts = curves[s]
        if not pts:
            continue
        x = [p[0] for p in pts]
        y = [p[1] for p in pts]
        z = 10 if s == dynamic_name else 3
        ax.plot(
            x,
            y,
            linewidth=2.0,
            marker="o",
            markersize=4.0,
            color=ALGORITHM_COLORS.get(s, "#9C9C9C"),
            label=ALGORITHM_LABELS.get(s, s),
            zorder=z,
        )

    ax.set_xscale("log")
    ax.set_xlabel("Flow Size (Bytes)", fontsize=LABEL_FONT_SIZE)
    ax.set_ylabel("FCT (ms)", fontsize=LABEL_FONT_SIZE)
    ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
    ax.grid(True, which="both", linestyle="--", linewidth=GRID_LINEWIDTH, alpha=0.25)
    ax.set_axisbelow(True)

    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def plot_legend_strip(
    schedulers: List[str],
    out_png: str,
    logger: FileLogger,
) -> None:
    if not schedulers:
        return

    fig_w = max(13.5, 2.6 * len(schedulers))
    fig_h = 0.9
    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), constrained_layout=True)
    ax.axis("off")

    handles = [
        Line2D(
            [0],
            [0],
            color=ALGORITHM_COLORS.get(s, "#9C9C9C"),
            marker="o",
            linewidth=2.0,
            markersize=5.0,
            label=ALGORITHM_LABELS.get(s, s),
        )
        for s in schedulers
    ]

    ax.legend(
        handles=handles,
        loc="center",
        ncol=len(handles),
        frameon=False,
        fontsize=LEGEND_FONT_SIZE,
        handlelength=2.0,
        columnspacing=1.45,
        handletextpad=0.45,
        borderaxespad=0.0,
    )
    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def log_selected_points(
    logger: FileLogger,
    tag: str,
    schedulers: List[str],
    curves: Dict[str, List[Tuple[float, float, int]]],
) -> None:
    logger.log(f"[subset] {tag}")
    for s in schedulers:
        pts = curves.get(s, [])
        if not pts:
            logger.log(f"[subset] {tag} scheduler={s} empty")
            continue
        summary = ", ".join([f"({p[0]:.3g}B,{p[1]:.3g}ms,n={p[2]})" for p in pts])
        logger.log(f"[subset] {tag} scheduler={s} points={summary}")


def export_paper_pdfs(
    out_mice: str,
    out_elephant: str,
    out_legend: str,
    logger: FileLogger,
) -> None:
    os.makedirs(PAPER_CDF_DIR, exist_ok=True)
    exports = [
        (derive_pdf_output_path(out_legend), "cdf_legend.pdf"),
        (derive_pdf_output_path(out_mice), f"mice_{PAPER_NODE_LABEL}.pdf"),
        (derive_pdf_output_path(out_elephant), f"elephant_{PAPER_NODE_LABEL}.pdf"),
    ]
    for src, name in exports:
        dst = os.path.join(PAPER_CDF_DIR, name)
        shutil.copy2(src, dst)
        logger.log(f"[export] pdf={dst}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot case1 mice/elephant subsets from 10-seed FCT-vs-bytes curves."
    )
    parser.add_argument("--scenario", default=CASE1_SCENARIO)
    parser.add_argument("--case_base", default=CASE1_BASE)
    parser.add_argument("--points_per_group", type=int, default=5)
    parser.add_argument("--out_dir", default="", help="Default: case1_elephant_mice/figures")
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(EXPE_FIG_DIR, "..", ".."))
    scenario_root = detect_latest_scenario_root(repo_root, args.scenario)
    out_dir = os.path.abspath(args.out_dir or os.path.join(SCRIPT_DIR, "figures"))
    os.makedirs(out_dir, exist_ok=True)

    log_path = os.path.join(out_dir, "case1_elephant_mice.log")
    logger = FileLogger(log_path)

    try:
        schedulers = list(CASE1_TARGET_SCHEDULERS)
        if not schedulers:
            raise RuntimeError("No target schedulers configured for case1.")

        logger.log(f"[case] scenario={args.scenario}")
        logger.log(f"[case] case_base={args.case_base}")
        logger.log(f"[case] scenario_root={scenario_root}")
        logger.log(f"[case] out_dir={out_dir}")
        logger.log(f"[algorithms] enabled={','.join(schedulers)}")

        curves = aggregate_case_fct_curve(
            scenario_root=scenario_root,
            case_base=args.case_base,
            schedulers=schedulers,
            logger=logger,
        )
        nonempty = [s for s in schedulers if curves.get(s)]
        if not nonempty:
            raise RuntimeError("No curve points loaded for selected case.")

        common_len = min(len(curves[s]) for s in nonempty)
        logger.log(f"[curve] nonempty_schedulers={','.join(nonempty)}")
        logger.log(f"[curve] common_len={common_len}")

        mice_idx = pick_indices(max(0, common_len - 1), args.points_per_group, pick_tail=False)
        mice_idx = [i + 1 for i in mice_idx]
        elephant_idx = pick_indices(common_len, args.points_per_group, pick_tail=True)
        logger.log(f"[pick] mice_indices={mice_idx}")
        logger.log(f"[pick] elephant_indices={elephant_idx}")

        mice_curves = make_subset(curves, schedulers, mice_idx)
        elephant_curves = make_subset(curves, schedulers, elephant_idx)

        log_selected_points(logger, "mice", schedulers, mice_curves)
        log_selected_points(logger, "elephant", schedulers, elephant_curves)

        out_mice = os.path.join(out_dir, f"case1_mice_{len(mice_idx)}points.png")
        out_elephant = os.path.join(out_dir, f"case1_elephant_{len(elephant_idx)}points.png")
        out_legend = os.path.join(out_dir, "case1_elephant_mice_legend.png")

        plot_subset(mice_curves, schedulers, out_mice, logger)
        plot_subset(elephant_curves, schedulers, out_elephant, logger)
        plot_legend_strip(nonempty, out_legend, logger)
        export_paper_pdfs(out_mice, out_elephant, out_legend, logger)

        logger.log("[done] case1 mice/elephant plots generated")
        logger.log(f"[done] log={log_path}")
    finally:
        logger.close()


if __name__ == "__main__":
    main()
