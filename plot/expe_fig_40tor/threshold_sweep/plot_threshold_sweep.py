#!/usr/bin/env python3

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(__file__), ".mplconfig"))
import matplotlib.pyplot as plt


FIG_SIZE = (5, 4)
LABEL_FONT_SIZE = 23
TICK_FONT_SIZE = 21
LEGEND_FONT_SIZE = 19
DPI = 600
THRESHOLDS = [10, 20, 30, 40, 50, 60, 70, 80, 90]
TAG_ORDER = [f"helios_t{x}" for x in THRESHOLDS] + [f"hyacinth_preset_t{x}" for x in THRESHOLDS] + [
    "hyacinth_dynamic"
]
BASELINE_TAG = "hyacinth_dynamic"

SERIES_STYLE = {
    "helios": {
        "label": "Helios",
        "color": "#D64A3A",
        "marker": "o",
    },
    "hyacinth_preset": {
        "label": "Hyacinth-static",
        "color": "#2F6FDB",
        "marker": "s",
    },
    "hyacinth_dynamic": {
        "label": "Hyacinth-dynamic",
        "color": "#111111",
        "marker": "D",
    },
}

METRICS = [
    (
        "fct_relative_seed_avg.csv",
        "mean_avg_relative_fct_vs_dynamic",
        "std_avg_relative_fct_vs_dynamic",
        "Avg Relative FCT",
        "threshold_sweep_fct_relative_seed_avg",
        True,
    ),
    (
        "coflow_cct_avg_relative_seed_avg.csv",
        "mean_avg_relative_cct_vs_dynamic",
        "std_avg_relative_cct_vs_dynamic",
        "Norm. Avg CCT",
        "threshold_sweep_coflow_cct_avg_relative_seed_avg",
        True,
    ),
    (
        "coflow_p95_relative_seed_avg.csv",
        "mean_avg_relative_cct_vs_dynamic",
        "std_avg_relative_cct_vs_dynamic",
        "P95 Relative CCT",
        "threshold_sweep_coflow_p95_relative_seed_avg",
        True,
    ),
    (
        "coflow_p99_relative_seed_avg.csv",
        "mean_avg_relative_cct_vs_dynamic",
        "std_avg_relative_cct_vs_dynamic",
        "P99 Relative CCT",
        "threshold_sweep_coflow_p99_relative_seed_avg",
        True,
    ),
    (
        "coflow_p100_relative_seed_avg.csv",
        "mean_avg_relative_cct_vs_dynamic",
        "std_avg_relative_cct_vs_dynamic",
        "P100 Relative CCT",
        "threshold_sweep_coflow_p100_relative_seed_avg",
        True,
    ),
    (
        "solve_time_seed_avg.csv",
        "mean_avg_solve_time_ms",
        "std_avg_solve_time_ms",
        "Avg Solve Time (ms)",
        "threshold_sweep_solve_time_seed_avg",
        False,
    ),
]


@dataclass
class RunRow:
    scheduler: str
    tag: str
    threshold: str
    seed: str
    status: str
    run_dir: str


def repo_root_from_script() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def read_csv_dict(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def detect_latest_batch(repo_root: str) -> str:
    parent = os.path.join(
        repo_root,
        "experiments",
        "expe_logs_threshold_sweep",
        "threshold_sweep",
    )
    candidates = [
        os.path.join(parent, x)
        for x in sorted(os.listdir(parent))
        if x.startswith("batch_") and os.path.isdir(os.path.join(parent, x))
    ]
    if not candidates:
        raise RuntimeError(f"No threshold-sweep batch found under: {parent}")
    return os.path.abspath(candidates[-1])


def resolve_run_dir(batch_dir: str, row: Dict[str, str], repo_root: str) -> str:
    raw = (row.get("run_dir") or "").strip()
    candidates = []
    if raw:
        candidates.append(raw)
        candidates.append(raw.replace("/home/xuheng/hyacinth", repo_root))
    tag = (row.get("threshold_tag") or "").strip()
    seed = (row.get("seed") or "").strip()
    if tag and seed:
        candidates.append(os.path.join(batch_dir, "results", tag, f"seed_{seed}"))
    for p in candidates:
        if p and os.path.isdir(p):
            return os.path.abspath(p)
    return os.path.abspath(candidates[-1]) if candidates else ""


def load_runs(batch_dir: str, repo_root: str) -> List[RunRow]:
    batch_summary = os.path.join(batch_dir, "batch_summary.csv")
    rows = read_csv_dict(batch_summary)
    out: List[RunRow] = []
    for r in rows:
        out.append(
            RunRow(
                scheduler=(r.get("scheduler") or "").strip(),
                tag=(r.get("threshold_tag") or "").strip(),
                threshold=(r.get("threshold_pct") or "").strip(),
                seed=(r.get("seed") or "").strip(),
                status=(r.get("status") or "").strip().lower(),
                run_dir=resolve_run_dir(batch_dir, r, repo_root),
            )
        )
    return out


def run_cmd(cmd: List[str], log_path: str, env: Dict[str, str]) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log_f:
        proc = subprocess.run(cmd, stdout=log_f, stderr=subprocess.STDOUT, check=False, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}), see {log_path}: {' '.join(cmd)}")


