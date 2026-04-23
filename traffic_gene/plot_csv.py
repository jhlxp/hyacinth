#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np
import matplotlib.pyplot as plt
import csv
import os

plt.rcParams["font.family"] = "Arial"

# ====== Load CSV file (two columns: size, cdf) ======
def load_cdf_csv(path):
    sizes = []
    cdfs = []
    with open(path, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            try:
                s = float(row[0])
                c = float(row[1])
            except ValueError:
                continue
            sizes.append(s)
            cdfs.append(c)
    return np.array(sizes), np.array(cdfs)


# ====== Compute average flow size from CDF (bytes) ======
def compute_avg_flow_size(sizes, cdf):
    pdf = np.diff(np.insert(cdf, 0, 0))
    pdf = np.clip(pdf, 0, 1)

    avg_size = np.sum(sizes * pdf)
    return avg_size


# ====== Plot multiple CDFs ======
def plot_multiple_cdfs(csv_files, legends, out_path):
    fig, ax = plt.subplots(figsize=(10, 8))

    colors = ["#F9413D", "#3071F4", "#43AA8B", "#F9A03F", "#7B2CBF"]

    for i, path in enumerate(csv_files):
        sizes, cdf = load_cdf_csv(path)

        idx = np.argsort(sizes)
        sizes = sizes[idx]
        cdf = cdf[idx]

        label = legends[i] if i < len(legends) else os.path.basename(path)
        ax.plot(
            sizes,
            cdf,
            "-o",
            markersize=4,
            label=label,
            color=colors[i % len(colors)],
        )

    ax.set_xscale("log")
    ax.set_xlabel("Flow size (Bytes)", fontsize=19)
    ax.set_ylabel("CDF", fontsize=19)
    ax.set_yticks(
        [0, 0.25, 0.5, 0.75, 1],
        ["0", "0.25", "0.5", "0.75", "1"]
    )


    # --- tick label size ---
    ax.tick_params(labelsize=19)

    # --- only major grid ---
    ax.grid(True, which="major", linestyle="--", alpha=0.4)

    # --- legend font size ---
    ax.legend(
        fontsize=18,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        frameon=False,
        ncol=min(3, len(csv_files))
    )

    fig.tight_layout(rect=[0, 0, 1, 0.90])
    fig.savefig(out_path, dpi=600, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print(f"[OK] Saved CDF plot to: {out_path}")


# ====== Main ======
if __name__ == "__main__":

    csv_files = [
        "./flow_distr/websearch.csv",
        "./flow_distr/fbcoco.csv",
        "./flow_distr/fbcoco_january_2024.csv",
        "./flow_distr/fbcoco_february_2024.csv",
        "./flow_distr/fbcoco_march_2024.csv",
    ]

    legends = [
        "Websearch",
        "Meta trace",
        "Meta trace january",
        "Meta trace february",
        "Meta trace march"
    ]

    LINK_Gbps = 100
    LOAD_RATIO = 0.40

    plot_dir = "./plot"
    os.makedirs(plot_dir, exist_ok=True)

    out_img = os.path.join(plot_dir, "cdf_flows.png")
    plot_multiple_cdfs(csv_files, legends, out_img)
    out_img = os.path.join(plot_dir, "cdf_flows.pdf")
    plot_multiple_cdfs(csv_files, legends, out_img)

    print("\n========== Flow Calculation ==========\n")

    target_bps = LINK_Gbps * 1e9 * LOAD_RATIO
    print(
        f"Target throughput: {LINK_Gbps} Gbps * {LOAD_RATIO*100:.1f}% = {target_bps/1e9:.2f} Gbps\n"
    )

    for i, path in enumerate(csv_files):
        sizes, cdf = load_cdf_csv(path)

        idx = np.argsort(sizes)
        sizes = sizes[idx]
        cdf = cdf[idx]

        avg_size_bytes = compute_avg_flow_size(sizes, cdf)
        avg_size_bits = avg_size_bytes * 8

        flows_per_sec = target_bps / avg_size_bits

        label = legends[i] if i < len(legends) else os.path.basename(path)
        print(f"[{label}]")
        print(
            f"  Average flow size: {avg_size_bytes/1e6:.4f} MB  ({avg_size_bytes:.0f} bytes)"
        )
        print(
            f"  Required flows/s to reach target load: {flows_per_sec:.2f} flows/s\n"
        )
