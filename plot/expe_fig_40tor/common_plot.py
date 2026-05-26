#!/usr/bin/env python3

import csv
import glob
import math
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from algorithm_switches import ALGORITHM_COLORS, ALGORITHM_LABELS, PREFERRED_ORDER, enabled_algorithms

LABEL_FONT_SIZE = 22
TICK_FONT_SIZE = 19
LEGEND_FONT_SIZE = 19
ANNOT_FONT_SIZE = 12
OUTPUT_DPI = 600
RELATIVE_BASELINE_LINEWIDTH = 1.1
GRID_LINEWIDTH = 0.9

# Global hardcoded case exclusions for the whole paper.
# key: scenario name under experiments/expe_logs_10round
EXCLUDED_CASES_BY_SCENARIO = {
    "workload": {
        "cdf_fbcoco_january_2024",
    },
}


@dataclass
class MetricBarSpec:
    csv_name: str
    mean_col: str
    std_col: str
    y_label: str
    out_prefix: str
    is_relative: bool
    use_centered_ylim: bool
    force_zero_baseline: bool
    show_value_labels: bool


class FileLogger:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "w", encoding="utf-8")

    def log(self, msg: str) -> None:
        print(msg)
        self.f.write(msg + "\n")
        self.f.flush()

    def close(self) -> None:
        self.f.close()


def derive_pdf_output_path(out_png: str) -> str:
    out_png_abs = os.path.abspath(out_png)
    out_dir = os.path.dirname(out_png_abs)
    out_name = os.path.basename(out_png_abs)
    out_stem, _ = os.path.splitext(out_name)

    # By default, keep PNGs under "figures/" and mirror PDFs under sibling "figures_pdf/".
    if os.path.basename(out_dir) == "figures":
        pdf_dir = os.path.join(os.path.dirname(out_dir), "figures_pdf")
    else:
        pdf_dir = os.path.join(out_dir, "figures_pdf")
    return os.path.join(pdf_dir, f"{out_stem}.pdf")


def save_png_and_pdf(fig: plt.Figure, out_png: str, logger: FileLogger) -> None:
    out_pdf = derive_pdf_output_path(out_png)
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    fig.savefig(out_png, dpi=OUTPUT_DPI, bbox_inches="tight", pad_inches=0.01)
    fig.savefig(out_pdf, dpi=OUTPUT_DPI, bbox_inches="tight", pad_inches=0.01)
    w, h = fig.get_size_inches()
    logger.log(
        f"[save] dpi={OUTPUT_DPI} bbox=tight pad=0.01 figsize_in=({w:.3f},{h:.3f})"
    )
    logger.log(f"[plot] png={out_png}")
    logger.log(f"[plot] pdf={out_pdf}")


def apply_centered_ylim(
    ax: plt.Axes,
    vals: List[float],
    errs: List[float],
    target_index: Optional[int],
    is_relative: bool,
    logger: FileLogger,
    out_png: str,
) -> None:
    if not vals:
        return

    lowers = [v - e for v, e in zip(vals, errs)]
    uppers = [v + e for v, e in zip(vals, errs)]
    if is_relative:
        lowers.append(1.0)
        uppers.append(1.0)

    y_min_raw = min(lowers)
    y_max_raw = max(uppers)
    span = max(1e-9, y_max_raw - y_min_raw)
    pad = 0.08 * span
    y_min = y_min_raw - pad
    y_max = y_max_raw + pad

    # Leave extra room for percentage labels drawn above error-bar tops.
    top_headroom = max(1e-6, 0.16 * span)
    max_upper = max(uppers)

    if target_index is None or target_index < 0 or target_index >= len(vals):
        y0 = max(0.0, y_min)
        y1 = y_max
        y1 = max(y1, max_upper + top_headroom)
        if y1 <= y0:
            y1 = y0 + max(1e-6, 0.1 * max(uppers) if uppers else 1e-6)
        ax.set_ylim(y0, y1)
        return

    center = vals[target_index]
    half_span = max(center - y_min, y_max - center, 1e-6)
    y0 = center - half_span
    y1 = center + half_span
    if y0 < 0.0:
        y0 = 0.0
    y1 = max(y1, max_upper + top_headroom)
    if y1 <= y0:
        y1 = y0 + max(1e-6, 0.1 * max(uppers) if uppers else 1e-6)
    ax.set_ylim(y0, y1)
    logger.log(
        f"[ylim] centered_on_last_algo={center:.6g} range=({y0:.6g},{y1:.6g}) file={os.path.basename(out_png)}"
    )


