#!/usr/bin/env python3

import argparse
import csv
import glob
import math
import os
import pathlib
import statistics
from typing import Dict, List, Tuple

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

ALGORITHM_ALIASES = {
    "ocs_eps_global_ksp": "ocs_eps_global_ksp",
    "pure_ocs_ksp": "pure_ocs_ksp",
    "eps_ecmp": "eps_ecmp",
    "ocs_eps_pruned": "ocs_eps_pruned",
    "ocs_eps_large_small_10pct": "ocs_eps_large_small-10%",
    "ocs_eps_large_small_20pct": "ocs_eps_large_small-20%",
    "ocs_eps_large_small_30pct": "ocs_eps_large_small-30%",
    "pure_ocs_ksp_greedy": "pure_ocs_ksp_greedy",
    "ocs_eps_preset_greedy_10pct": "ocs_eps_preset_greedy-10%",
    "ocs_eps_preset_greedy_20pct": "ocs_eps_preset_greedy-20%",
    "ocs_eps_preset_greedy_30pct": "ocs_eps_preset_greedy-30%",
    "ocs_eps_preset_dynamic_greedy": "ocs_eps_preset_dynamic_greedy",
    "pure_ocs_pruned": "pure_ocs_pruned",
    # legacy keys
    "ocs_eps_large_small": "ocs_eps_large_small",
    "ocs_eps_preset_greedy": "ocs_eps_preset_greedy",
}

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


def scheduler_order_key(name: str) -> Tuple[int, str]:
    return (ORDER_INDEX.get(name, len(PREFERRED_BASELINE_ORDER)), name)


def infer_scheduler_from_filename(path: str) -> str:
    stem = pathlib.Path(path).stem
    # Match longer names first to avoid substring collisions
    # (e.g., pure_ocs_ksp_greedy vs pure_ocs_ksp).
    for name in sorted(PREFERRED_BASELINE_ORDER, key=len, reverse=True):
        if name in stem:
            return name
    return stem


