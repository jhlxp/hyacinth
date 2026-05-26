#!/usr/bin/env python3

import argparse
import csv
import glob
import math
import os
import pathlib
from typing import Dict, List, Optional, Tuple

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
    for name in sorted(PREFERRED_BASELINE_ORDER, key=len, reverse=True):
        if name in stem:
            return name
    return stem


def parse_int_token(token: str) -> Optional[int]:
    try:
        return int(token)
    except ValueError:
        pass
    try:
        f = float(token)
    except ValueError:
        return None
    if not math.isfinite(f):
        return None
    rounded = int(round(f))
    if abs(f - rounded) <= 1e-9:
        return rounded
    return None


def extract_group_id(tokens: List[str], fct_idx: int) -> int:
    # flat_dep: dag group task FCT ...
    if fct_idx >= 3:
        maybe_dag = parse_int_token(tokens[fct_idx - 3])
        maybe_group = parse_int_token(tokens[fct_idx - 2])
        maybe_task = parse_int_token(tokens[fct_idx - 1])
        if maybe_dag is not None and maybe_group is not None and maybe_task is not None:
            return maybe_group

    # flat: group FCT ...
    if fct_idx >= 1:
        maybe_group = parse_int_token(tokens[fct_idx - 1])
        if maybe_group is not None:
            return maybe_group

    return -1