def apply_regular_ylim(
    ax: plt.Axes,
    vals: List[float],
    errs: List[float],
    is_relative: bool,
    force_zero_baseline: bool,
    logger: FileLogger,
    out_png: str,
) -> None:
    if not vals:
        return
    lowers = [v - e for v, e in zip(vals, errs)]
    uppers = [v + e for v, e in zip(vals, errs)]
    if is_relative:
        lowers.append(1.0)
        uppers.append(1.0)
    y_min_raw = min(lowers)
    y_max_raw = max(uppers)
    span = max(1e-9, y_max_raw - y_min_raw)
    pad = 0.08 * span
    if force_zero_baseline:
        y0 = 0.0
    else:
        y0 = max(0.0, y_min_raw - pad)
    y1 = y_max_raw + pad
    if y1 <= y0:
        y1 = y0 + max(1e-6, 0.1 * max(uppers) if uppers else 1e-6)
    ax.set_ylim(y0, y1)
    logger.log(f"[ylim] regular range=({y0:.6g},{y1:.6g}) file={os.path.basename(out_png)}")


def format_relative_percent(value: float, ref_value: float, is_ref: bool) -> str:
    if is_ref:
        return ""
    if abs(ref_value) < 1e-12:
        return "N/A"
    delta_pct = (value / ref_value - 1.0) * 100.0
    return f"{delta_pct:+.1f}%"


def read_csv_dict(path: str) -> List[Dict[str, str]]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def scheduler_order_key(name: str) -> Tuple[int, str]:
    return (PREFERRED_ORDER.index(name) if name in PREFERRED_ORDER else len(PREFERRED_ORDER), name)


