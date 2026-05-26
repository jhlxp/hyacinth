#!/usr/bin/env python3

import argparse
import csv
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")

import matplotlib.pyplot as plt
import numpy as np


SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

DEFAULT_DATASETS = [
    (
        "40 ToRs",
        os.path.join(
            REPO_ROOT,
            "experiments/expe_logs_10round_40tor/frag/"
            "batch_20260510_155035_frag/frag0p1",
        ),
        40,
    ),
    (
        "80 ToRs",
        os.path.join(
            REPO_ROOT,
            "experiments/expe_logs_10round_80tor/frag/"
            "batch_20260422_200323_frag/frag0p1",
        ),
        80,
    ),
]

DEFAULT_SCHEDULERS = [
    ("pure_ocs_pruned", "Optics-pruned", "#4E79A7"),
    ("ocs_eps_global_ksp", "Hybrid-ksp", "#9C755F"),
    ("ocs_eps_preset_dynamic_greedy", "Hyacinth-dynamic", "#000000"),
    ("ocs_eps_pruned", "Hyacinth-pruned", "#FF9900"),
]

PATH_TYPES = [
    "intra-rack",
    "1-hop OCS",
    "2-hop OCS",
    ">=3-hop OCS",
    "direct EPS",
    "OCS-then-EPS",
    "EPS-then-OCS",
    "EPS+multi-OCS",
]

PATH_RE = re.compile(r"(?:^|\s)path=([0-9,]+)")
SEED_RE = re.compile(r"seed_(\d+)")

LABEL_FONT_SIZE = 23
TICK_FONT_SIZE = 21
LEGEND_FONT_SIZE = 17
OUTPUT_DPI = 600


def path_type_key(path_type: str) -> str:
    return (
        path_type.lower()
        .replace(">=", "ge")
        .replace("+", "_")
        .replace(" ", "_")
        .replace("-", "_")
    )


@dataclass(frozen=True)
class SchedulerSpec:
    name: str
    label: str
    color: str


@dataclass(frozen=True)
class DatasetSpec:
    label: str
    case_dir: str
    num_tor: int


@dataclass
class FileMetrics:
    flows: int = 0
    core_flows: int = 0
    bytes_total: float = 0.0
    core_bytes_total: float = 0.0
    total_hops_sum: float = 0.0
    ocs_hops_sum: float = 0.0
    total_hops_core_sum: float = 0.0
    ocs_hops_core_sum: float = 0.0
    total_hops_byte_sum: float = 0.0
    ocs_hops_byte_sum: float = 0.0
    total_hops_core_byte_sum: float = 0.0
    ocs_hops_core_byte_sum: float = 0.0
    eps_flows: int = 0
    eps_core_flows: int = 0
    eps_bytes: float = 0.0
    eps_core_bytes: float = 0.0
    path_type_counts: Counter = None
    path_type_bytes: Counter = None

    def __post_init__(self) -> None:
        if self.path_type_counts is None:
            self.path_type_counts = Counter()
        if self.path_type_bytes is None:
            self.path_type_bytes = Counter()


def parse_scheduler_specs(raw: str) -> List[SchedulerSpec]:
    if not raw:
        return [SchedulerSpec(*x) for x in DEFAULT_SCHEDULERS]
    specs = []
    for item in raw.split(","):
        parts = item.split(":")
        if len(parts) == 1:
            specs.append(SchedulerSpec(parts[0], parts[0], "#777777"))
        elif len(parts) == 2:
            specs.append(SchedulerSpec(parts[0], parts[1], "#777777"))
        else:
            specs.append(SchedulerSpec(parts[0], parts[1], parts[2]))
    return specs


def parse_dataset_specs(raw: str) -> List[DatasetSpec]:
    if not raw:
        return [DatasetSpec(*x) for x in DEFAULT_DATASETS]
    specs = []
    for item in raw.split(","):
        parts = item.split(":")
        if len(parts) != 3:
            raise ValueError(
                "dataset entries must be label:path:num_tor, separated by commas"
            )
        specs.append(DatasetSpec(parts[0], os.path.abspath(parts[1]), int(parts[2])))
    return specs


