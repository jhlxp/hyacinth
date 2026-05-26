#!/usr/bin/env python3

import argparse
import csv
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")

import matplotlib.pyplot as plt
import numpy as np


SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

DEFAULT_BATCHES = [
    (
        "40 ToRs",
        os.path.join(
            REPO_ROOT,
            "experiments/expe_logs_threshold_sweep/threshold_sweep/"
            "batch_20260524_181615_threshold_sweep",
        ),
        40,
        60,
        os.path.join(
            REPO_ROOT,
            "experiments/expe_logs_10round_40tor/mix/"
            "batch_20260510_155035_mix/mix3L2M1S",
        ),
    ),
    (
        "80 ToRs",
        os.path.join(
            REPO_ROOT,
            "experiments/expe_logs_threshold_sweep/threshold_sweep/"
            "batch_20260524_211104_threshold_sweep_80tor",
        ),
        80,
        30,
        os.path.join(
            REPO_ROOT,
            "experiments/expe_logs_10round_80tor/mix/"
            "batch_20260422_200323_mix/mix4L3M3S",
        ),
    ),
]

THRESHOLDS = [10, 20, 30, 40, 50, 60, 70, 80, 90]
PATH_TYPES = [
    "1-hop OCS",
    "2-hop OCS",
    "3-hop OCS",
    ">3-hop OCS",
    "direct EPS",
    "OCS-then-EPS",
    "EPS-then-OCS",
    "intra-rack",
]
PATH_TYPE_LABELS = {
    "intra-rack": "Intra-rack",
    "1-hop OCS": "1-hop OCS",
    "2-hop OCS": "2-hop OCS",
    "3-hop OCS": "3-hop OCS",
    ">3-hop OCS": ">3-hop OCS",
    "direct EPS": "Direct EPS",
    "OCS-then-EPS": "OCS-then-EPS",
    "EPS-then-OCS": "EPS-then-OCS",
}
PATH_RE = re.compile(r"(?:^|\s)path=([0-9,]+)")

LABEL_FONT_SIZE = 23
X_TICK_FONT_SIZE = 16
Y_TICK_FONT_SIZE = 18
LEGEND_FONT_SIZE = 11
OUTPUT_DPI = 600


def path_type_key(path_type: str) -> str:
    return (
        path_type.lower()
        .replace(">=", "ge")
        .replace(">", "gt")
        .replace("+", "_")
        .replace(" ", "_")
        .replace("-", "_")
    )


@dataclass(frozen=True)
class BatchSpec:
    label: str
    batch_dir: str
    num_tor: int
    best_static_threshold: int
    pure_ocs_case_dir: str = ""


@dataclass
class RunMetrics:
    flows: int = 0
    core_flows: int = 0
    bytes_total: float = 0.0
    core_bytes: float = 0.0
    eps_core_flows: int = 0
    eps_core_bytes: float = 0.0
    total_hops_core_sum: float = 0.0
    ocs_hops_core_sum: float = 0.0
    path_type_counts: Counter = None
    path_type_bytes: Counter = None
    eps_link_bytes: Counter = None
    ocs_link_bytes: Counter = None

    def __post_init__(self) -> None:
        self.path_type_counts = self.path_type_counts or Counter()
        self.path_type_bytes = self.path_type_bytes or Counter()
        self.eps_link_bytes = self.eps_link_bytes or Counter()
        self.ocs_link_bytes = self.ocs_link_bytes or Counter()


def safe_div(num: float, den: float) -> float:
    return num / den if den else float("nan")


def parse_batches(raw: str) -> List[BatchSpec]:
    if not raw:
        return [BatchSpec(*x) for x in DEFAULT_BATCHES]
    batches: List[BatchSpec] = []
    for item in raw.split(","):
        parts = item.split(":")
        if len(parts) not in (4, 5):
            raise ValueError("batch entries must be label:path:num_tor:best_threshold[:pure_ocs_case_dir]")
        pure_dir = os.path.abspath(parts[4]) if len(parts) >= 5 else ""
        batches.append(BatchSpec(parts[0], os.path.abspath(parts[1]), int(parts[2]), int(parts[3]), pure_dir))
    return batches


def parse_path(line: str) -> Optional[List[int]]:
    match = PATH_RE.search(line)
    if not match:
        return None
    return [int(x) for x in match.group(1).split(",") if x.strip()]


def parse_bytes(line: str) -> float:
    parts = line.split()
    if len(parts) < 3:
        return 0.0
    try:
        return float(parts[2])
    except ValueError:
        return 0.0


