#!/usr/bin/env python3

import argparse
import csv
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class SeedRunRow:
    case_tag: str
    seed: str
    model_mix: str
    frag: str
    load: str
    nrack: str
    workload: str
    status: str
    run_dir: str


def find_case_dirs(scenario_root: str) -> List[str]:
    out: List[str] = []
    for name in sorted(os.listdir(scenario_root)):
        p = os.path.join(scenario_root, name)
        if not os.path.isdir(p):
            continue
        if name.startswith("_"):
            continue
        has_seed = False
        for sub in os.listdir(p):
            if sub.startswith("seed_") and os.path.isdir(os.path.join(p, sub)):
                has_seed = True
                break
        if has_seed:
            out.append(p)
    return out


def read_kv_meta(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def seed_status_from_manifest(path: str) -> str:
    if not os.path.isfile(path):
        return "failed"
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows or "status" not in (reader.fieldnames or []):
        return "failed"
    for row in rows:
        if str(row.get("status", "")).strip().lower() != "ok":
            return "failed"
    return "ok"


def collect_rows(case_dirs: List[str]) -> List[SeedRunRow]:
    rows: List[SeedRunRow] = []
    seed_dir_pattern = re.compile(r"^seed_(\d+)$")
    for case_dir in case_dirs:
        case_base = os.path.basename(case_dir.rstrip("/"))
        seed_dirs = sorted(
            [
                os.path.join(case_dir, x)
                for x in os.listdir(case_dir)
                if x.startswith("seed_") and os.path.isdir(os.path.join(case_dir, x))
            ]
        )
        for seed_dir in seed_dirs:
            seed_name = os.path.basename(seed_dir)
            m = seed_dir_pattern.match(seed_name)
            if not m:
                continue
            seed = m.group(1)
            summary_dir = os.path.join(seed_dir, "summary")
            meta = read_kv_meta(os.path.join(summary_dir, "run_meta.txt"))
            status = seed_status_from_manifest(os.path.join(summary_dir, "run_manifest.csv"))
            rows.append(
                SeedRunRow(
                    case_tag=f"{case_base}_seed{seed}",
                    seed=seed,
                    model_mix=meta.get("model_mix", ""),
                    frag=meta.get("frag_level", ""),
                    load=meta.get("load", ""),
                    nrack=meta.get("nrack", ""),
                    workload=meta.get("workload", ""),
                    status=status,
                    run_dir=seed_dir,
                )
            )
    return rows


def write_rebuilt_batch(rows: List[SeedRunRow], out_csv: str) -> None:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_tag",
                "seed",
                "model_mix",
                "frag",
                "load",
                "nrack",
                "workload",
                "status",
                "run_dir",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "case_tag": r.case_tag,
                    "seed": r.seed,
                    "model_mix": r.model_mix,
                    "frag": r.frag,
                    "load": r.load,
                    "nrack": r.nrack,
                    "workload": r.workload,
                    "status": r.status,
                    "run_dir": r.run_dir,
                }
            )


def run_aggregate(aggregate_script: str, batch_summary: str, out_dir: str, out_log: str) -> int:
    os.makedirs(os.path.dirname(out_log), exist_ok=True)
    cmd = [
        sys.executable,
        aggregate_script,
        "--batch_summary",
        batch_summary,
        "--out_dir",
        out_dir,
    ]
    with open(out_log, "w", encoding="utf-8") as log_f:
        proc = subprocess.run(cmd, stdout=log_f, stderr=subprocess.STDOUT, check=False)
    return int(proc.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild selected-case batch summary from seed folders and regenerate seed_avg_summary."
    )
    parser.add_argument("--scenario_root", required=True, help="Scenario batch root, e.g. .../batch_..._frag")
    parser.add_argument(
        "--aggregate_script",
        default="",
        help="Path to plot/aggregate_seed_summaries.py (auto-detected if empty).",
    )
    parser.add_argument(
        "--rebuilt_batch_csv",
        default="",
        help="Output rebuilt batch summary CSV path (default: <scenario_root>/batch_summary_rebuilt_selected_cases.csv).",
    )
    parser.add_argument(
        "--aggregate_log",
        default="",
        help="Output aggregation log path (default: <scenario_root>/seed_avg_summary_rebuilt.log).",
    )
    args = parser.parse_args()

    scenario_root = os.path.abspath(args.scenario_root)
    if not os.path.isdir(scenario_root):
        raise RuntimeError(f"Scenario root not found: {scenario_root}")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    aggregate_script = args.aggregate_script or os.path.join(repo_root, "plot", "aggregate_seed_summaries.py")
    if not os.path.isfile(aggregate_script):
        raise RuntimeError(f"aggregate script not found: {aggregate_script}")

    rebuilt_batch_csv = args.rebuilt_batch_csv or os.path.join(scenario_root, "batch_summary_rebuilt_selected_cases.csv")
    aggregate_log = args.aggregate_log or os.path.join(scenario_root, "seed_avg_summary_rebuilt.log")

    case_dirs = find_case_dirs(scenario_root)
    if not case_dirs:
        raise RuntimeError(f"No case dirs with seed_* found under: {scenario_root}")

    rows = collect_rows(case_dirs)
    if not rows:
        raise RuntimeError(f"No seed rows collected under: {scenario_root}")

    ok_cnt = sum(1 for r in rows if r.status == "ok")
    fail_cnt = len(rows) - ok_cnt

    write_rebuilt_batch(rows, rebuilt_batch_csv)
    rc = run_aggregate(aggregate_script, rebuilt_batch_csv, scenario_root, aggregate_log)
    if rc != 0:
        raise RuntimeError(f"aggregate_seed_summaries failed ({rc}), see {aggregate_log}")

    print(f"[rebuild] scenario_root : {scenario_root}")
    print(f"[rebuild] case_count    : {len(case_dirs)}")
    print(f"[rebuild] seed_rows     : {len(rows)}")
    print(f"[rebuild] ok            : {ok_cnt}")
    print(f"[rebuild] failed        : {fail_cnt}")
    print(f"[rebuild] rebuilt_csv   : {rebuilt_batch_csv}")
    print(f"[rebuild] seed_avg_log  : {aggregate_log}")
    print(f"[rebuild] seed_avg_dir  : {os.path.join(scenario_root, 'seed_avg_summary')}")


if __name__ == "__main__":
    main()
