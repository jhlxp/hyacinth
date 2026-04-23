#!/usr/bin/env python3

import argparse
import csv
import datetime as dt
import os
import pathlib
import shlex
import subprocess
from typing import Dict, List


ALGO_SPECS = [
    {"scheduler": "ocs_eps_pruned", "topo_key": "eps1", "num_eps": 1},
    {"scheduler": "pure_ocs_ksp", "topo_key": "eps0", "num_eps": 0},
    {"scheduler": "eps_ecmp", "topo_key": "eps8", "num_eps": 8},
    {"scheduler": "pure_ocs_ksp_greedy", "topo_key": "eps0", "num_eps": 0},
    {"scheduler": "pure_ocs_pruned", "topo_key": "eps0", "num_eps": 0},
    {"scheduler": "ocs_eps_large_small", "topo_key": "eps1", "num_eps": 1},
    {"scheduler": "ocs_eps_global_ksp", "topo_key": "eps1", "num_eps": 1},
    {"scheduler": "pure_ocs_3hop_preset", "topo_key": "eps0", "num_eps": 0},
    {"scheduler": "ocs_eps_preset_greedy", "topo_key": "eps1", "num_eps": 1},
    {"scheduler": "ocs_eps_preset_dynamic_greedy", "topo_key": "eps1", "num_eps": 1},
]


def parse_args() -> argparse.Namespace:
    root = pathlib.Path(__file__).resolve().parents[1]
    default_topo_dir = root.parents[0] / "topology"

    parser = argparse.ArgumentParser(
        description="Run 10 schedulers via route_trace_dep_injector and plot solve-time bars."
    )
    parser.add_argument(
        "--injector_bin",
        default=str(root / "bin" / "route_trace_dep_injector"),
        help="Path to route_trace_dep_injector binary.",
    )
    parser.add_argument(
        "--traffic_in",
        default="",
        help="Single trace_dep traffic file shared by all topologies.",
    )
    parser.add_argument(
        "--traffic_eps0",
        default="",
        help="Topology-specific traffic for EPS0 topo (n80_k8_c8_eps0).",
    )
    parser.add_argument(
        "--traffic_eps1",
        default="",
        help="Topology-specific traffic for EPS1 topo (n80_k7_c8_eps1).",
    )
    parser.add_argument(
        "--traffic_eps8",
        default="",
        help="Topology-specific traffic for EPS8 topo (n80_k0_c8_eps8).",
    )

    parser.add_argument(
        "--topo_eps0",
        default=str(default_topo_dir / "n80_k8_c8_eps0.txt"),
        help="Topology for pure OCS algorithms.",
    )
    parser.add_argument(
        "--topo_eps1",
        default=str(default_topo_dir / "n80_k7_c8_eps1.txt"),
        help="Topology for hybrid OCS+EPS algorithms.",
    )
    parser.add_argument(
        "--topo_eps8",
        default=str(default_topo_dir / "n80_k0_c8_eps8.txt"),
        help="Topology for EPS-heavy algorithm.",
    )

    parser.add_argument("--num_tor", type=int, default=80)
    parser.add_argument("--rate_tor_tor", type=float, default=12_500_000_000.0)
    parser.add_argument("--rate_tor_eps", type=float, default=12_500_000_000.0)

    parser.add_argument("--ksp_k", type=int, default=4)
    parser.add_argument("--max_hops", type=int, default=5)
    parser.add_argument("--max_candidates", type=int, default=20)
    parser.add_argument("--small_flow_mode", default="percent")
    parser.add_argument("--small_flow_threshold", type=float, default=90.0)

    parser.add_argument(
        "--schedulers",
        default="",
        help="Optional comma-separated subset of scheduler names.",
    )
    parser.add_argument(
        "--run_dir",
        default="",
        help="Output run directory. Default: plot/runs/run_<timestamp>",
    )
    parser.add_argument("--skip_plot", action="store_true", help="Only run and collect logs; skip plotting.")
    return parser.parse_args()