def classify_path(path: Sequence[int], num_tor: int) -> Tuple[int, int, bool, str]:
    total_hops = max(0, len(path) - 1)
    eps_positions = [i for i, node in enumerate(path) if node >= num_tor]
    eps_edges = sum(1 for a, b in zip(path, path[1:]) if a >= num_tor or b >= num_tor)
    ocs_hops = total_hops - eps_edges

    if total_hops == 0:
        return total_hops, ocs_hops, False, "intra-rack"
    if not eps_positions:
        if ocs_hops == 1:
            return total_hops, ocs_hops, False, "1-hop OCS"
        if ocs_hops == 2:
            return total_hops, ocs_hops, False, "2-hop OCS"
        if ocs_hops == 3:
            return total_hops, ocs_hops, False, "3-hop OCS"
        return total_hops, ocs_hops, False, ">3-hop OCS"

    first_eps = eps_positions[0]
    if ocs_hops == 0:
        return total_hops, ocs_hops, True, "direct EPS"
    if ocs_hops == 1:
        if first_eps == 1:
            return total_hops, ocs_hops, True, "EPS-then-OCS"
        return total_hops, ocs_hops, True, "OCS-then-EPS"
    return total_hops, ocs_hops, True, "EPS+multi-OCS"


def read_run_metrics(path: str, num_tor: int) -> RunMetrics:
    metrics = RunMetrics()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            route = parse_path(line)
            if not route:
                continue
            size = parse_bytes(line)
            total_hops, ocs_hops, uses_eps, path_type = classify_path(route, num_tor)

            metrics.flows += 1
            metrics.bytes_total += size
            metrics.path_type_counts[path_type] += 1
            metrics.path_type_bytes[path_type] += size

            for a, b in zip(route, route[1:]):
                if a >= num_tor or b >= num_tor:
                    metrics.eps_link_bytes[(a, b)] += size
                else:
                    metrics.ocs_link_bytes[(a, b)] += size

            if total_hops > 0:
                metrics.core_flows += 1
                metrics.core_bytes += size
                metrics.total_hops_core_sum += total_hops
                metrics.ocs_hops_core_sum += ocs_hops
                if uses_eps:
                    metrics.eps_core_flows += 1
                    metrics.eps_core_bytes += size
    return metrics


def percentile(values: Sequence[float], pct: float) -> float:
    vals = [v for v in values if not math.isnan(v)]
    if not vals:
        return float("nan")
    return float(np.percentile(vals, pct))


def row_from_metrics(batch: BatchSpec, tag: str, seed: str, metrics: RunMetrics) -> Dict[str, float]:
    row: Dict[str, float] = {
        "dataset": batch.label,
        "num_tor": batch.num_tor,
        "tag": tag,
        "seed": seed,
        "core_flows": metrics.core_flows,
        "core_bytes": metrics.core_bytes,
        "eps_core_flow_share": safe_div(metrics.eps_core_flows, metrics.core_flows),
        "eps_core_byte_share": safe_div(metrics.eps_core_bytes, metrics.core_bytes),
        "avg_total_hops_core": safe_div(metrics.total_hops_core_sum, metrics.core_flows),
        "avg_ocs_hops_core": safe_div(metrics.ocs_hops_core_sum, metrics.core_flows),
        "eps_max_link_gb": max(metrics.eps_link_bytes.values(), default=0.0) / 1e9,
        "eps_mean_active_link_gb": safe_div(sum(metrics.eps_link_bytes.values()) / 1e9, len(metrics.eps_link_bytes)),
        "ocs_max_link_gb": max(metrics.ocs_link_bytes.values(), default=0.0) / 1e9,
        "ocs_p95_link_gb": percentile([v / 1e9 for v in metrics.ocs_link_bytes.values()], 95),
        "ocs_mean_active_link_gb": safe_div(sum(metrics.ocs_link_bytes.values()) / 1e9, len(metrics.ocs_link_bytes)),
    }
    for path_type in PATH_TYPES:
        key = path_type_key(path_type)
        row[f"{key}_flow_share"] = safe_div(metrics.path_type_counts[path_type], metrics.flows)
        row[f"{key}_byte_share"] = safe_div(metrics.path_type_bytes[path_type], metrics.bytes_total)
    return row


def read_cct_relative(batch_dir: str) -> Dict[str, float]:
    path = os.path.join(batch_dir, "seed_avg_summary", "coflow_cct_avg_relative_seed_avg.csv")
    out: Dict[str, float] = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("case_base") != "threshold_sweep":
                continue
            try:
                out[row["scheduler"]] = float(row["mean_avg_relative_cct_vs_dynamic"])
            except (KeyError, ValueError):
                continue
    return out