def parse_path(line: str) -> Optional[List[int]]:
    match = PATH_RE.search(line)
    if not match:
        return None
    path = []
    for token in match.group(1).split(","):
        token = token.strip()
        if token:
            path.append(int(token))
    return path


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
    eps_edges = 0
    for a, b in zip(path, path[1:]):
        if a >= num_tor or b >= num_tor:
            eps_edges += 1
    ocs_hops = total_hops - eps_edges

    if total_hops == 0:
        return total_hops, ocs_hops, False, "intra-rack"
    if not eps_positions:
        if ocs_hops == 1:
            return total_hops, ocs_hops, False, "1-hop OCS"
        if ocs_hops == 2:
            return total_hops, ocs_hops, False, "2-hop OCS"
        return total_hops, ocs_hops, False, ">=3-hop OCS"

    first_eps = eps_positions[0]
    if ocs_hops == 0:
        return total_hops, ocs_hops, True, "direct EPS"
    if ocs_hops == 1:
        if first_eps == 1:
            return total_hops, ocs_hops, True, "EPS-then-OCS"
        return total_hops, ocs_hops, True, "OCS-then-EPS"
    return total_hops, ocs_hops, True, "EPS+multi-OCS"


def read_metrics(path: str, num_tor: int) -> FileMetrics:
    metrics = FileMetrics()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            route = parse_path(line)
            if not route:
                continue
            size = parse_bytes(line)
            total_hops, ocs_hops, uses_eps, path_type = classify_path(route, num_tor)
            core_flow = total_hops > 0

            metrics.flows += 1
            metrics.bytes_total += size
            metrics.total_hops_sum += total_hops
            metrics.ocs_hops_sum += ocs_hops
            metrics.total_hops_byte_sum += total_hops * size
            metrics.ocs_hops_byte_sum += ocs_hops * size
            metrics.path_type_counts[path_type] += 1
            metrics.path_type_bytes[path_type] += size

            if core_flow:
                metrics.core_flows += 1
                metrics.core_bytes_total += size
                metrics.total_hops_core_sum += total_hops
                metrics.ocs_hops_core_sum += ocs_hops
                metrics.total_hops_core_byte_sum += total_hops * size
                metrics.ocs_hops_core_byte_sum += ocs_hops * size

            if uses_eps:
                metrics.eps_flows += 1
                metrics.eps_bytes += size
                if core_flow:
                    metrics.eps_core_flows += 1
                    metrics.eps_core_bytes += size
    return metrics


def safe_div(num: float, den: float) -> float:
    return num / den if den else float("nan")


def metrics_to_row(
    dataset: DatasetSpec,
    scheduler: SchedulerSpec,
    seed: str,
    metrics: FileMetrics,
) -> Dict[str, float]:
    row: Dict[str, float] = {
        "dataset": dataset.label,
        "case_dir": dataset.case_dir,
        "num_tor": dataset.num_tor,
        "seed": seed,
        "scheduler": scheduler.name,
        "label": scheduler.label,
        "flows": metrics.flows,
        "core_flows": metrics.core_flows,
        "bytes": metrics.bytes_total,
        "core_bytes": metrics.core_bytes_total,
        "avg_total_hops_all": safe_div(metrics.total_hops_sum, metrics.flows),
        "avg_ocs_hops_all": safe_div(metrics.ocs_hops_sum, metrics.flows),
        "avg_total_hops_core": safe_div(
            metrics.total_hops_core_sum, metrics.core_flows
        ),
        "avg_ocs_hops_core": safe_div(metrics.ocs_hops_core_sum, metrics.core_flows),
        "avg_total_hops_all_byte": safe_div(
            metrics.total_hops_byte_sum, metrics.bytes_total
        ),
        "avg_ocs_hops_all_byte": safe_div(
            metrics.ocs_hops_byte_sum, metrics.bytes_total
        ),
        "avg_total_hops_core_byte": safe_div(
            metrics.total_hops_core_byte_sum, metrics.core_bytes_total
        ),
        "avg_ocs_hops_core_byte": safe_div(
            metrics.ocs_hops_core_byte_sum, metrics.core_bytes_total
        ),
        "eps_flow_share_all": safe_div(metrics.eps_flows, metrics.flows),
        "eps_flow_share_core": safe_div(metrics.eps_core_flows, metrics.core_flows),
        "eps_byte_share_all": safe_div(metrics.eps_bytes, metrics.bytes_total),
        "eps_byte_share_core": safe_div(
            metrics.eps_core_bytes, metrics.core_bytes_total
        ),
    }
    for path_type in PATH_TYPES:
        key = path_type_key(path_type)
        count = metrics.path_type_counts[path_type]
        byte_count = metrics.path_type_bytes[path_type]
        row[f"{key}_flow_share"] = safe_div(count, metrics.flows)
        row[f"{key}_byte_share"] = safe_div(byte_count, metrics.bytes_total)
    return row


def find_seed_dirs(case_dir: str) -> List[str]:
    if os.path.isdir(os.path.join(case_dir, "transformed_traffic")):
        return [case_dir]
    seed_dirs = []
    for name in sorted(os.listdir(case_dir)):
        path = os.path.join(case_dir, name)
        if name.startswith("seed_") and os.path.isdir(
            os.path.join(path, "transformed_traffic")
        ):
            seed_dirs.append(path)
    return seed_dirs


