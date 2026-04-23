#!/usr/bin/env python3

import argparse
import csv
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt


PP_COLORS = {
    1: "#4E79A7",
    2: "#F28E2B",
    3: "#E15759",
    4: "#76B7B2",
    5: "#59A14F",
    6: "#EDC948",
    7: "#B07AA1",
    8: "#9C755F",
}


@dataclass
class CoflowEvent:
    gid: int
    start_ns: int
    model_id: str
    pp_idx: int
    num_flows: int
    num_src_hosts: int
    num_dst_hosts: int


def parse_pp_groups_hosts(raw: str) -> List[List[int]]:
    groups: List[List[int]] = []
    for token in (raw or "").split("|"):
        token = token.strip()
        if not token:
            continue
        hosts = [int(x) for x in re.findall(r"\d+", token)]
        groups.append(hosts)
    return groups


def load_host_mapping(placement_file: str) -> Tuple[Dict[int, str], Dict[int, int]]:
    host_to_model: Dict[int, str] = {}
    host_to_pp: Dict[int, int] = {}

    with open(placement_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            model_id = (row.get("model_id") or "").strip()
            if not model_id:
                continue
            pp_groups = parse_pp_groups_hosts(row.get("pp_groups_hosts", ""))
            for pp_idx, hosts in enumerate(pp_groups, start=1):
                for h in hosts:
                    if h in host_to_model:
                        raise RuntimeError(
                            f"Host {h} appears in multiple models/PP groups "
                            f"({host_to_model[h]} vs {model_id})"
                        )
                    host_to_model[h] = model_id
                    host_to_pp[h] = pp_idx

    if not host_to_model:
        raise RuntimeError(f"No host mapping loaded from placement file: {placement_file}")
    return host_to_model, host_to_pp


def load_coflow_events(
    traffic_file: str, host_to_model: Dict[int, str], host_to_pp: Dict[int, int]
) -> Tuple[List[CoflowEvent], int]:
    by_gid: Dict[int, Dict[str, object]] = {}
    with open(traffic_file, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            sp = raw.strip().split()
            if not sp:
                continue
            if len(sp) < 5:
                raise RuntimeError(
                    f"Traffic line must have at least 5 columns (src dst bytes start gid), "
                    f"got {len(sp)} at line {line_no}"
                )
            src = int(sp[0])
            dst = int(sp[1])
            start_ns = int(sp[3])
            gid = int(sp[4])

            if gid not in by_gid:
                by_gid[gid] = {
                    "start_ns": start_ns,
                    "src_first": src,
                    "src_set": set([src]),
                    "dst_set": set([dst]),
                    "num_flows": 1,
                }
            else:
                st = by_gid[gid]
                st["start_ns"] = min(int(st["start_ns"]), start_ns)
                st["src_set"].add(src)
                st["dst_set"].add(dst)
                st["num_flows"] = int(st["num_flows"]) + 1

    events: List[CoflowEvent] = []
    unknown_gid = 0
    for gid, st in by_gid.items():
        src_first = int(st["src_first"])
        model_id = host_to_model.get(src_first)
        pp_idx = host_to_pp.get(src_first)

        if model_id is None or pp_idx is None:
            # Fallback: if first src is unknown, try any src in this gid.
            for s in st["src_set"]:
                if s in host_to_model:
                    model_id = host_to_model[s]
                    pp_idx = host_to_pp[s]
                    break

        if model_id is None or pp_idx is None:
            unknown_gid += 1
            continue

        events.append(
            CoflowEvent(
                gid=gid,
                start_ns=int(st["start_ns"]),
                model_id=model_id,
                pp_idx=int(pp_idx),
                num_flows=int(st["num_flows"]),
                num_src_hosts=len(st["src_set"]),
                num_dst_hosts=len(st["dst_set"]),
            )
        )

    events.sort(key=lambda x: (x.start_ns, x.gid))
    return events, unknown_gid


def model_sort_key(model_id: str) -> Tuple[str, int]:
    m = re.match(r"([A-Za-z]+)(\d+)$", model_id)
    if not m:
        return (model_id, 0)
    return (m.group(1), int(m.group(2)))


def write_event_csv(events: List[CoflowEvent], out_csv: str, time_unit: str) -> None:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    fields = [
        "gid",
        f"start_time_{time_unit}",
        "start_ns",
        "model_id",
        "pp_idx",
        "num_flows",
        "num_src_hosts",
        "num_dst_hosts",
    ]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in events:
            if time_unit == "ms":
                t = e.start_ns / 1e6
            else:
                t = e.start_ns / 1e9
            w.writerow(
                {
                    "gid": e.gid,
                    f"start_time_{time_unit}": f"{t:.9f}",
                    "start_ns": e.start_ns,
                    "model_id": e.model_id,
                    "pp_idx": e.pp_idx,
                    "num_flows": e.num_flows,
                    "num_src_hosts": e.num_src_hosts,
                    "num_dst_hosts": e.num_dst_hosts,
                }
            )


def plot_timeline(
    events: List[CoflowEvent],
    out_png: str,
    title: str,
    time_unit: str,
    fig_w: float,
    fig_h: float,
    marker_size: float,
    font_size: float,
    legend_font_size: float,
) -> None:
    models = sorted({e.model_id for e in events}, key=model_sort_key)
    model_to_y = {m: i for i, m in enumerate(models)}
    pp_list = sorted({e.pp_idx for e in events})
    pp_center = (min(pp_list) + max(pp_list)) / 2.0 if pp_list else 1.0

    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), constrained_layout=True)

    for pp in pp_list:
        x_vals: List[float] = []
        y_vals: List[float] = []
        for e in events:
            if e.pp_idx != pp:
                continue
            t = e.start_ns / (1e6 if time_unit == "ms" else 1e9)
            y_base = model_to_y[e.model_id]
            y_vals.append(y_base + 0.06 * (pp - pp_center))
            x_vals.append(t)

        color = PP_COLORS.get(pp, None)
        ax.scatter(
            x_vals,
            y_vals,
            s=marker_size,
            alpha=0.8,
            label=f"PP{pp}",
            color=color,
            edgecolors="none",
        )

    ax.set_yticks([model_to_y[m] for m in models])
    ax.set_yticklabels(models, fontsize=font_size)
    ax.set_xlabel(f"Time ({time_unit})", fontsize=font_size)
    ax.set_ylabel("Model", fontsize=font_size)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.set_title(title, fontsize=font_size + 1)
    ax.tick_params(axis="x", labelsize=font_size)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            ncol=4,
            frameon=False,
            bbox_to_anchor=(0.5, 1.14),
            fontsize=legend_font_size,
        )

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    fig.savefig(out_png, dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot coflow start-time distribution: x=time, y=model, color=PP."
    )
    parser.add_argument("--traffic_file", required=True, help="Input .htsim traffic file.")
    parser.add_argument("--placement_file", required=True, help="Input placement CSV file.")
    parser.add_argument("--out_png", required=True, help="Output PNG path.")
    parser.add_argument("--out_csv", default="", help="Optional event CSV output.")
    parser.add_argument("--title", default="Coflow Start Timeline by Model and PP")
    parser.add_argument("--time_unit", choices=["s", "ms"], default="s")
    parser.add_argument("--fig_w", type=float, default=10.0)
    parser.add_argument("--fig_h", type=float, default=4.0)
    parser.add_argument("--marker_size", type=float, default=26.0)
    parser.add_argument("--font_size", type=float, default=14.0)
    parser.add_argument("--legend_font_size", type=float, default=13.0)
    args = parser.parse_args()

    host_to_model, host_to_pp = load_host_mapping(args.placement_file)
    events, unknown_gid = load_coflow_events(args.traffic_file, host_to_model, host_to_pp)
    if not events:
        raise RuntimeError("No coflow events parsed from traffic file.")

    if args.out_csv:
        write_event_csv(events, args.out_csv, args.time_unit)

    plot_timeline(
        events=events,
        out_png=args.out_png,
        title=args.title,
        time_unit=args.time_unit,
        fig_w=args.fig_w,
        fig_h=args.fig_h,
        marker_size=args.marker_size,
        font_size=args.font_size,
        legend_font_size=args.legend_font_size,
    )

    print(f"[summary] events parsed     : {len(events)}")
    print(f"[summary] unknown gid count : {unknown_gid}")
    if args.out_csv:
        print(f"[summary] csv              : {args.out_csv}")
    print(f"[summary] png              : {args.out_png}")


if __name__ == "__main__":
    main()
