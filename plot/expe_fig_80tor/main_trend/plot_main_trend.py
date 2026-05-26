#!/usr/bin/env python3

import argparse
import math
import os
import re
import sys
from statistics import mean, stdev
from typing import Dict, List, Tuple

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
EXPE_FIG_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = os.path.join(EXPE_FIG_DIR, ".mplconfig")

import matplotlib.pyplot as plt

if EXPE_FIG_DIR not in sys.path:
    sys.path.insert(0, EXPE_FIG_DIR)

from algorithm_switches import ALGORITHM_COLORS, ALGORITHM_LABELS, enabled_algorithms  # noqa: E402
from common_plot import (  # noqa: E402
    EXCLUDED_CASES_BY_SCENARIO,
    GRID_LINEWIDTH,
    LABEL_FONT_SIZE,
    RELATIVE_BASELINE_LINEWIDTH,
    TICK_FONT_SIZE,
    FileLogger,
    detect_latest_scenario_root,
    load_full_seed_cases,
    read_csv_dict,
    save_png_and_pdf,
)


def parse_frag(case_base: str) -> float:
    m = re.match(r"^frag(\d+)p(\d+)$", case_base)
    if not m:
        return float("nan")
    return float(f"{m.group(1)}.{m.group(2)}")


def parse_spread_ms(case_base: str) -> float:
    m = re.match(r"^spread(\d+)ms$", case_base)
    if not m:
        return float("nan")
    return float(m.group(1))


def scenario_case_sort(scene: str, cases: List[str]) -> List[str]:
    if scene == "frag":
        return sorted(cases, key=parse_frag)
    if scene == "start_spread":
        return sorted(cases, key=parse_spread_ms)
    if scene == "mix":
        rank = {
            "mix5L": 0,
            "mix10L": 0,
            "mix3L2M1S": 1,
            "mix4L3M3S": 1,
            "mix10S": 2,
            "mix20S": 2,
        }
        return sorted(cases, key=lambda c: (rank.get(c, 99), c))
    if scene == "workload":
        rank = {
            "cdf_fbcoco": 0,
            "cdf_fbcoco_february_2024": 1,
            "cdf_fbcoco_march_2024": 2,
        }
        return sorted(cases, key=lambda c: (rank.get(c, 99), c))
    return sorted(cases)


def case_label(scene: str, case_base: str) -> str:
    if scene == "mix":
        mapping = {
            "mix3L2M1S": "3L2M1S",
            "mix4L3M3S": "4L3M3S",
            "mix5L": "5L",
            "mix10L": "10L",
            "mix10S": "10S",
            "mix20S": "20S",
        }
        return mapping.get(case_base, case_base)
    if scene == "workload":
        mapping = {
            "cdf_fbcoco": "Jan",
            "cdf_fbcoco_february_2024": "Feb",
            "cdf_fbcoco_march_2024": "Mar",
        }
        return mapping.get(case_base, case_base)
    return case_base


