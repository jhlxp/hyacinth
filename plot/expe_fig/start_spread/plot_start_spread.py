#!/usr/bin/env python3

import argparse
import os
import sys

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
EXPE_FIG_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if EXPE_FIG_DIR not in sys.path:
    sys.path.insert(0, EXPE_FIG_DIR)

from common_plot import detect_latest_scenario_root, run_section


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot section figures for start_spread experiments.")
    parser.add_argument(
        "--scenario_root",
        default="",
        help="Scenario batch root (default: latest start_spread batch).",
    )
    parser.add_argument("--out_dir", default="", help="Output dir (default: expe_fig/start_spread/figures).")
    parser.add_argument("--min_success_seeds", type=int, default=10)
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(EXPE_FIG_DIR, "..", ".."))
    scenario_root = args.scenario_root or detect_latest_scenario_root(repo_root, "start_spread")
    out_dir = args.out_dir or os.path.join(SCRIPT_DIR, "figures")
    run_section(
        exp_name="start_spread",
        section_title="PP1 Start-Spread Sweep",
        scenario_root=os.path.abspath(scenario_root),
        out_dir=os.path.abspath(out_dir),
        min_success_seeds=args.min_success_seeds,
    )


if __name__ == "__main__":
    main()

