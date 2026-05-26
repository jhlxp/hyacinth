#!/usr/bin/env python3

import csv
import os
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt


SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
LABEL_FONT_SIZE = 23
TICK_FONT_SIZE = 21
LEGEND_FONT_SIZE = 19

SCHEDULERS = [
    ("ocs_eps_preset_dynamic_greedy", "Hyacinth-dynamic", "#000000"),
    ("ocs_eps_pruned", "Hyacinth-pruned", "#FF9900"),
    ("pure_ocs_pruned", "Optics-pruned", "#3DB19E"),
]

PLOTS = [
    {
        "name": "2560nodes",
        "cases": [
            ("mix10S", "Small"),
            ("mix3L2M1S", "Mix"),
            ("mix5L", "Large"),
        ],
        "data": {
            ("mix10S", "ocs_eps_preset_dynamic_greedy"): 0.162,
            ("mix10S", "ocs_eps_pruned"): 0.214,
            ("mix10S", "pure_ocs_pruned"): 0.298,
            ("mix3L2M1S", "ocs_eps_preset_dynamic_greedy"): 0.329,
            ("mix3L2M1S", "ocs_eps_pruned"): 0.479,
            ("mix3L2M1S", "pure_ocs_pruned"): 0.623,
            ("mix5L", "ocs_eps_preset_dynamic_greedy"): 0.495,
            ("mix5L", "ocs_eps_pruned"): 0.618,
            ("mix5L", "pure_ocs_pruned"): 0.996,
        },
    },
    {
        "name": "5120nodes",
        "cases": [
            ("mix20S", "Small"),
            ("mix4L3M3S", "Mix"),
            ("mix10L", "Large"),
        ],
        "data": {
            ("mix20S", "ocs_eps_preset_dynamic_greedy"): 0.112,
            ("mix20S", "ocs_eps_pruned"): 0.349,
            ("mix20S", "pure_ocs_pruned"): 0.674,
            ("mix4L3M3S", "ocs_eps_preset_dynamic_greedy"): 0.257,
            ("mix4L3M3S", "ocs_eps_pruned"): 0.621,
            ("mix4L3M3S", "pure_ocs_pruned"): 0.984,
            ("mix10L", "ocs_eps_preset_dynamic_greedy"): 0.333,
            ("mix10L", "ocs_eps_pruned"): 0.988,
            ("mix10L", "pure_ocs_pruned"): 1.462,
        },
    },
]


def write_used_csv(
    plot_name: str,
    cases: List[Tuple[str, str]],
    data: Dict[Tuple[str, str], float],
) -> None:
    out_csv = os.path.join(SCRIPT_DIR, f"search_time_models_{plot_name}.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case_base", "model", "scheduler", "label", "mean_avg_solve_time_ms"])
        for case_base, model_label in cases:
            for sched, label, _ in SCHEDULERS:
                mean = data[(case_base, sched)]
                writer.writerow([case_base, model_label, sched, label, f"{mean:.6f}"])


def print_values(
    plot_name: str,
    cases: List[Tuple[str, str]],
    data: Dict[Tuple[str, str], float],
) -> None:
    print(f"[{plot_name}]")
    print("model,Hyacinth-dynamic,Hyacinth-pruned,Optics-pruned")
    for case_base, model_label in cases:
        vals = [data[(case_base, sched)] for sched, _, _ in SCHEDULERS]
        vals_str = ",".join(f"{v:.3f}" for v in vals)
        print(f"{model_label},{vals_str}")


def plot_one(spec: Dict[str, object]) -> None:
    data = dict(spec["data"])
    cases = list(spec["cases"])
    name = str(spec["name"])
    print_values(name, cases, data)
    write_used_csv(name, cases, data)

    fig, ax = plt.subplots(figsize=(5, 4))
    x = list(range(len(cases)))
    width = 0.24
    offsets = [-width, 0.0, width]

    all_vals: List[float] = []
    for idx, (sched, label, color) in enumerate(SCHEDULERS):
        vals = [data[(case_base, sched)] for case_base, _ in cases]
        all_vals.extend(vals)
        xpos = [v + offsets[idx] for v in x]
        ax.bar(
            xpos,
            vals,
            width=width,
            label=label,
            color=color,
            edgecolor="black",
            linewidth=0.45,
        )

    ax.set_ylabel("Avg. solve time (ms)", fontsize=LABEL_FONT_SIZE)
    ax.set_xticks(x)
    ax.set_xticklabels([label for _, label in cases], fontsize=TICK_FONT_SIZE)
    ax.tick_params(axis="y", labelsize=TICK_FONT_SIZE)
    ax.grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.35)
    ax.set_axisbelow(True)
    ax.set_ylim(0.0, max(all_vals) * 1.18 if all_vals else 1.0)
    ax.legend(frameon=False, fontsize=LEGEND_FONT_SIZE, ncol=1, loc="upper left", handlelength=1.0)

    fig.tight_layout(pad=0.2)
    for ext in ("pdf", "png"):
        out = os.path.join(SCRIPT_DIR, f"search_time_models_{name}.{ext}")
        fig.savefig(out, dpi=600)
    plt.close(fig)


def main() -> None:
    for spec in PLOTS:
        plot_one(spec)


if __name__ == "__main__":
    main()
