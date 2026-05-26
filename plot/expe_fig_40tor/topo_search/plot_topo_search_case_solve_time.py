#!/usr/bin/env python3

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
EXPE_FIG_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = os.path.join(EXPE_FIG_DIR, ".mplconfig")

import matplotlib.pyplot as plt

if EXPE_FIG_DIR not in sys.path:
    sys.path.insert(0, EXPE_FIG_DIR)

from algorithm_switches import ALGORITHM_COLORS, ALGORITHM_LABELS  # noqa: E402
from common_plot import (  # noqa: E402
    GRID_LINEWIDTH,
    LABEL_FONT_SIZE,
    TICK_FONT_SIZE,
    FileLogger,
    detect_latest_scenario_root,
    load_full_seed_cases,
    read_csv_dict,
    save_png_and_pdf,
    try_float,
)

TARGET_SCHEDULERS = [
    "pure_ocs_pruned",
    "ocs_eps_pruned",
]

TARGET_LABELS = {
    "ocs_eps_pruned": "Hyacinth-pruned",
}

TARGET_COLORS = {}

SCENARIOS = ["frag", "mix", "start_spread", "topo", "workload"]

# Hardcoded dedup for repeated base-performance aliases.
HARDCODED_DROP_CASES = {
    "mix/mix4L3M3S",
    "start_spread/spread100ms",
    "topo/n80_mix4L3M3S",
    "workload/cdf_fbcoco",
}

# Explicit Case 1..15 order.
TABLE_CASE_ORDER = [
    ("frag", "frag0p5"),
    ("frag", "frag0p1"),
    ("frag", "frag0p3"),
    ("frag", "frag0p7"),
    ("frag", "frag0p9"),
    ("mix", "mix10L"),
    ("mix", "mix20S"),
    ("start_spread", "spread0ms"),
    ("start_spread", "spread25ms"),
    ("start_spread", "spread50ms"),
    ("start_spread", "spread75ms"),
    ("topo", "n20_mix1L1M1S"),
    ("topo", "n40_mix3L2M1S"),
    ("workload", "cdf_fbcoco_february_2024"),
    ("workload", "cdf_fbcoco_march_2024"),
]


def extract_case_means(rows: List[Dict[str, str]], case_base: str) -> Optional[Dict[str, float]]:
    table: Dict[str, float] = {}
    for r in rows:
        cb = (r.get("case_base") or "").strip()
        if cb != case_base:
            continue
        sched = (r.get("scheduler") or "").strip()
        if sched not in TARGET_SCHEDULERS:
            continue
        mv = try_float(r.get("mean_avg_solve_time_ms", ""), float("nan"))
        if mv != mv:
            continue
        table[sched] = mv

    for s in TARGET_SCHEDULERS:
        if s not in table:
            return None
    return table


def build_case_series(repo_root: str, min_success_seeds: int, logger: FileLogger) -> Dict[str, List[float]]:
    points_map: Dict[Tuple[str, str], Dict[str, float]] = {}

    for scene in SCENARIOS:
        scenario_root = detect_latest_scenario_root(repo_root, scene)
        cases = load_full_seed_cases(scenario_root, min_success_seeds=min_success_seeds, logger=logger)
        seed_avg_dir = os.path.join(scenario_root, "seed_avg_summary")
        solve_rows = read_csv_dict(os.path.join(seed_avg_dir, "solve_time_seed_avg.csv"))

        logger.log(f"[load] scene={scene} scenario_root={scenario_root}")
        logger.log(f"[load] scene={scene} cases={cases}")

        for case_base in cases:
            case_key = f"{scene}/{case_base}"
            if case_key in HARDCODED_DROP_CASES:
                logger.log(f"[dedup-hardcoded] drop {case_key}")
                continue

            means = extract_case_means(solve_rows, case_base)
            if means is None:
                logger.log(f"[warn] missing solve rows: {case_key}")
                continue
            points_map[(scene, case_base)] = means

    series: Dict[str, List[float]] = {s: [] for s in TARGET_SCHEDULERS}
    for idx, key in enumerate(TABLE_CASE_ORDER, start=1):
        means = points_map.get(key)
        if means is None:
            logger.log(f"[warn] missing case in final order: case={idx} key={key[0]}/{key[1]}")
            continue
        for s in TARGET_SCHEDULERS:
            v = means[s]
            series[s].append(v)
            logger.log(
                f"[point] case={idx} key={key[0]}/{key[1]} scheduler={s} mean_avg_solve_time_ms={v:.6f}"
            )

    logger.log(f"[series] points={len(next(iter(series.values()), []))}")
    return series


def plot_case_solve_time(series: Dict[str, List[float]], out_png: str, logger: FileLogger) -> None:
    n = len(next(iter(series.values()), []))
    x = list(range(n))
    case_ticks = [str(i) for i in range(1, n + 1)]

    fig, ax = plt.subplots(1, 1, figsize=(10, 4), constrained_layout=True)
    all_vals: List[float] = []

    for s in TARGET_SCHEDULERS:
        ys = series.get(s, [])
        if len(ys) != n:
            logger.log(f"[warn] scheduler={s} has {len(ys)} points, expected={n}")
            continue
        all_vals.extend(ys)
        ax.plot(
            x,
            ys,
            linewidth=2.0,
            marker="o",
            markersize=4.8,
            color=TARGET_COLORS.get(s, ALGORITHM_COLORS.get(s, "#888888")),
            label=TARGET_LABELS.get(s, ALGORITHM_LABELS.get(s, s)),
            zorder=10 if s == "ocs_eps_pruned" else 3,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(case_ticks)
    ax.set_xlabel("Case", fontsize=LABEL_FONT_SIZE)
    ax.set_ylabel("Avg. Solve Time (ms)", fontsize=LABEL_FONT_SIZE - 0.5)
    ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
    ax.grid(True, axis="y", linestyle="--", linewidth=GRID_LINEWIDTH + 0.5, color="#666666", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=TICK_FONT_SIZE - 2, ncol=2, loc="upper left")

    if all_vals:
        y_max = max(all_vals)
        y_top = y_max + max(0.10 * y_max, 0.03)
        ax.set_ylim(0.0, y_top)
        logger.log(f"[ylim] range=(0,{y_top:.6f})")

    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot case-wise solve-time line for topology-search algorithms.")
    parser.add_argument("--out_dir", default="", help="Default: topo_search/figures")
    parser.add_argument("--min_success_seeds", type=int, default=10)
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir or os.path.join(SCRIPT_DIR, "figures"))
    os.makedirs(out_dir, exist_ok=True)

    logger = FileLogger(os.path.join(out_dir, "topo_search_case_solve_time.log"))
    try:
        repo_root = os.path.abspath(os.path.join(EXPE_FIG_DIR, "..", ".."))
        logger.log(f"[run] repo_root={repo_root}")
        logger.log(f"[run] out_dir={out_dir}")
        logger.log(f"[algorithms] target={','.join(TARGET_SCHEDULERS)}")

        series = build_case_series(repo_root=repo_root, min_success_seeds=args.min_success_seeds, logger=logger)
        plot_case_solve_time(
            series=series,
            out_png=os.path.join(out_dir, "topo_search_case_solve_time_line.png"),
            logger=logger,
        )

        logger.log("[done] topo_search_case_solve_time")
    finally:
        logger.close()


if __name__ == "__main__":
    main()