def load_scene_table(
    repo_root: str,
    scene: str,
    schedulers: List[str],
    logger: FileLogger,
) -> Tuple[List[str], Dict[str, Dict[str, Tuple[float, float]]]]:
    scenario_root = detect_latest_scenario_root(repo_root, scene)
    excluded = EXCLUDED_CASES_BY_SCENARIO.get(scene, set())
    cases = load_full_seed_cases(scenario_root, min_success_seeds=10, logger=logger)

    table: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for case in cases:
        if case in excluded:
            continue
        case_dir = os.path.join(scenario_root, case)
        if not os.path.isdir(case_dir):
            continue

        per_scheduler_seed_vals: Dict[str, List[float]] = {s: [] for s in schedulers}
        seed_dirs = sorted(
            [
                d
                for d in os.listdir(case_dir)
                if re.match(r"^seed_\d+$", d) and os.path.isdir(os.path.join(case_dir, d))
            ]
        )
        for seed_name in seed_dirs:
            summary_csv = os.path.join(case_dir, seed_name, "summary", "coflow_cct_avg_relative_summary.csv")
            rows = read_csv_dict(summary_csv)
            if not rows:
                continue
            seed_seen = set()
            for r in rows:
                scheduler = (r.get("scheduler") or "").strip()
                if scheduler not in per_scheduler_seed_vals:
                    continue
                if scheduler in seed_seen:
                    continue
                try:
                    avg_cct_ms = float((r.get("avg_cct_ms") or "nan").strip())
                except Exception:
                    continue
                if math.isnan(avg_cct_ms):
                    continue
                per_scheduler_seed_vals[scheduler].append(avg_cct_ms)
                seed_seen.add(scheduler)

        for scheduler in schedulers:
            vals = per_scheduler_seed_vals[scheduler]
            if not vals:
                continue
            mu = mean(vals)
            sigma = stdev(vals) if len(vals) > 1 else 0.0
            table.setdefault(case, {})[scheduler] = (mu, max(0.0, sigma))
            logger.log(
                f"[abs-cct] scene={scene} case={case} scheduler={scheduler} "
                f"seed_count={len(vals)} mean={mu:.6g} std={sigma:.6g}"
            )

    complete_cases = [c for c in cases if c in table and all(s in table[c] for s in schedulers)]
    complete_cases = scenario_case_sort(scene, complete_cases)

    logger.log(f"[load] scene={scene} root={scenario_root}")
    logger.log(f"[load] cases={complete_cases}")
    return complete_cases, table


def style_axes(ax: plt.Axes) -> None:
    ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
    ax.grid(True, axis="y", linestyle="--", linewidth=GRID_LINEWIDTH + 0.5, color="#555555", alpha=0.28)
    ax.set_axisbelow(True)