def parse_fct_points(log_path: str) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []

    with open(log_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or "FCT" not in line:
                continue
            toks = line.split()

            for i, tok in enumerate(toks):
                if tok != "FCT":
                    continue
                # Supported FCT tail after token:
                #   src dst bytes fct_ms start_ms
                # This works for both:
                #   FCT ...
                # and
                #   dag group task FCT ...
                if i + 5 >= len(toks):
                    continue
                try:
                    flow_bytes = float(toks[i + 3])
                    fct_ms = float(toks[i + 4])
                except ValueError:
                    continue

                if flow_bytes > 0.0 and fct_ms >= 0.0:
                    points.append((flow_bytes, fct_ms))
                break

    return points


def build_log_bins(vmin: float, vmax: float, bins: int) -> List[float]:
    if bins <= 1 or vmin <= 0.0 or vmax <= 0.0 or vmin == vmax:
        return [vmin, vmax * (1.0 + 1e-12)]

    log_min = math.log10(vmin)
    log_max = math.log10(vmax)
    edges = [10 ** (log_min + (log_max - log_min) * i / bins) for i in range(bins + 1)]
    edges[0] = vmin
    edges[-1] = vmax * (1.0 + 1e-12)
    return edges


def reduce_to_curve(points: List[Tuple[float, float]], bins: int, min_points_per_bin: int) -> List[Tuple[float, float, int]]:
    if not points:
        return []

    pairs = sorted(points, key=lambda x: x[0])
    vmin = pairs[0][0]
    vmax = pairs[-1][0]
    if vmin <= 0.0:
        pos_vals = [b for b, _ in pairs if b > 0.0]
        if not pos_vals:
            return []
        vmin = min(pos_vals)

    edges = build_log_bins(vmin, vmax, bins)
    if len(edges) < 2:
        return []

    out: List[Tuple[float, float, int]] = []
    n = len(pairs)
    idx = 0

    for bi in range(len(edges) - 1):
        lo = edges[bi]
        hi = edges[bi + 1]

        while idx < n and pairs[idx][0] < lo:
            idx += 1

        cur_bytes: List[float] = []
        cur_fcts: List[float] = []
        j = idx
        if bi < len(edges) - 2:
            while j < n and pairs[j][0] < hi:
                cur_bytes.append(pairs[j][0])
                cur_fcts.append(pairs[j][1])
                j += 1
        else:
            while j < n and pairs[j][0] <= hi:
                cur_bytes.append(pairs[j][0])
                cur_fcts.append(pairs[j][1])
                j += 1

        idx = j

        if len(cur_fcts) < min_points_per_bin:
            continue

        x_val = statistics.median(cur_bytes)
        y_val = statistics.median(cur_fcts)
        out.append((x_val, y_val, len(cur_fcts)))

    if not out:
        x_val = statistics.median([p[0] for p in pairs])
        y_val = statistics.median([p[1] for p in pairs])
        out.append((x_val, y_val, len(pairs)))

    return out


def write_curve_csv(rows: List[Dict[str, str]], out_csv: str) -> None:
    fieldnames = ["scheduler", "bytes", "fct_ms", "num_flows_in_bin"]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def plot_curves(curves: Dict[str, List[Tuple[float, float, int]]], out_png: str, title: str, log_x: bool) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(5, 4), constrained_layout=True)

    scheduler_names = sorted(curves.keys(), key=scheduler_order_key)
    dynamic_name = "ocs_eps_preset_dynamic_greedy"
    if dynamic_name in scheduler_names:
        scheduler_names = [s for s in scheduler_names if s != dynamic_name] + [dynamic_name]

    for s in scheduler_names:
        pts = curves[s]
        if not pts:
            continue
        x = [p[0] for p in pts]
        y = [p[1] for p in pts]
        color = ALGORITHM_COLORS.get(s, None)
        label = ALGORITHM_ALIASES.get(s, s)
        z = 10 if s == dynamic_name else 3
        ax.plot(x, y, marker="o", linewidth=2.0, markersize=4.0, label=label, color=color, zorder=z)

    if log_x:
        ax.set_xscale("log")

    ax.set_xlabel("Flow Size (Bytes)")
    ax.set_ylabel("Flow Completion Time (ms)")
    ax.set_title(title)
    ax.grid(True, which="both", linestyle="--", alpha=0.25)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            ncol=2,
            frameon=False,
            bbox_to_anchor=(0.5, 1.28),
        )

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot per-flow size vs completion-time curves from simulator logs."
    )
    parser.add_argument("--sim_log_dir", required=True, help="Directory containing simulator *.log files.")
    parser.add_argument("--log_glob", default="*.log", help="Glob pattern under sim_log_dir (default: *.log).")
    parser.add_argument("--schedulers", default="", help="Optional comma-separated scheduler subset.")
    parser.add_argument("--bins", type=int, default=50, help="Number of log-space bins (default: 50).")
    parser.add_argument("--min_points_per_bin", type=int, default=20, help="Min flows per bin (default: 20).")
    parser.add_argument("--linear_x", action="store_true", help="Use linear x-axis (default is log-scale).")
    parser.add_argument("--title", default="Flow Size vs Completion Time", help="Figure title.")
    parser.add_argument("--out_png", required=True, help="Output PNG path.")
    parser.add_argument("--out_csv", default="", help="Optional output CSV path for curve points.")
    args = parser.parse_args()

    selected = {x.strip() for x in args.schedulers.split(",") if x.strip()}

    pattern = os.path.join(args.sim_log_dir, args.log_glob)
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise RuntimeError(f"No files matched: {pattern}")

    raw_by_scheduler: Dict[str, List[Tuple[float, float]]] = {}
    for p in paths:
        scheduler = infer_scheduler_from_filename(p)
        if selected and scheduler not in selected:
            continue
        pts = parse_fct_points(p)
        if not pts:
            continue
        raw_by_scheduler.setdefault(scheduler, []).extend(pts)

    if not raw_by_scheduler:
        raise RuntimeError("No FCT points found in the provided simulator logs.")

    curves: Dict[str, List[Tuple[float, float, int]]] = {}
    csv_rows: List[Dict[str, str]] = []

    for scheduler, pts in raw_by_scheduler.items():
        curve = reduce_to_curve(pts, bins=max(1, args.bins), min_points_per_bin=max(1, args.min_points_per_bin))
        if not curve:
            continue
        curves[scheduler] = curve
        for b, fct, cnt in curve:
            csv_rows.append(
                {
                    "scheduler": scheduler,
                    "bytes": f"{b:.6f}",
                    "fct_ms": f"{fct:.6f}",
                    "num_flows_in_bin": str(cnt),
                }
            )

    if not curves:
        raise RuntimeError("All parsed schedulers are empty after curve reduction.")

    plot_curves(curves, args.out_png, args.title, log_x=(not args.linear_x))

    if args.out_csv:
        os.makedirs(os.path.dirname(args.out_csv), exist_ok=True)
        write_curve_csv(csv_rows, args.out_csv)

    print(f"[summary] schedulers: {', '.join(sorted(curves.keys(), key=scheduler_order_key))}")
    for s in sorted(curves.keys(), key=scheduler_order_key):
        n_raw = len(raw_by_scheduler[s])
        n_curve = len(curves[s])
        print(f"[summary] {s}: raw_flows={n_raw}, curve_points={n_curve}")
    if args.out_csv:
        print(f"[summary] csv : {args.out_csv}")
    print(f"[summary] png : {args.out_png}")


if __name__ == "__main__":
    main()