def copy_log(src: str, dst: str) -> bool:
    if not os.path.isfile(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def tag_sort_key(tag: str) -> Tuple[int, str]:
    if tag in TAG_ORDER:
        return (TAG_ORDER.index(tag), tag)
    return (len(TAG_ORDER), tag)


def build_per_seed_summaries(batch_dir: str, runs: List[RunRow], repo_root: str) -> List[str]:
    plot_dir = os.path.join(repo_root, "plot")
    plot_solve_time = os.path.join(plot_dir, "plot_solve_time.py")
    plot_fct_bytes = os.path.join(plot_dir, "plot_fct_vs_bytes.py")
    plot_fct_rel = os.path.join(plot_dir, "plot_fct_avg_relative_bar.py")
    plot_coflow_rel = os.path.join(plot_dir, "plot_coflow_avg_relative_bar.py")

    by_seed: Dict[str, List[RunRow]] = {}
    for r in runs:
        if r.status == "ok" and r.tag and r.seed:
            by_seed.setdefault(r.seed, []).append(r)

    env = os.environ.copy()
    env["MPLCONFIGDIR"] = os.path.join(batch_dir, ".mplconfig")
    os.makedirs(env["MPLCONFIGDIR"], exist_ok=True)

    good_seeds: List[str] = []
    for seed in sorted(by_seed.keys(), key=lambda x: int(x)):
        seed_runs = sorted(by_seed[seed], key=lambda r: tag_sort_key(r.tag))
        seed_tags: List[str] = []
        sim_dir = os.path.join(batch_dir, f"sim_logs_seed{seed}")
        route_dir = os.path.join(batch_dir, f"route_logs_seed{seed}")
        summary_dir = os.path.join(batch_dir, f"plots_seed{seed}")
        os.makedirs(sim_dir, exist_ok=True)
        os.makedirs(route_dir, exist_ok=True)
        os.makedirs(summary_dir, exist_ok=True)

        for r in seed_runs:
            sim_src = os.path.join(r.run_dir, "sim_logs", f"{r.tag}.log")
            route_src = os.path.join(r.run_dir, "route_logs", f"{r.tag}.log")
            sim_ok = copy_log(sim_src, os.path.join(sim_dir, f"{r.tag}.log"))
            copy_log(route_src, os.path.join(route_dir, f"{r.tag}.log"))
            if sim_ok:
                seed_tags.append(r.tag)

        seed_tags = sorted(set(seed_tags), key=tag_sort_key)
        if len(seed_tags) < 2 or BASELINE_TAG not in seed_tags:
            continue
        sched_csv = ",".join(seed_tags)

        run_cmd(
            [
                sys.executable,
                plot_solve_time,
                "--log_dir",
                route_dir,
                "--out_csv",
                os.path.join(summary_dir, "solve_time_summary.csv"),
                "--out_md",
                os.path.join(summary_dir, "solve_time_summary.md"),
                "--out_png",
                os.path.join(summary_dir, "solve_time_summary.png"),
            ],
            os.path.join(summary_dir, "plot_solve_time.log"),
            env,
        )
        run_cmd(
            [
                sys.executable,
                plot_fct_bytes,
                "--sim_log_dir",
                sim_dir,
                "--log_glob",
                "*.log",
                "--schedulers",
                sched_csv,
                "--title",
                f"Flow Size vs Completion Time (Threshold Sweep seed={seed})",
                "--out_csv",
                os.path.join(summary_dir, "fct_vs_bytes_curve.csv"),
                "--out_png",
                os.path.join(summary_dir, "fct_vs_bytes_curve.png"),
            ],
            os.path.join(summary_dir, "plot_fct_vs_bytes.log"),
            env,
        )
        run_cmd(
            [
                sys.executable,
                plot_fct_rel,
                "--curve_csv",
                os.path.join(summary_dir, "fct_vs_bytes_curve.csv"),
                "--schedulers",
                sched_csv,
                "--baseline",
                BASELINE_TAG,
                "--title",
                f"Avg Relative FCT vs Dynamic (Threshold Sweep seed={seed})",
                "--out_csv",
                os.path.join(summary_dir, "fct_avg_relative_summary.csv"),
                "--out_png",
                os.path.join(summary_dir, "fct_avg_relative_summary.png"),
            ],
            os.path.join(summary_dir, "plot_fct_avg_rel.log"),
            env,
        )
        run_cmd(
            [
                sys.executable,
                plot_coflow_rel,
                "--sim_log_dir",
                sim_dir,
                "--log_glob",
                "*.log",
                "--schedulers",
                sched_csv,
                "--baseline",
                BASELINE_TAG,
                "--emit_quad",
                "--out_dir",
                summary_dir,
                "--title_template",
                f"{{p}} Relative CCT vs Dynamic (Threshold Sweep seed={seed})",
            ],
            os.path.join(summary_dir, "plot_coflow_avg_rel.log"),
            env,
        )
        good_seeds.append(seed)
    return good_seeds


def build_rollup(batch_dir: str, seeds: List[str]) -> str:
    rollup_root = os.path.join(batch_dir, "_threshold_seed_rollup", "threshold_sweep")
    rows: List[Dict[str, str]] = []
    required = [
        "solve_time_summary.csv",
        "fct_avg_relative_summary.csv",
        "coflow_p100_relative_summary.csv",
        "coflow_p99_relative_summary.csv",
        "coflow_p95_relative_summary.csv",
        "coflow_cct_avg_relative_summary.csv",
    ]
    for seed in sorted(seeds, key=lambda x: int(x)):
        src = os.path.join(batch_dir, f"plots_seed{seed}")
        dst_seed = os.path.join(rollup_root, f"seed_{seed}")
        dst_summary = os.path.join(dst_seed, "summary")
        os.makedirs(dst_summary, exist_ok=True)
        missing = [name for name in required if not os.path.isfile(os.path.join(src, name))]
        if missing:
            continue
        for name in required:
            if name == "solve_time_summary.csv":
                normalize_solve_time_by_tag(
                    os.path.join(src, name),
                    os.path.join(dst_summary, name),
                )
            else:
                shutil.copy2(os.path.join(src, name), os.path.join(dst_summary, name))
        rows.append(
            {
                "case_tag": f"threshold_sweep_seed{seed}",
                "seed": seed,
                "model_mix": "3L,2M,1S",
                "frag": "0.5",
                "load": "0.5",
                "nrack": "40",
                "workload": "fbcoco",
                "status": "ok",
                "run_dir": dst_seed,
            }
        )

    if not rows:
        raise RuntimeError("No complete per-seed threshold summaries were available for rollup.")

    pseudo_batch = os.path.join(batch_dir, "batch_summary_rebuilt_threshold_seed_rollup.csv")
    write_csv(
        pseudo_batch,
        ["case_tag", "seed", "model_mix", "frag", "load", "nrack", "workload", "status", "run_dir"],
        rows,
    )
    return pseudo_batch


def normalize_solve_time_by_tag(src_csv: str, dst_csv: str) -> None:
    rows = read_csv_dict(src_csv)
    out_rows: List[Dict[str, str]] = []
    for r in rows:
        log_file = (r.get("log_file") or "").strip()
        tag = os.path.splitext(os.path.basename(log_file))[0]
        if tag not in TAG_ORDER:
            tag = (r.get("scheduler") or "").strip()
        out = dict(r)
        out["scheduler"] = tag
        out_rows.append(out)
    write_csv(
        dst_csv,
        [
            "scheduler",
            "avg_solve_time_ms",
            "solve_time_ms",
            "num_solve_calls",
            "topo_file",
            "traffic_in",
            "traffic_out",
            "log_file",
        ],
        out_rows,
    )


def run_seed_aggregate(batch_dir: str, pseudo_batch: str, repo_root: str) -> None:
    aggregate_script = os.path.join(repo_root, "plot", "aggregate_seed_summaries.py")
    log_path = os.path.join(batch_dir, "seed_avg_summary_threshold_rollup.log")
    run_cmd(
        [sys.executable, aggregate_script, "--batch_summary", pseudo_batch, "--out_dir", batch_dir],
        log_path,
        os.environ.copy(),
    )


def parse_threshold_tag(tag: str) -> Tuple[Optional[str], Optional[int]]:
    m = re.match(r"^helios_t(\d+)$", tag)
    if m:
        return "helios", int(m.group(1))
    m = re.match(r"^hyacinth_preset_t(\d+)$", tag)
    if m:
        return "hyacinth_preset", int(m.group(1))
    if tag == "hyacinth_dynamic":
        return "hyacinth_dynamic", None
    return None, None


def safe_float(x: str, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def save_pdf(fig: plt.Figure, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.tight_layout(pad=0.2)
    out_pdf = os.path.splitext(out_path)[0] + ".pdf"
    fig.savefig(out_pdf, dpi=DPI, bbox_inches="tight", pad_inches=0.04)


def plot_threshold_lines(seed_avg_dir: str) -> None:
    for csv_name, mean_col, std_col, ylabel, out_stem, relative in METRICS:
        path = os.path.join(seed_avg_dir, csv_name)
        if not os.path.isfile(path):
            continue
        rows = read_csv_dict(path)
        series: Dict[str, Dict[int, Tuple[float, float, int]]] = {"helios": {}, "hyacinth_preset": {}}
        dynamic: Optional[Tuple[float, float, int]] = None
        for r in rows:
            if (r.get("case_base") or "") != "threshold_sweep":
                continue
            tag = (r.get("scheduler") or "").strip()
            family, threshold = parse_threshold_tag(tag)
            mean_v = safe_float(r.get(mean_col, ""), 0.0)
            std_v = safe_float(r.get(std_col, ""), 0.0)
            seed_count = int(safe_float(r.get("seed_count", ""), 0.0))
            if family in ("helios", "hyacinth_preset") and threshold is not None:
                series[family][threshold] = (mean_v, std_v, seed_count)
            elif family == "hyacinth_dynamic":
                dynamic = (mean_v, std_v, seed_count)

        if not series["helios"] and not series["hyacinth_preset"] and dynamic is None:
            continue

        fig, ax = plt.subplots(1, 1, figsize=FIG_SIZE)
        for family in ("helios", "hyacinth_preset"):
            pts = [(t, series[family][t]) for t in THRESHOLDS if t in series[family]]
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1][0] for p in pts]
            es = [p[1][1] for p in pts]
            style = SERIES_STYLE[family]
            ax.errorbar(
                xs,
                ys,
                yerr=es,
                marker=style["marker"],
                linewidth=2.0,
                markersize=5.0,
                capsize=3,
                color=style["color"],
                label=style["label"],
            )
        if dynamic is not None:
            style = SERIES_STYLE["hyacinth_dynamic"]
            ax.axhline(dynamic[0], linestyle="--", linewidth=1.6, color=style["color"], label=style["label"])
            ax.fill_between(
                THRESHOLDS,
                [dynamic[0] - dynamic[1]] * len(THRESHOLDS),
                [dynamic[0] + dynamic[1]] * len(THRESHOLDS),
                color=style["color"],
                alpha=0.08,
                linewidth=0,
            )
        if relative:
            ax.axhline(1.0, linestyle=":", linewidth=1.0, color="#555555", alpha=0.7)
        ax.set_xticks(THRESHOLDS[::2])
        ax.set_xlabel("EPS Threshold (%)", fontsize=LABEL_FONT_SIZE)
        ax.set_ylabel(ylabel, fontsize=LABEL_FONT_SIZE)
        ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
        ax.grid(True, axis="y", linestyle="--", linewidth=0.8, alpha=0.25)
        ax.set_axisbelow(True)
        handles, labels = ax.get_legend_handles_labels()
        legend_order = ["Hyacinth-dynamic", "Hyacinth-static", "Helios"]
        ordered = [
            (handles[labels.index(label)], label)
            for label in legend_order
            if label in labels
        ]
        if ordered:
            handles, labels = zip(*ordered)
        legend_kwargs = dict(
            frameon=False,
            fontsize=LEGEND_FONT_SIZE,
            handlelength=1.15,
            handletextpad=0.35,
            labelspacing=0.15,
            borderaxespad=0.10,
        )
        if "threshold_sweep_80tor" in seed_avg_dir:
            ax.legend(handles, labels, loc="best", **legend_kwargs)
        else:
            ax.legend(handles, labels, loc="upper right", bbox_to_anchor=(1.0, 1.0), **legend_kwargs)
        save_pdf(fig, os.path.join(seed_avg_dir, f"{out_stem}.pdf"))
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild and plot 40-rack threshold-sweep seed averages.")
    parser.add_argument("--batch_dir", default="", help="Threshold-sweep batch dir; default is latest.")
    args = parser.parse_args()

    repo_root = repo_root_from_script()
    batch_dir = os.path.abspath(args.batch_dir or detect_latest_batch(repo_root))
    if not os.path.isdir(batch_dir):
        raise RuntimeError(f"batch dir not found: {batch_dir}")

    runs = load_runs(batch_dir, repo_root)
    seeds = build_per_seed_summaries(batch_dir, runs, repo_root)
    pseudo_batch = build_rollup(batch_dir, seeds)
    run_seed_aggregate(batch_dir, pseudo_batch, repo_root)
    plot_threshold_lines(os.path.join(batch_dir, "seed_avg_summary"))

    print(f"[ok] batch_dir        : {batch_dir}")
    print(f"[ok] per-seed summaries: {len(seeds)} seeds")
    print(f"[ok] pseudo batch csv : {pseudo_batch}")
    print(f"[ok] seed_avg_summary: {os.path.join(batch_dir, 'seed_avg_summary')}")


if __name__ == "__main__":
    main()