def collect_rows(batches: Sequence[BatchSpec]) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    for batch in batches:
        cct = read_cct_relative(batch.batch_dir)
        results_dir = os.path.join(batch.batch_dir, "results")
        tags = ["hyacinth_dynamic"]
        tags += [f"hyacinth_preset_t{x}" for x in THRESHOLDS]
        tags += [f"helios_t{x}" for x in THRESHOLDS]
        for tag in tags:
            tag_dir = os.path.join(results_dir, tag)
            if not os.path.isdir(tag_dir):
                continue
            for name in sorted(os.listdir(tag_dir)):
                if not name.startswith("seed_"):
                    continue
                seed = name.replace("seed_", "")
                routed = os.path.join(tag_dir, name, "transformed_traffic", f"traffic_routed.{tag}.txt")
                if not os.path.isfile(routed):
                    continue
                row = row_from_metrics(batch, tag, seed, read_run_metrics(routed, batch.num_tor))
                row["cct_relative_mean"] = cct.get(tag, float("nan"))
                rows.append(row)
        if batch.pure_ocs_case_dir and os.path.isdir(batch.pure_ocs_case_dir):
            case_schedulers = [
                "ocs_eps_pruned",
                "ocs_eps_global_ksp",
                "pure_ocs_ksp",
                "pure_ocs_ksp_greedy",
                "pure_ocs_pruned",
            ]
            for name in sorted(os.listdir(batch.pure_ocs_case_dir)):
                if not name.startswith("seed_"):
                    continue
                seed = name.replace("seed_", "")
                for scheduler in case_schedulers:
                    routed = os.path.join(
                        batch.pure_ocs_case_dir,
                        name,
                        "transformed_traffic",
                        f"traffic_routed.{scheduler}.txt",
                    )
                    if not os.path.isfile(routed):
                        continue
                    row = row_from_metrics(batch, scheduler, seed, read_run_metrics(routed, batch.num_tor))
                    row["cct_relative_mean"] = float("nan")
                    rows.append(row)
    return rows


def summarize(rows: Sequence[Dict[str, float]]) -> List[Dict[str, float]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, float]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["dataset"]), str(row["tag"]))].append(row)

    out: List[Dict[str, float]] = []
    keys = sorted({k for row in rows for k in row.keys() if k not in ("dataset", "tag", "seed")})
    for (dataset, tag), selected in sorted(grouped.items()):
        summary: Dict[str, float] = {"dataset": dataset, "tag": tag, "seeds": len(selected)}
        for key in keys:
            vals = []
            for row in selected:
                val = row.get(key, float("nan"))
                if isinstance(val, (int, float)) and not math.isnan(float(val)):
                    vals.append(float(val))
            summary[f"{key}_mean"] = float(np.mean(vals)) if vals else float("nan")
            summary[f"{key}_std"] = float(np.std(vals, ddof=0)) if vals else float("nan")
        out.append(summary)
    return out