def parse_fct_records(log_path: str) -> Tuple[List[Tuple[int, float, float, float]], int]:
    # returns (group_id, start_ms, end_ms, fct_ms), unknown_group_flow_count
    out: List[Tuple[int, float, float, float]] = []
    unknown_group = 0

    with open(log_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or "FCT" not in line:
                continue

            tokens = line.split()
            for i, tok in enumerate(tokens):
                if tok != "FCT":
                    continue
                if i + 5 >= len(tokens):
                    continue
                try:
                    flow_bytes = float(tokens[i + 3])
                    fct_ms = float(tokens[i + 4])
                    start_ms = float(tokens[i + 5])
                except ValueError:
                    continue
                if flow_bytes <= 0.0 or fct_ms < 0.0:
                    continue

                gid = extract_group_id(tokens, i)
                if gid < 0:
                    unknown_group += 1
                out.append((gid, start_ms, start_ms + fct_ms, fct_ms))
                break

    return out, unknown_group


def percentile_label(percentile: float) -> str:
    rounded = int(round(percentile))
    if abs(percentile - rounded) <= 1e-9:
        return str(rounded)
    return f"{percentile:.2f}".rstrip("0").rstrip(".")


def compute_percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    if percentile <= 0.0:
        return min(values)
    if percentile >= 100.0:
        return max(values)

    sorted_vals = sorted(values)
    pos = (percentile / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def compute_coflow_ccts(records: List[Tuple[int, float, float, float]]) -> List[float]:
    # by group id: cct = max(flow_end) - min(flow_start)
    coflow_range: Dict[int, List[float]] = {}
    for gid, start_ms, end_ms, _ in records:
        if gid < 0:
            continue
        if gid not in coflow_range:
            coflow_range[gid] = [start_ms, end_ms]
            continue
        coflow_range[gid][0] = min(coflow_range[gid][0], start_ms)
        coflow_range[gid][1] = max(coflow_range[gid][1], end_ms)

    if not coflow_range:
        return []

    return [max(0.0, v[1] - v[0]) for _, v in coflow_range.items()]


def compute_coflow_percentile_cct(records: List[Tuple[int, float, float, float]], percentile: float) -> Tuple[float, int]:
    ccts = compute_coflow_ccts(records)
    if not ccts:
        return 0.0, 0
    return compute_percentile(ccts, percentile), len(ccts)


def compute_coflow_avg_cct(records: List[Tuple[int, float, float, float]]) -> Tuple[float, int]:
    ccts = compute_coflow_ccts(records)
    if not ccts:
        return 0.0, 0
    return sum(ccts) / float(len(ccts)), len(ccts)


def parse_percentiles_arg(raw: str) -> List[float]:
    vals: List[float] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        vals.append(float(token))
    return vals


def build_scheduler_records(
    paths: List[str], selected: set
) -> Dict[str, Tuple[List[Tuple[int, float, float, float]], int]]:
    scheduler_records: Dict[str, Tuple[List[Tuple[int, float, float, float]], int]] = {}
    for p in paths:
        scheduler = infer_scheduler_from_filename(p)
        if selected and scheduler not in selected:
            continue
        records, unknown_group = parse_fct_records(p)
        if not records:
            continue
        scheduler_records[scheduler] = (records, unknown_group)
    return scheduler_records


def compute_rows_for_percentile(
    scheduler_records: Dict[str, Tuple[List[Tuple[int, float, float, float]], int]],
    percentile: float,
    baseline_scheduler: str,
) -> Tuple[List[Dict[str, str]], float]:
    cct_stat_by_scheduler: Dict[str, float] = {}
    num_coflows_by_scheduler: Dict[str, int] = {}
    unknown_group_by_scheduler: Dict[str, int] = {}

    for scheduler, (records, unknown_group) in scheduler_records.items():
        cct_stat, num_coflows = compute_coflow_percentile_cct(records, percentile)
        if num_coflows <= 0:
            continue
        cct_stat_by_scheduler[scheduler] = cct_stat
        num_coflows_by_scheduler[scheduler] = num_coflows
        unknown_group_by_scheduler[scheduler] = unknown_group

    if not cct_stat_by_scheduler:
        raise RuntimeError(
            "No valid coflow CCT stats parsed from logs. "
            "Check whether FCT lines include coflow/group id."
        )

    if baseline_scheduler not in cct_stat_by_scheduler:
        raise RuntimeError(
            f"Baseline scheduler '{baseline_scheduler}' not found. "
            f"Available: {', '.join(sorted(cct_stat_by_scheduler.keys(), key=scheduler_order_key))}"
        )

    baseline = cct_stat_by_scheduler[baseline_scheduler]
    if baseline <= 0.0:
        raise RuntimeError(f"Baseline CCT statistic is non-positive: {baseline}")

    rows: List[Dict[str, str]] = []
    for scheduler in sorted(cct_stat_by_scheduler.keys(), key=scheduler_order_key):
        cct_stat = cct_stat_by_scheduler[scheduler]
        rel = cct_stat / baseline
        rows.append(
            {
                "scheduler": scheduler,
                "percentile": f"{percentile:.1f}",
                "cct_percentile_ms": f"{cct_stat:.3f}",
                "relative_cct_percentile_vs_dynamic": f"{rel:.3f}",
                # Backward-compatible columns kept for downstream scripts.
                "avg_cct_ms": f"{cct_stat:.3f}",
                "avg_relative_cct_vs_dynamic": f"{rel:.3f}",
                "num_coflows": str(num_coflows_by_scheduler[scheduler]),
                "unknown_group_flows": str(unknown_group_by_scheduler.get(scheduler, 0)),
            }
        )
    return rows, baseline


def compute_rows_for_avg(
    scheduler_records: Dict[str, Tuple[List[Tuple[int, float, float, float]], int]],
    baseline_scheduler: str,
) -> Tuple[List[Dict[str, str]], float]:
    avg_cct_by_scheduler: Dict[str, float] = {}
    num_coflows_by_scheduler: Dict[str, int] = {}
    unknown_group_by_scheduler: Dict[str, int] = {}

    for scheduler, (records, unknown_group) in scheduler_records.items():
        avg_cct, num_coflows = compute_coflow_avg_cct(records)
        if num_coflows <= 0:
            continue
        avg_cct_by_scheduler[scheduler] = avg_cct
        num_coflows_by_scheduler[scheduler] = num_coflows
        unknown_group_by_scheduler[scheduler] = unknown_group

    if not avg_cct_by_scheduler:
        raise RuntimeError(
            "No valid coflow CCT stats parsed from logs. "
            "Check whether FCT lines include coflow/group id."
        )

    if baseline_scheduler not in avg_cct_by_scheduler:
        raise RuntimeError(
            f"Baseline scheduler '{baseline_scheduler}' not found. "
            f"Available: {', '.join(sorted(avg_cct_by_scheduler.keys(), key=scheduler_order_key))}"
        )

    baseline = avg_cct_by_scheduler[baseline_scheduler]
    if baseline <= 0.0:
        raise RuntimeError(f"Baseline avg CCT is non-positive: {baseline}")

    rows: List[Dict[str, str]] = []
    for scheduler in sorted(avg_cct_by_scheduler.keys(), key=scheduler_order_key):
        avg_cct = avg_cct_by_scheduler[scheduler]
        rel = avg_cct / baseline
        rows.append(
            {
                "scheduler": scheduler,
                "percentile": "100.0",
                "cct_percentile_ms": f"{avg_cct:.3f}",
                "relative_cct_percentile_vs_dynamic": f"{rel:.3f}",
                "avg_cct_ms": f"{avg_cct:.3f}",
                "avg_relative_cct_vs_dynamic": f"{rel:.3f}",
                "num_coflows": str(num_coflows_by_scheduler[scheduler]),
                "unknown_group_flows": str(unknown_group_by_scheduler.get(scheduler, 0)),
            }
        )
    return rows, baseline


def resolve_multi_output_paths(out_dir: str, stat_kind: str, percentile: float) -> Tuple[str, str]:
    p_label = percentile_label(percentile)
    if stat_kind == "avg":
        stem = "coflow_cct_avg_relative_summary"
    elif p_label == "100":
        stem = "coflow_p100_relative_summary"
    elif p_label == "99":
        stem = "coflow_p99_relative_summary"
    elif p_label == "95":
        stem = "coflow_p95_relative_summary"
    else:
        stem = f"coflow_p{p_label.replace('.', 'p')}_relative_summary"
    return (
        os.path.join(out_dir, f"{stem}.csv"),
        os.path.join(out_dir, f"{stem}.png"),
    )


def write_rows_csv(rows: List[Dict[str, str]], out_csv: str) -> None:
    fieldnames = [
        "scheduler",
        "percentile",
        "cct_percentile_ms",
        "relative_cct_percentile_vs_dynamic",
        "avg_cct_ms",
        "avg_relative_cct_vs_dynamic",
        "num_coflows",
        "unknown_group_flows",
    ]
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def plot_bar(
    rows: List[Dict[str, str]],
    out_png: str,
    title: str,
    percentile: float,
    stat_kind: str,
) -> None:
    rows_sorted = sorted(rows, key=lambda r: scheduler_order_key(r["scheduler"]))

    schedulers = [r["scheduler"] for r in rows_sorted]
    values = [float(r["relative_cct_percentile_vs_dynamic"]) for r in rows_sorted]
    colors = [ALGORITHM_COLORS.get(s, "#9C9C9C") for s in schedulers]
    labels = [ALGORITHM_ALIASES.get(s, s) for s in schedulers]

    fig, ax = plt.subplots(1, 1, figsize=(10, 4), constrained_layout=True)
    x = list(range(len(schedulers)))
    bars = ax.bar(x, values, color=colors, edgecolor="none")

    ax.axhline(1.0, linestyle="--", linewidth=1.2, color="#444444", alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="center")
    if stat_kind == "avg":
        ax.set_ylabel("Avg Relative Coflow CCT (dynamic=1)")
    else:
        ax.set_ylabel(f"P{percentile_label(percentile)} Relative Coflow CCT (dynamic=1)")
    ax.set_title(title)
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    for rect, val in zip(bars, values):
        ax.text(
            rect.get_x() + rect.get_width() * 0.5,
            val,
            f"{val:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute each coflow CCT (max end - min start in same group), "
            "then take percentile across coflows per scheduler, and plot relative bar."
        )
    )
    parser.add_argument("--sim_log_dir", required=True, help="Directory containing simulator *.log files.")
    parser.add_argument("--log_glob", default="*.log", help="Glob pattern under sim_log_dir (default: *.log).")
    parser.add_argument("--schedulers", default="", help="Optional comma-separated scheduler subset.")
    parser.add_argument(
        "--baseline",
        default="ocs_eps_preset_dynamic_greedy",
        help="Baseline scheduler for normalization (default: ocs_eps_preset_dynamic_greedy).",
    )
    parser.add_argument(
        "--percentile",
        type=float,
        default=100.0,
        help="Coflow CCT percentile in [0,100] (default: 100, i.e., max).",
    )
    parser.add_argument(
        "--percentiles",
        default="",
        help="Optional comma-separated percentile list, e.g. '100,99,95'.",
    )
    parser.add_argument(
        "--emit_triplet",
        action="store_true",
        help="Emit P100/P99/P95 in one call. Requires --out_dir.",
    )
    parser.add_argument(
        "--emit_quad",
        action="store_true",
        help="Emit P100/P99/P95 + AVG(coflow CCT) in one call. Requires --out_dir.",
    )
    parser.add_argument("--out_dir", default="", help="Output directory when generating multiple percentiles.")
    parser.add_argument(
        "--title",
        default="",
        help="Figure title (optional).",
    )
    parser.add_argument(
        "--title_template",
        default="",
        help="Optional title template for multi outputs, use '{p}' as placeholder (P100/P99/P95/AVG).",
    )
    parser.add_argument("--out_png", default="", help="Output PNG path (single-percentile mode).")
    parser.add_argument("--out_csv", default="", help="Optional output CSV path.")
    args = parser.parse_args()

    selected = {x.strip() for x in args.schedulers.split(",") if x.strip()}
    pattern = os.path.join(args.sim_log_dir, args.log_glob)
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise RuntimeError(f"No files matched: {pattern}")
    scheduler_records = build_scheduler_records(paths, selected=selected)
    if not scheduler_records:
        raise RuntimeError("No valid FCT records found from selected schedulers.")

    if args.emit_quad:
        percentiles = [100.0, 99.0, 95.0, 100.0]
        kinds = ["percentile", "percentile", "percentile", "avg"]
    elif args.emit_triplet:
        percentiles = [100.0, 99.0, 95.0]
        kinds = ["percentile", "percentile", "percentile"]
    elif args.percentiles.strip():
        percentiles = parse_percentiles_arg(args.percentiles)
        kinds = ["percentile"] * len(percentiles)
    else:
        percentiles = [args.percentile]
        kinds = ["percentile"]

    if not percentiles:
        raise RuntimeError("No percentile selected.")

    for p in percentiles:
        if p < 0.0 or p > 100.0:
            raise RuntimeError(f"Percentile must be in [0,100], got {p}")

    multi_mode = len(percentiles) > 1
    if multi_mode:
        if not args.out_dir:
            raise RuntimeError("Multi-percentile mode requires --out_dir.")
    else:
        if not args.out_png:
            raise RuntimeError("Single-percentile mode requires --out_png.")

    for p, stat_kind in zip(percentiles, kinds):
        p_label = "AVG" if stat_kind == "avg" else percentile_label(p)
        if multi_mode:
            out_csv, out_png = resolve_multi_output_paths(args.out_dir, stat_kind, p)
        else:
            out_csv = args.out_csv
            out_png = args.out_png

        if args.title_template:
            title = args.title_template.format(p=p_label)
        elif args.title:
            title = args.title
        else:
            if stat_kind == "avg":
                title = "Avg Relative Coflow CCT by Scheduler (dynamic=1)"
            else:
                title = f"P{p_label} Relative Coflow CCT by Scheduler (dynamic=1)"

        if stat_kind == "avg":
            rows, _ = compute_rows_for_avg(
                scheduler_records=scheduler_records,
                baseline_scheduler=args.baseline,
            )
        else:
            rows, _ = compute_rows_for_percentile(
                scheduler_records=scheduler_records,
                percentile=p,
                baseline_scheduler=args.baseline,
            )

        plot_bar(rows, out_png, title, p, stat_kind)
        if out_csv:
            write_rows_csv(rows, out_csv)

        print(f"[summary] baseline : {args.baseline}")
        if stat_kind == "avg":
            print("[summary] stat : AVG(coflow CCT)")
        else:
            print(f"[summary] percentile : P{p_label}")
        print(f"[summary] schedulers: {', '.join([r['scheduler'] for r in rows])}")
        for r in rows:
            print(
                f"[summary] {r['scheduler']}: cct_{'avg' if stat_kind == 'avg' else 'p' + p_label}_ms={r['cct_percentile_ms']}, "
                f"num_coflows={r['num_coflows']}, unknown_group_flows={r['unknown_group_flows']}"
            )
        if out_csv:
            print(f"[summary] csv : {out_csv}")
        print(f"[summary] png : {out_png}")


if __name__ == "__main__":
    main()