def try_int(x: str, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def try_float(x: str, default: float = float("nan")) -> float:
    try:
        return float(x)
    except Exception:
        return default


def case_sort_key(case_base: str) -> Tuple[int, float, str]:
    # frag0p7
    m = re.match(r"^frag(\d+)p(\d+)$", case_base)
    if m:
        return (1, float(f"{m.group(1)}.{m.group(2)}"), case_base)
    # spread100ms
    m = re.match(r"^spread(\d+)ms$", case_base)
    if m:
        return (2, float(m.group(1)), case_base)
    # n20_mix...
    m = re.match(r"^n(\d+)_", case_base)
    if m:
        return (3, float(m.group(1)), case_base)
    # mix10L / mix20S / mix4L3M3S
    m = re.match(r"^mix(\d+)([A-Za-z].*)?$", case_base)
    if m:
        suffix = m.group(2) or ""
        suffix_rank = {"L": 0, "M": 1, "S": 2}.get(suffix[:1], 9)
        return (4, float(m.group(1)) + 0.01 * suffix_rank, case_base)
    # workload cdf_*
    cdf_rank = {
        "cdf_fbcoco": 0,
        "cdf_fbcoco_january_2024": 1,
        "cdf_fbcoco_february_2024": 2,
        "cdf_fbcoco_march_2024": 3,
    }
    if case_base in cdf_rank:
        return (5, float(cdf_rank[case_base]), case_base)
    return (99, 0.0, case_base)


def detect_latest_scenario_root(repo_root: str, exp_name: str) -> str:
    parent = os.path.join(repo_root, "experiments", "expe_logs_10round_40tor", exp_name)
    candidates = sorted(glob.glob(os.path.join(parent, "batch_*")))
    if not candidates:
        raise RuntimeError(f"No batch_* found under: {parent}")
    return os.path.abspath(candidates[-1])


def load_full_seed_cases(scenario_root: str, min_success_seeds: int, logger: FileLogger) -> List[str]:
    coverage_csv = os.path.join(scenario_root, "seed_avg_summary", "seed_coverage.csv")
    rows = read_csv_dict(coverage_csv)
    if not rows:
        raise RuntimeError(f"Missing/empty seed coverage: {coverage_csv}")

    scenario_name = os.path.basename(os.path.dirname(os.path.abspath(scenario_root)))
    excluded_cases = EXCLUDED_CASES_BY_SCENARIO.get(scenario_name, set())
    if excluded_cases:
        logger.log(
            f"[exclude-hardcoded] scenario={scenario_name} cases={sorted(excluded_cases)}"
        )

    logger.log(f"[coverage] {coverage_csv}")
    full_cases: List[str] = []
    for r in rows:
        case_base = (r.get("case_base") or "").strip()
        ns = try_int((r.get("num_success_seeds") or "").strip(), 0)
        nt = try_int((r.get("num_total_seeds") or "").strip(), 0)
        logger.log(f"[coverage] case={case_base} success={ns}/{nt}")
        if case_base in excluded_cases:
            logger.log(f"[exclude-hardcoded] drop case={case_base}")
            continue
        if ns >= min_success_seeds and nt >= min_success_seeds:
            full_cases.append(case_base)

    full_cases = sorted(set(full_cases), key=case_sort_key)
    logger.log(f"[coverage] min_success_seeds={min_success_seeds}, selected_cases={len(full_cases)}")
    if not full_cases:
        raise RuntimeError("No full-seed cases available after coverage filtering.")
    return full_cases


def plot_grouped_bar(
    rows: List[Dict[str, str]],
    cases: List[str],
    schedulers: List[str],
    mean_col: str,
    std_col: str,
    y_label: str,
    title: str,
    out_png: str,
    is_relative: bool,
    logger: FileLogger,
) -> None:
    pivot: Dict[str, Dict[str, Tuple[float, float]]] = {c: {} for c in cases}
    for r in rows:
        case_base = (r.get("case_base") or "").strip()
        s = (r.get("scheduler") or "").strip()
        if case_base not in pivot or s not in schedulers:
            continue
        pivot[case_base][s] = (
            try_float(r.get(mean_col, ""), float("nan")),
            try_float(r.get(std_col, ""), 0.0),
        )

    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)

    x_base = list(range(len(cases)))
    n_sched = max(1, len(schedulers))
    width = 0.8 / float(n_sched)

    for si, s in enumerate(schedulers):
        x = [v - 0.4 + width * (si + 0.5) for v in x_base]
        y = []
        yerr = []
        miss = 0
        for c in cases:
            pair = pivot[c].get(s)
            if pair is None or math.isnan(pair[0]):
                y.append(float("nan"))
                yerr.append(0.0)
                miss += 1
            else:
                y.append(pair[0])
                yerr.append(max(0.0, pair[1]))
        if miss > 0:
            logger.log(f"[warn] {s}: missing points in {miss}/{len(cases)} cases for {os.path.basename(out_png)}")
        ax.bar(
            x,
            y,
            width=width * 0.95,
            yerr=yerr,
            capsize=2,
            color=ALGORITHM_COLORS.get(s, "#9C9C9C"),
            edgecolor="none",
            label=ALGORITHM_LABELS.get(s, s),
        )

    if is_relative:
        ax.axhline(1.0, linestyle="--", linewidth=RELATIVE_BASELINE_LINEWIDTH, color="#444444", alpha=0.8)

    ax.set_xticks(x_base)
    ax.set_xticklabels(cases, fontsize=TICK_FONT_SIZE)
    ax.set_ylabel(y_label, fontsize=LABEL_FONT_SIZE)
    ax.tick_params(axis="y", labelsize=TICK_FONT_SIZE)
    ax.grid(True, axis="y", linestyle="--", linewidth=GRID_LINEWIDTH, alpha=0.25)
    ax.set_axisbelow(True)
    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def plot_single_case_bar(
    rows: List[Dict[str, str]],
    case_base: str,
    schedulers: List[str],
    mean_col: str,
    std_col: str,
    y_label: str,
    title: str,
    out_png: str,
    is_relative: bool,
    use_centered_ylim: bool,
    force_zero_baseline: bool,
    show_value_labels: bool,
    logger: FileLogger,
) -> None:
    per_sched: Dict[str, Tuple[float, float]] = {}
    for r in rows:
        cb = (r.get("case_base") or "").strip()
        if cb != case_base:
            continue
        s = (r.get("scheduler") or "").strip()
        if s not in schedulers:
            continue
        mv = try_float(r.get(mean_col, ""), float("nan"))
        sv = try_float(r.get(std_col, ""), 0.0)
        if math.isnan(mv):
            continue
        per_sched[s] = (mv, max(0.0, sv))

    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)

    shown_sched: List[str] = []
    vals: List[float] = []
    errs: List[float] = []
    for s in schedulers:
        pair = per_sched.get(s)
        if pair is None:
            logger.log(f"[warn] case={case_base}: missing scheduler={s} in {os.path.basename(out_png)}")
            continue
        shown_sched.append(s)
        vals.append(pair[0])
        errs.append(pair[1])

    if not shown_sched:
        plt.close(fig)
        logger.log(f"[warn] skip empty case bar: {out_png}")
        return

    x = list(range(len(shown_sched)))
    colors = [ALGORITHM_COLORS.get(s, "#9C9C9C") for s in shown_sched]
    ax.bar(x, vals, yerr=errs, capsize=2, color=colors, edgecolor="none", width=0.68)
    if is_relative:
        ax.axhline(1.0, linestyle="--", linewidth=RELATIVE_BASELINE_LINEWIDTH, color="#444444", alpha=0.8)
    target_sched = schedulers[-1] if schedulers else ""
    target_index = shown_sched.index(target_sched) if target_sched in shown_sched else None
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
            force_zero_baseline=force_zero_baseline,
            logger=logger,
            out_png=out_png,
        )
    # Keep bar positions but hide crowded algorithm names on main figures.
    ax.set_xticks([])
    ax.set_ylabel(y_label, fontsize=LABEL_FONT_SIZE)
    ax.tick_params(axis="y", labelsize=TICK_FONT_SIZE)
    ax.grid(True, axis="y", linestyle="--", linewidth=GRID_LINEWIDTH, alpha=0.25)
    ax.set_axisbelow(True)
    if show_value_labels:
        ref_value = vals[target_index] if target_index is not None else vals[-1]
        y_low, y_high = ax.get_ylim()
        y_span = max(1e-9, y_high - y_low)
        text_gap = 0.015 * y_span
        for i, v in enumerate(vals):
            label = format_relative_percent(v, ref_value, is_ref=(target_index is not None and i == target_index))
            if not label:
                continue
            y_text = v + max(0.0, errs[i]) + text_gap
            va = "bottom"
            # Keep labels inside plot area to avoid being clipped by top boundary.
            if y_text > y_high - 0.005 * y_span:
                y_text = y_high - 0.01 * y_span
                va = "top"
            ax.text(i, y_text, label, ha="center", va=va, fontsize=ANNOT_FONT_SIZE)
    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def seed_dir_sort_key(seed_name: str) -> Tuple[int, str]:
    m = re.match(r"^seed_(\d+)$", seed_name)
    if m:
        return (int(m.group(1)), seed_name)
    return (10**9, seed_name)