def ensure_exists(path: pathlib.Path, what: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{what} not found: {path}")


def resolve_specs(selected: str) -> List[Dict[str, object]]:
    if not selected.strip():
        return ALGO_SPECS
    wanted = [x.strip() for x in selected.split(",") if x.strip()]
    wanted_set = set(wanted)
    unknown = wanted_set - {spec["scheduler"] for spec in ALGO_SPECS}
    if unknown:
        raise ValueError(f"Unknown schedulers: {sorted(unknown)}")
    return [spec for spec in ALGO_SPECS if spec["scheduler"] in wanted_set]


def main() -> int:
    args = parse_args()

    injector_bin = pathlib.Path(args.injector_bin).resolve()
    topo_map = {
        "eps0": pathlib.Path(args.topo_eps0).resolve(),
        "eps1": pathlib.Path(args.topo_eps1).resolve(),
        "eps8": pathlib.Path(args.topo_eps8).resolve(),
    }

    ensure_exists(injector_bin, "injector_bin")
    for k, p in topo_map.items():
        ensure_exists(p, f"topology({k})")

    per_topo_mode = bool(args.traffic_eps0 or args.traffic_eps1 or args.traffic_eps8)
    if per_topo_mode:
        if not (args.traffic_eps0 and args.traffic_eps1 and args.traffic_eps8):
            raise ValueError(
                "When using per-topology mode, please set all of "
                "--traffic_eps0/--traffic_eps1/--traffic_eps8."
            )
        traffic_map = {
            "eps0": pathlib.Path(args.traffic_eps0).resolve(),
            "eps1": pathlib.Path(args.traffic_eps1).resolve(),
            "eps8": pathlib.Path(args.traffic_eps8).resolve(),
        }
        for k, p in traffic_map.items():
            ensure_exists(p, f"traffic({k})")
        traffic_desc = "per-topology traffic"
    else:
        if not args.traffic_in:
            raise ValueError(
                "Please set --traffic_in, or provide all "
                "--traffic_eps0/--traffic_eps1/--traffic_eps8."
            )
        common_traffic = pathlib.Path(args.traffic_in).resolve()
        ensure_exists(common_traffic, "traffic_in")
        traffic_map = {"eps0": common_traffic, "eps1": common_traffic, "eps8": common_traffic}
        traffic_desc = str(common_traffic)

    root = pathlib.Path(__file__).resolve().parents[1]
    if args.run_dir:
        run_dir = pathlib.Path(args.run_dir).resolve()
    else:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = (root / "plot" / "runs" / f"run_{ts}").resolve()

    logs_dir = run_dir / "logs"
    routed_dir = run_dir / "routed_traffic"
    summary_dir = run_dir / "summary"
    logs_dir.mkdir(parents=True, exist_ok=True)
    routed_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    specs = resolve_specs(args.schedulers)
    manifest_rows: List[Dict[str, str]] = []
    failed: List[str] = []

    for spec in specs:
        scheduler = str(spec["scheduler"])
        topo_key = str(spec["topo_key"])
        num_eps = int(spec["num_eps"])
        topo_file = topo_map[topo_key]
        traffic_in = traffic_map[topo_key]

        out_traffic = routed_dir / f"traffic_routed.{scheduler}.txt"
        log_file = logs_dir / f"{scheduler}.log"

        cmd = [
            str(injector_bin),
            "--topo_file", str(topo_file),
            "--traffic_in", str(traffic_in),
            "--traffic_out", str(out_traffic),
            "--num_tor", str(args.num_tor),
            "--num_eps", str(num_eps),
            "--rate_tor_tor", str(args.rate_tor_tor),
            "--rate_tor_eps", str(args.rate_tor_eps),
            "--scheduler", scheduler,
            "--ksp_k", str(args.ksp_k),
            "--max_hops", str(args.max_hops),
            "--max_candidates", str(args.max_candidates),
            "--small_flow_mode", str(args.small_flow_mode),
            "--small_flow_threshold", str(args.small_flow_threshold),
        ]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("$ " + " ".join(shlex.quote(x) for x in cmd) + "\n")
            f.write(f"[returncode] {proc.returncode}\n")
            f.write("[stdout]\n")
            f.write(proc.stdout)
            if proc.stdout and not proc.stdout.endswith("\n"):
                f.write("\n")
            f.write("[stderr]\n")
            f.write(proc.stderr)
            if proc.stderr and not proc.stderr.endswith("\n"):
                f.write("\n")

        status = "ok" if proc.returncode == 0 else "failed"
        if status == "failed":
            failed.append(scheduler)

        manifest_rows.append(
            {
                "scheduler": scheduler,
                "topology": str(topo_file),
                "num_eps": str(num_eps),
                "traffic_in": str(traffic_in),
                "traffic_out": str(out_traffic),
                "log_file": str(log_file),
                "status": status,
            }
        )

    manifest_csv = summary_dir / "run_manifest.csv"
    with open(manifest_csv, "w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "scheduler", "topology", "num_eps", "traffic_in", "traffic_out", "log_file", "status"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest_rows:
            writer.writerow(row)

    print(f"[run] run_dir      : {run_dir}")
    print(f"[run] logs_dir     : {logs_dir}")
    print(f"[run] traffic      : {traffic_desc}")
    print(f"[run] manifest_csv : {manifest_csv}")

    if not args.skip_plot:
        plot_script = pathlib.Path(__file__).resolve().parent / "plot_solve_time.py"
        out_csv = summary_dir / "solve_time_summary.csv"
        out_md = summary_dir / "solve_time_summary.md"
        out_png = summary_dir / "solve_time_summary.png"

        plot_cmd = [
            "python3",
            str(plot_script),
            "--log_dir",
            str(logs_dir),
            "--out_csv",
            str(out_csv),
            "--out_md",
            str(out_md),
            "--out_png",
            str(out_png),
        ]
        plot_proc = subprocess.run(plot_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(plot_proc.stdout, end="")
        if plot_proc.returncode != 0:
            print(plot_proc.stderr, end="")
            raise RuntimeError("plot_solve_time.py failed")

    if failed:
        raise RuntimeError(f"Schedulers failed: {failed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