def seed_name(seed_dir: str) -> str:
    match = SEED_RE.search(os.path.basename(seed_dir))
    return match.group(1) if match else os.path.basename(seed_dir)


def collect_rows(
    datasets: Sequence[DatasetSpec],
    schedulers: Sequence[SchedulerSpec],
) -> List[Dict[str, float]]:
    rows = []
    for dataset in datasets:
        for seed_dir in find_seed_dirs(dataset.case_dir):
            for scheduler in schedulers:
                routed = os.path.join(
                    seed_dir,
                    "transformed_traffic",
                    f"traffic_routed.{scheduler.name}.txt",
                )
                if not os.path.isfile(routed):
                    continue
                metrics = read_metrics(routed, dataset.num_tor)
                rows.append(metrics_to_row(dataset, scheduler, seed_name(seed_dir), metrics))
    return rows


def numeric_values(rows: Iterable[Dict[str, float]], key: str) -> List[float]:
    vals = []
    for row in rows:
        value = row.get(key, float("nan"))
        if isinstance(value, (int, float)) and not math.isnan(float(value)):
            vals.append(float(value))
    return vals


def summarize_rows(
    rows: Sequence[Dict[str, float]],
    datasets: Sequence[DatasetSpec],
    schedulers: Sequence[SchedulerSpec],
) -> List[Dict[str, float]]:
    metric_keys = [
        "flows",
        "core_flows",
        "avg_total_hops_all",
        "avg_ocs_hops_all",
        "avg_total_hops_core",
        "avg_ocs_hops_core",
        "avg_total_hops_all_byte",
        "avg_ocs_hops_all_byte",
        "avg_total_hops_core_byte",
        "avg_ocs_hops_core_byte",
        "eps_flow_share_all",
        "eps_flow_share_core",
        "eps_byte_share_all",
        "eps_byte_share_core",
    ]
    for path_type in PATH_TYPES:
        key = path_type_key(path_type)
        metric_keys.append(f"{key}_flow_share")
        metric_keys.append(f"{key}_byte_share")

    out = []
    for dataset in datasets:
        for scheduler in schedulers:
            selected = [
                row
                for row in rows
                if row["dataset"] == dataset.label and row["scheduler"] == scheduler.name
            ]
            if not selected:
                continue
            summary = {
                "dataset": dataset.label,
                "num_tor": dataset.num_tor,
                "scheduler": scheduler.name,
                "label": scheduler.label,
                "seeds": len(selected),
            }
            for key in metric_keys:
                vals = numeric_values(selected, key)
                summary[f"{key}_mean"] = float(np.mean(vals)) if vals else float("nan")
                summary[f"{key}_std"] = float(np.std(vals, ddof=0)) if vals else float("nan")
            out.append(summary)
    return out


def write_csv(path: str, rows: Sequence[Dict[str, float]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def setup_axes(ax: plt.Axes, ylabel: str) -> None:
    ax.set_ylabel(ylabel, fontsize=LABEL_FONT_SIZE)
    ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
    ax.grid(axis="y", linestyle="--", linewidth=0.8, alpha=0.35)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)


def plot_grouped_metric(
    summaries: Sequence[Dict[str, float]],
    datasets: Sequence[DatasetSpec],
    schedulers: Sequence[SchedulerSpec],
    metric: str,
    ylabel: str,
    out_prefix: str,
    out_dir: str,
    scale: float = 1.0,
) -> None:
    x = np.arange(len(datasets))
    width = min(0.18, 0.8 / max(1, len(schedulers)))
    fig, ax = plt.subplots(figsize=(5.0, 4.0))

    for i, scheduler in enumerate(schedulers):
        vals = []
        errs = []
        for dataset in datasets:
            match = next(
                (
                    row
                    for row in summaries
                    if row["dataset"] == dataset.label
                    and row["scheduler"] == scheduler.name
                ),
                None,
            )
            vals.append(scale * match.get(f"{metric}_mean", float("nan")) if match else float("nan"))
            errs.append(scale * match.get(f"{metric}_std", 0.0) if match else 0.0)
        offset = (i - (len(schedulers) - 1) / 2.0) * width
        ax.bar(
            x + offset,
            vals,
            width,
            yerr=errs,
            capsize=3,
            color=scheduler.color,
            label=scheduler.label,
            linewidth=0.8,
            edgecolor="black",
        )

    ax.set_xticks(x)
    ax.set_xticklabels([d.label for d in datasets])
    setup_axes(ax, ylabel)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.23),
        ncol=2,
        frameon=False,
        fontsize=LEGEND_FONT_SIZE,
        handlelength=1.2,
        columnspacing=0.8,
    )
    fig.tight_layout(pad=0.4)
    for ext in ("pdf", "png"):
        fig.savefig(
            os.path.join(out_dir, f"{out_prefix}.{ext}"),
            dpi=OUTPUT_DPI,
            bbox_inches="tight",
            pad_inches=0.01,
        )
    plt.close(fig)