def load_seed_fct_curve_csv(path: str, schedulers: List[str]) -> Dict[str, List[Tuple[float, float]]]:
    rows = read_csv_dict(path)
    out: Dict[str, List[Tuple[float, float]]] = {s: [] for s in schedulers}
    sched_set = set(schedulers)
    for r in rows:
        s = (r.get("scheduler") or "").strip()
        if s not in sched_set:
            continue
        b = try_float(r.get("bytes", ""), float("nan"))
        f = try_float(r.get("fct_ms", ""), float("nan"))
        if math.isnan(b) or math.isnan(f):
            continue
        out[s].append((b, f))
    for s in schedulers:
        out[s] = sorted(out[s], key=lambda x: x[0])
    return out


def median(vals: List[float]) -> float:
    if not vals:
        return float("nan")
    arr = sorted(vals)
    n = len(arr)
    if n % 2 == 1:
        return arr[n // 2]
    return 0.5 * (arr[n // 2 - 1] + arr[n // 2])


def aggregate_case_fct_curve(
    scenario_root: str,
    case_base: str,
    schedulers: List[str],
    logger: FileLogger,
) -> Dict[str, List[Tuple[float, float, int]]]:
    case_dir = os.path.join(scenario_root, case_base)
    if not os.path.isdir(case_dir):
        logger.log(f"[warn] missing case dir: {case_dir}")
        return {}

    seed_dirs = sorted(
        [
            os.path.join(case_dir, x)
            for x in os.listdir(case_dir)
            if re.match(r"^seed_\d+$", x) and os.path.isdir(os.path.join(case_dir, x))
        ],
        key=lambda p: seed_dir_sort_key(os.path.basename(p)),
    )
    if not seed_dirs:
        logger.log(f"[warn] no seed dirs under case: {case_dir}")
        return {}

    per_sched_seed_curves: Dict[str, List[List[Tuple[float, float]]]] = {s: [] for s in schedulers}

    for sd in seed_dirs:
        curve_csv = os.path.join(sd, "summary", "fct_vs_bytes_curve.csv")
        if not os.path.isfile(curve_csv):
            logger.log(f"[warn] missing seed curve csv: {curve_csv}")
            continue
        seed_curves = load_seed_fct_curve_csv(curve_csv, schedulers=schedulers)
        for s in schedulers:
            if seed_curves[s]:
                per_sched_seed_curves[s].append(seed_curves[s])

    agg: Dict[str, List[Tuple[float, float, int]]] = {}
    for s in schedulers:
        curves = per_sched_seed_curves[s]
        if not curves:
            continue
        min_len = min(len(c) for c in curves)
        if min_len <= 0:
            continue
        points: List[Tuple[float, float, int]] = []
        for i in range(min_len):
            b_vals = [c[i][0] for c in curves]
            f_vals = [c[i][1] for c in curves]
            points.append((median(b_vals), median(f_vals), len(curves)))
        agg[s] = points
        logger.log(
            f"[fct-curve] case={case_base} scheduler={s} seeds={len(curves)} bins={len(points)}"
        )
    return agg


def plot_fct_curve(
    curves: Dict[str, List[Tuple[float, float, int]]],
    schedulers: List[str],
    out_png: str,
    title: str,
    logger: FileLogger,
) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)
    any_curve = False
    for s in schedulers:
        pts = curves.get(s, [])
        if not pts:
            continue
        x = [p[0] for p in pts]
        y = [p[1] for p in pts]
        ax.plot(
            x,
            y,
            linewidth=1.8,
            marker="o",
            markersize=3.0,
            color=ALGORITHM_COLORS.get(s, "#9C9C9C"),
            label=ALGORITHM_LABELS.get(s, s),
        )
        any_curve = True

    if not any_curve:
        plt.close(fig)
        logger.log(f"[warn] skip empty fct curve: {out_png}")
        return

    ax.set_xscale("log")
    ax.set_xlabel("Flow Size (Bytes)", fontsize=LABEL_FONT_SIZE)
    ax.set_ylabel("FCT (ms)", fontsize=LABEL_FONT_SIZE)
    ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
    ax.grid(True, which="both", linestyle="--", linewidth=GRID_LINEWIDTH, alpha=0.25)
    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def plot_algorithm_legend_strip(
    schedulers: List[str],
    out_png: str,
    logger: FileLogger,
) -> None:
    if not schedulers:
        return

    fig_w = max(14.0, 2.4 * len(schedulers))
    fig_h = 1.35
    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), constrained_layout=True)
    ax.axis("off")

    handles = [
        Patch(
            facecolor=ALGORITHM_COLORS.get(s, "#9C9C9C"),
            edgecolor="none",
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
        handlelength=1.6,
        columnspacing=1.4,
        handletextpad=0.5,
    )
    save_png_and_pdf(fig, out_png, logger)
    plt.close(fig)


def run_section(
    exp_name: str,
    section_title: str,
    scenario_root: str,
    out_dir: str,
    min_success_seeds: int = 10,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, f"{exp_name}.log")
    logger = FileLogger(log_path)
    try:
        logger.log(f"[section] exp_name={exp_name}")
        logger.log(f"[section] title={section_title}")
        logger.log(f"[section] scenario_root={scenario_root}")
        logger.log(f"[section] out_dir={out_dir}")

        schedulers = enabled_algorithms()
        if not schedulers:
            raise RuntimeError("No enabled schedulers. Edit algorithm_switches.py")
        logger.log(f"[algorithms] enabled={','.join(schedulers)}")

        expe_fig_root = os.path.dirname(os.path.dirname(os.path.abspath(out_dir)))
        legend_out_png = os.path.join(expe_fig_root, "legend", "figures", "main_algorithms_legend_strip.png")
        plot_algorithm_legend_strip(schedulers=schedulers, out_png=legend_out_png, logger=logger)

        cases = load_full_seed_cases(scenario_root, min_success_seeds=min_success_seeds, logger=logger)
        logger.log(f"[cases] selected={cases}")

        seed_avg_dir = os.path.join(scenario_root, "seed_avg_summary")
        bar_specs = [
            MetricBarSpec(
                csv_name="coflow_cct_avg_relative_seed_avg.csv",
                mean_col="mean_avg_relative_cct_vs_dynamic",
                std_col="std_avg_relative_cct_vs_dynamic",
                y_label="Norm. Avg CCT",
                out_prefix="coflow_cct_avg_relative_seed_avg_bar",
                is_relative=True,
                use_centered_ylim=True,
                force_zero_baseline=False,
                show_value_labels=True,
            ),
            MetricBarSpec(
                csv_name="solve_time_seed_avg.csv",
                mean_col="mean_avg_solve_time_ms",
                std_col="std_avg_solve_time_ms",
                y_label="Avg. Solve Time (ms)",
                out_prefix="solve_time_seed_avg_bar",
                is_relative=False,
                use_centered_ylim=False,
                force_zero_baseline=True,
                show_value_labels=False,
            ),
        ]

        for spec in bar_specs:
            csv_path = os.path.join(seed_avg_dir, spec.csv_name)
            rows = read_csv_dict(csv_path)
            if not rows:
                logger.log(f"[warn] skip missing metric csv: {csv_path}")
                continue
            rows_f = [
                r
                for r in rows
                if (r.get("case_base") or "").strip() in set(cases)
                and (r.get("scheduler") or "").strip() in set(schedulers)
            ]
            if not rows_f:
                logger.log(f"[warn] skip empty metric after filtering: {csv_path}")
                continue
            for case_base in cases:
                out_png = os.path.join(out_dir, f"{spec.out_prefix}_{case_base}.png")
                plot_single_case_bar(
                    rows=rows_f,
                    case_base=case_base,
                    schedulers=schedulers,
                    mean_col=spec.mean_col,
                    std_col=spec.std_col,
                    y_label=spec.y_label,
                    title=f"{section_title}: {spec.y_label} ({case_base}, 10-seed)",
                    out_png=out_png,
                    is_relative=spec.is_relative,
                    use_centered_ylim=spec.use_centered_ylim,
                    force_zero_baseline=spec.force_zero_baseline,
                    show_value_labels=spec.show_value_labels,
                    logger=logger,
                )

        for case_base in cases:
            case_curves = aggregate_case_fct_curve(
                scenario_root=scenario_root,
                case_base=case_base,
                schedulers=schedulers,
                logger=logger,
            )
            out_png = os.path.join(out_dir, f"fct_vs_bytes_curve_10seed_{case_base}.png")
            plot_fct_curve(
                curves=case_curves,
                schedulers=schedulers,
                out_png=out_png,
                title=f"{section_title}: FCT vs Bytes ({case_base}, 10-seed)",
                logger=logger,
            )

        logger.log(f"[done] section={exp_name}")
        logger.log(f"[done] log={log_path}")
    finally:
        logger.close()