def plot_self_normalized_trend(
    scene: str,
    cases: List[str],
    table: Dict[str, Dict[str, Tuple[float, float]]],
    schedulers: List[str],
    baseline_case: str,
    xlabel: str,
    out_png: str,
    logger: FileLogger,
    y_min: float = None,
) -> None:
    if baseline_case not in table:
        raise RuntimeError(f"Baseline case not found in {scene}: {baseline_case}")
    dynamic_scheduler = "ocs_eps_preset_dynamic_greedy"
    if dynamic_scheduler not in table[baseline_case]:
        raise RuntimeError(
            f"Hyacinth baseline missing: scene={scene} case={baseline_case} scheduler={dynamic_scheduler}"
        )
    global_base = table[baseline_case][dynamic_scheduler][0]
    if abs(global_base) < 1e-12:
        raise RuntimeError(f"Zero Hyacinth baseline value: scene={scene} case={baseline_case}")

    if scene == "frag":
        x = [parse_frag(c) for c in cases]
        xticklabels = None
    elif scene == "start_spread":
        x = [parse_spread_ms(c) for c in cases]
        xticklabels = None
    else:
        x = list(range(len(cases)))
        xticklabels = [case_label(scene, c) for c in cases]

    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)
    dyn = dynamic_scheduler
    all_y_vals: List[float] = []

    for s in schedulers:
        y_vals: List[float] = []
        for c in cases:
            mean_v, _ = table[c][s]
            y_vals.append(mean_v / global_base)
        all_y_vals.extend(y_vals)
        z = 10 if s == dyn else 3
        ax.plot(
            x,
            y_vals,
            linewidth=2.0,
            marker="o",
            markersize=4.8,
            color=ALGORITHM_COLORS.get(s, "#888888"),
            label=ALGORITHM_LABELS.get(s, s),
            zorder=z,
        )
        logger.log(
            f"[series] scene={scene} scheduler={s} baseline_case={baseline_case} hyacinth_base={global_base:.6g} "
            f"vals={[round(v, 4) for v in y_vals]}"
        )

    ax.axhline(1.0, linestyle="--", linewidth=RELATIVE_BASELINE_LINEWIDTH, color="#444444", alpha=0.85)
    ax.set_xlabel(xlabel, fontsize=LABEL_FONT_SIZE)
    ax.set_ylabel("Norm. Avg CCT", fontsize=LABEL_FONT_SIZE)
    ax.set_xticks(x)
    if xticklabels is not None:
        ax.set_xticklabels(xticklabels)
    style_axes(ax)
    if y_min is not None:
        cur_bottom, cur_top = ax.get_ylim()
        data_min = min(all_y_vals) if all_y_vals else cur_bottom
        data_max = max(all_y_vals) if all_y_vals else cur_top
        if data_min < y_min:
            span = max(1e-9, data_max - data_min)
            target_bottom = max(0.0, data_min - 0.05 * span)
            reason = "auto_lower_for_data"
        else:
            target_bottom = y_min
            reason = "forced_floor"
        ax.set_ylim(target_bottom, max(cur_top, target_bottom + 1e-6))
        logger.log(
            f"[ylim] mode={reason} request={y_min:.6g} data_min={data_min:.6g} "
            f"set_bottom={target_bottom:.6g} original=({cur_bottom:.6g},{cur_top:.6g})"
        )
    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot main trend figures (frag/mix/conflict/workload).")
    parser.add_argument("--out_dir", default="", help="Default: expe_fig/main_trend/figures")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir or os.path.join(SCRIPT_DIR, "figures"))
    os.makedirs(out_dir, exist_ok=True)

    logger = FileLogger(os.path.join(out_dir, "main_trend.log"))
    try:
        schedulers = enabled_algorithms()
        if not schedulers:
            raise RuntimeError("No enabled algorithms. Check algorithm_switches.py")

        repo_root = os.path.abspath(os.path.join(EXPE_FIG_DIR, "..", ".."))
        logger.log(f"[run] repo_root={repo_root}")
        logger.log(f"[run] out_dir={out_dir}")
        logger.log(f"[algorithms] enabled={','.join(schedulers)}")

        frag_cases, frag_table = load_scene_table(repo_root, "frag", schedulers, logger)
        plot_self_normalized_trend(
            scene="frag",
            cases=frag_cases,
            table=frag_table,
            schedulers=schedulers,
            baseline_case="frag0p1",
            xlabel="Fragmentation Ratio (f)",
            out_png=os.path.join(out_dir, "frag_selfnorm_line.png"),
            logger=logger,
            y_min=0.8,
        )

        spread_cases, spread_table = load_scene_table(repo_root, "start_spread", schedulers, logger)
        plot_self_normalized_trend(
            scene="start_spread",
            cases=spread_cases,
            table=spread_table,
            schedulers=schedulers,
            baseline_case="spread0ms",
            xlabel="Concurrency Interval (ms)",
            out_png=os.path.join(out_dir, "conflict_selfnorm_line.png"),
            logger=logger,
            y_min=0.8,
        )

        mix_cases, mix_table = load_scene_table(repo_root, "mix", schedulers, logger)
        if mix_cases:
            plot_self_normalized_trend(
                scene="mix",
                cases=mix_cases,
                table=mix_table,
                schedulers=schedulers,
                baseline_case=mix_cases[0],
                xlabel="Mix Type",
                out_png=os.path.join(out_dir, "mix_selfnorm_line.png"),
                logger=logger,
                y_min=0.8,
            )

        workload_cases, workload_table = load_scene_table(repo_root, "workload", schedulers, logger)
        if workload_cases:
            plot_self_normalized_trend(
                scene="workload",
                cases=workload_cases,
                table=workload_table,
                schedulers=schedulers,
                baseline_case=workload_cases[0],
                xlabel="Workload CDF",
                out_png=os.path.join(out_dir, "workload_selfnorm_line.png"),
                logger=logger,
                y_min=0.8,
            )

        logger.log("[done] main_trend")
    finally:
        logger.close()


if __name__ == "__main__":
    main()