def plot_path_type_share(
    summaries: Sequence[Dict[str, float]],
    datasets: Sequence[DatasetSpec],
    schedulers: Sequence[SchedulerSpec],
    out_dir: str,
) -> None:
    colors = {
        "intra-rack": "#C7C7C7",
        "1-hop OCS": "#4E79A7",
        "2-hop OCS": "#59A14F",
        ">=3-hop OCS": "#E15759",
        "direct EPS": "#F28E2B",
        "OCS-then-EPS": "#B07AA1",
        "EPS-then-OCS": "#EDC948",
        "EPS+multi-OCS": "#76B7B2",
    }
    labels = []
    records = []
    for dataset in datasets:
        for scheduler in schedulers:
            match = next(
                (
                    row
                    for row in summaries
                    if row["dataset"] == dataset.label
                    and row["scheduler"] == scheduler.name
                ),
                None,
            )
            if match is None:
                continue
            labels.append(f"{dataset.label}\n{scheduler.label}")
            records.append(match)

    x = np.arange(len(records))
    fig_width = max(6.0, 0.62 * len(records))
    fig, ax = plt.subplots(figsize=(fig_width, 4.0))
    bottom = np.zeros(len(records))
    for path_type in PATH_TYPES:
        key = path_type_key(path_type)
        vals = np.array(
            [100.0 * row.get(f"{key}_flow_share_mean", 0.0) for row in records]
        )
        ax.bar(
            x,
            vals,
            bottom=bottom,
            color=colors[path_type],
            edgecolor="white",
            linewidth=0.3,
            label=path_type,
        )
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=14)
    setup_axes(ax, "Flow Share (%)")
    ax.set_ylim(0, 100)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.28),
        ncol=4,
        frameon=False,
        fontsize=13,
        handlelength=1.1,
        columnspacing=0.8,
    )
    fig.tight_layout(pad=0.4)
    for ext in ("pdf", "png"):
        fig.savefig(
            os.path.join(out_dir, f"path_type_share.{ext}"),
            dpi=OUTPUT_DPI,
            bbox_inches="tight",
            pad_inches=0.01,
        )
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute and plot route hop-count statistics from transformed traffic."
    )
    parser.add_argument(
        "--datasets",
        default="",
        help="Comma-separated label:path:num_tor entries. Default uses 40/80 ToR frag0p1.",
    )
    parser.add_argument(
        "--schedulers",
        default="",
        help="Comma-separated name[:label[:color]] entries.",
    )
    parser.add_argument(
        "--out_dir",
        default=os.path.join(SCRIPT_DIR, "figures"),
        help="Output directory.",
    )
    args = parser.parse_args()

    datasets = parse_dataset_specs(args.datasets)
    schedulers = parse_scheduler_specs(args.schedulers)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    rows = collect_rows(datasets, schedulers)
    if not rows:
        raise SystemExit("No routed traffic files found for the requested inputs.")
    summaries = summarize_rows(rows, datasets, schedulers)

    write_csv(os.path.join(out_dir, "hop_count_by_seed.csv"), rows)
    write_csv(os.path.join(out_dir, "hop_count_summary.csv"), summaries)

    plot_grouped_metric(
        summaries,
        datasets,
        schedulers,
        "avg_ocs_hops_core",
        "Avg. OCS Hops",
        "avg_ocs_hops_core",
        out_dir,
    )
    plot_grouped_metric(
        summaries,
        datasets,
        schedulers,
        "avg_total_hops_core",
        "Avg. Total Hops",
        "avg_total_hops_core",
        out_dir,
    )
    plot_grouped_metric(
        summaries,
        datasets,
        schedulers,
        "eps_flow_share_core",
        "EPS Flow Share (%)",
        "eps_flow_share_core",
        out_dir,
        scale=100.0,
    )
    plot_path_type_share(summaries, datasets, schedulers, out_dir)

    print(f"[rows] seed_rows={len(rows)} summary_rows={len(summaries)}")
    print(f"[out] {os.path.join(out_dir, 'hop_count_summary.csv')}")
    print(f"[out] {os.path.join(out_dir, 'avg_ocs_hops_core.pdf')}")


if __name__ == "__main__":
    main()