def write_csv(path: str, rows: Sequence[Dict[str, float]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    keys = sorted({k for row in rows for k in row.keys()})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def get_summary(summaries: Sequence[Dict[str, float]], dataset: str, tag: str) -> Optional[Dict[str, float]]:
    return next((r for r in summaries if r["dataset"] == dataset and r["tag"] == tag), None)


def setup_axis(ax: plt.Axes, ylabel: str) -> None:
    ax.set_ylabel(ylabel, fontsize=LABEL_FONT_SIZE)
    ax.tick_params(axis="y", labelsize=Y_TICK_FONT_SIZE)
    ax.tick_params(axis="x", labelsize=X_TICK_FONT_SIZE)
    ax.grid(axis="y", linestyle="--", linewidth=0.8, alpha=0.30)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)


def save_figure(
    fig: plt.Figure,
    out_dir: str,
    stem: str,
    rect: Tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    tight: bool = True,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    if tight:
        fig.tight_layout(pad=0.25, h_pad=3.0, rect=rect)
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(out_dir, f"{stem}.{ext}"), dpi=OUTPUT_DPI, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def reorder_legend_rowwise(handles: Sequence, labels: Sequence[str], ncol: int) -> Tuple[List, List[str]]:
    nitems = len(labels)
    nrows = int(math.ceil(nitems / ncol))
    order = [
        row * ncol + col
        for col in range(ncol)
        for row in range(nrows)
        if row * ncol + col < nitems
    ]
    return [handles[i] for i in order], [labels[i] for i in order]


def plot_path_composition(
    summaries: Sequence[Dict[str, float]],
    batches: Sequence[BatchSpec],
    out_dir: str,
    share_kind: str = "flow",
    out_stem: str = "threshold_path_type_distribution",
) -> None:
    colors = {
        "intra-rack": "#9D9D9D",
        "1-hop OCS": "#4E79A7",
        "2-hop OCS": "#59A14F",
        "3-hop OCS": "#E15759",
        ">3-hop OCS": "#76B7B2",
        "direct EPS": "#F28E2B",
        "OCS-then-EPS": "#B07AA1",
        "EPS-then-OCS": "#EDC948",
        "EPS+multi-OCS": "#76B7B2",
    }
    legend_handles = None
    legend_labels = None

    for batch in batches:
        tags = [
            "ocs_eps_global_ksp",
            "pure_ocs_ksp",
            "hyacinth_preset_t20",
            "helios_t20",
            "hyacinth_dynamic",
            "pure_ocs_ksp_greedy",
            "ocs_eps_pruned",
            "pure_ocs_pruned",
        ]
        labels = [
            "Hybrid-\nKSP",
            "Optics-\nKSP",
            "Hyacinth-\nstatic-20%",
            "Helios-\n20%",
            "Hyacinth-\ndynamic",
            "Optics-\ngreedy",
            "Hyacinth-\npruned",
            "Optics-\npruned",
        ]
        records = [get_summary(summaries, batch.label, tag) for tag in tags]
        x = np.arange(len(tags))
        bottom = np.zeros(len(tags))

        fig, ax = plt.subplots(1, 1, figsize=(10, 4))
        for path_type in PATH_TYPES:
            key = path_type_key(path_type)
            vals = np.array([
                100.0 * rec.get(f"{key}_{share_kind}_share_mean", 0.0) if rec else 0.0
                for rec in records
            ])
            ax.bar(
                x,
                vals,
                width=0.72,
                bottom=bottom,
                color=colors[path_type],
                edgecolor="white",
                linewidth=0.4,
                label=PATH_TYPE_LABELS[path_type],
            )
            bottom += vals
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15, ha="center", fontsize=X_TICK_FONT_SIZE)
        ylabel = "Byte Share (%)" if share_kind == "byte" else "Flow Share (%)"
        setup_axis(ax, ylabel)
        ax.set_ylim(0, 100)

        if legend_handles is None:
            legend_handles, legend_labels = ax.get_legend_handles_labels()

        fig.subplots_adjust(left=0.13, right=0.98, bottom=0.31, top=0.96)
        dataset_key = batch.label.lower().replace(" ", "").replace("tors", "tor")
        save_figure(fig, out_dir, f"{out_stem}_{dataset_key}", tight=False)

    legend_handles, legend_labels = reorder_legend_rowwise(legend_handles, legend_labels, ncol=4)
    legend_fig = plt.figure(figsize=(8.8, 0.9))
    legend_fig.legend(
        legend_handles,
        legend_labels,
        loc="center",
        ncol=4,
        frameon=False,
        fontsize=LEGEND_FONT_SIZE,
        handlelength=1.0,
        columnspacing=1.0,
    )
    save_figure(legend_fig, out_dir, f"{out_stem}_legend", tight=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot EPS bottleneck evidence from threshold-sweep routed traffic.")
    parser.add_argument("--batches", default="", help="Comma-separated label:path:num_tor:best_threshold entries.")
    parser.add_argument("--out_dir", default=os.path.join(SCRIPT_DIR, "eps_bottleneck_figures"))
    args = parser.parse_args()

    batches = parse_batches(args.batches)
    out_dir = os.path.abspath(args.out_dir)

    rows = collect_rows(batches)
    if not rows:
        raise SystemExit("No routed traffic files found.")
    summaries = summarize(rows)
    write_csv(os.path.join(out_dir, "eps_bottleneck_by_seed.csv"), rows)
    write_csv(os.path.join(out_dir, "eps_bottleneck_summary.csv"), summaries)

    plot_path_composition(summaries, batches, out_dir)
    plot_path_composition(
        summaries,
        batches,
        out_dir,
        share_kind="byte",
        out_stem="threshold_path_type_distribution_byte",
    )
    print(f"[rows] seed_rows={len(rows)} summary_rows={len(summaries)}")
    print(f"[out] {out_dir}")


if __name__ == "__main__":
    main()
