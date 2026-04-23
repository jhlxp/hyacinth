#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-file Flow Size CDF Plotter (stacked subplots)
---------------------------------------------------
- Reads multiple .htsim files.
- Plots flow size CDFs (log-x) stacked vertically.
- Saves final figure (no plt.show()).
"""

import numpy as np
import matplotlib.pyplot as plt
import os
import time

INPUT_FILES = [
    "../tasks/websearch_traffic/clos/flows_clos_98racks_9c_1pct_1.001s.htsim",
]  

OUTPUT_DIR = "./plot_flows"
os.makedirs(OUTPUT_DIR, exist_ok=True)

plt.rcParams.update({
    "font.size": 12,
    "axes.grid": True,
    "figure.figsize": (8, 10),
})


def plot_multiple_cdfs(filelist):
    """Plot stacked flow size CDFs for multiple .htsim files."""
    t0 = time.time()
    n_files = len(filelist)
    fig, axes = plt.subplots(n_files, 1, figsize=(8, 3.2 * n_files), sharex=True)

    if n_files == 1:
        axes = [axes]

    for i, htsim_file in enumerate(filelist):
        if not os.path.exists(htsim_file):
            print(f"[Warning] File not found: {htsim_file}")
            continue

        data = np.loadtxt(htsim_file)
        if data.ndim == 1:
            data = data[None, :]
        size = data[:, 2]

        sorted_sizes = np.sort(size)
        cdf = np.arange(1, len(sorted_sizes) + 1) / len(sorted_sizes)
        label = os.path.basename(htsim_file).replace(".htsim", "")
        axes[i].plot(sorted_sizes, cdf, lw=2, label=label)

        axes[i].set_xscale("log")
        axes[i].set_ylim(0, 1)
        axes[i].set_ylabel("CDF")
        axes[i].legend(loc="lower right", fontsize=10)
        axes[i].grid(True, which="both", ls="--", lw=0.5)

    axes[-1].set_xlabel("Flow size (Bytes, log scale)")
    fig.suptitle("Flow Size Distributions (Multiple Workloads)", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    outfile = os.path.join(OUTPUT_DIR, "flow_size_cdf_stack.png")
    plt.savefig(outfile, dpi=200)
    plt.close(fig)

    print(f"\n✅ Saved stacked plot to: {outfile}")
    print(f"Time cost: {time.time() - t0:.2f}s\n")


if __name__ == "__main__":
    plot_multiple_cdfs(INPUT_FILES)
