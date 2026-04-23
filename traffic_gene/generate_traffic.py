#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
General traffic generator for arbitrary topologies (optimized)
--------------------------------------------------------------
Generates inter-rack (inter-ToR) uniform random flows following
WebSearch workload (or user-provided CDF file).

Each line in output .htsim file:
    src_host dst_host flow_size_bytes start_time_ns [group_id]
"""

import numpy as np
import time
import argparse
import os


def write_to_htsim_file(flowmat, filename, output_dir, include_group=True):
    """Write flow matrix to .htsim file (same format as MATLAB)."""
    print("Writing to htsim file...")
    t0 = time.time()

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{filename}.htsim")

    with open(out_path, "w") as f:
        for i, row in enumerate(flowmat):
            src, dst, size_b, start_ns = row[:4]
            end = "\n" if i < len(flowmat) - 1 else ""
            if include_group and len(row) >= 5:
                group_id = row[4]
                f.write(
                    f"{int(src - 1)} {int(dst - 1)} {int(size_b)} "
                    f"{int(start_ns)} {int(group_id)}{end}"
                )
            else:
                f.write(f"{int(src - 1)} {int(dst - 1)} {int(size_b)} {int(start_ns)}{end}")

    print(f"    Finished in {time.time() - t0:.2f} seconds")
    print(f"    Saved to {out_path}")


def generate_general_traffic(
    topo_name,
    Nrack,
    Hosts_p_rack,
    workload_path,
    output_dir,
    nics=1,
    nic_rate=100e9,
    loadfrac0=0.01,
    totaltime=1.001,
    coflow_window_ms=20.0,
    include_group=True,
):
    """Generate inter-rack uniform random flows for any topology type."""
    H = Nrack * Hosts_p_rack
    filename = (
        f"flows_{topo_name}_{Nrack}racks_{Hosts_p_rack}c_"
        f"{int(100 * loadfrac0)}pct_{totaltime:.3f}s"
    )

    print(f"\n=== General Traffic Generation ===")
    print(f"Topology: {topo_name}")
    print(f"Nrack={Nrack}, Hosts_per_rack={Hosts_p_rack}, Total_hosts={H}")
    print(f"Load fraction={loadfrac0:.3f}, Duration={totaltime:.3f}s")
    print(f"Workload CSV: {workload_path}")
    print(f"Output dir: {output_dir}")
    print("--------------------------------------------------------")

    # ===== 1. Load flow size CDF =====
    print("Loading flow size distribution...")
    data = np.loadtxt(workload_path, delimiter=",")
    flowsize, flowcdf = data[:, 0], data[:, 1]

    avg_flowsize = np.sum(flowsize[1:] * np.diff(flowcdf))  # bytes / flow
    linkrate = (nic_rate * nics) / 8  # bytes/s per host NIC

    lambda_host_max = linkrate / avg_flowsize
    lambda_host = loadfrac0 * lambda_host_max
    lambda_network = H * lambda_host

    nflows_est = int(np.ceil(lambda_network * totaltime))
    print(f"Estimated number of flows ≈ {nflows_est}")

    # ===== 2. Generate Poisson arrivals =====
    print("Generating flow start times (Poisson process)...")
    t0 = time.time()
    crt_time = 0.0
    start_times = []
    while crt_time < totaltime:
        crt_time += -np.log(1 - np.random.rand()) / lambda_network
        start_times.append(crt_time)
    start_times = np.array(start_times)
    start_times = start_times[start_times < totaltime]
    nflows = len(start_times)
    print(f"    Generated {nflows} start times in {time.time() - t0:.2f} sec")

    # ===== 3. Assign flow sizes =====
    print("Assigning flow sizes...")
    t0 = time.time()
    randvect = np.random.rand(nflows)
    size_list = flowsize[np.searchsorted(flowcdf, randvect)]
    print(f"Finished in {time.time() - t0:.2f} sec")

    # ===== 4. Assign src–dst =====
    print("Assigning source and destination hosts (inter-rack only)...")
    t0 = time.time()
    src_list = np.random.randint(1, H + 1, nflows)
    dst_list = np.random.randint(1, H + 1, nflows)

    # same_rack = ((src_list - 1) // Hosts_p_rack) == ((dst_list - 1) // Hosts_p_rack)
    # while np.any(same_rack):
    #     dst_list[same_rack] = np.random.randint(1, H + 1, np.sum(same_rack))
    #     same_rack = ((src_list - 1) // Hosts_p_rack) == ((dst_list - 1) // Hosts_p_rack)

    same_host = (src_list == dst_list)
    while np.any(same_host):
        dst_list[same_host] = np.random.randint(1, H + 1, np.sum(same_host))
        same_host = (src_list == dst_list)


    print(f"Finished in {time.time() - t0:.2f} sec")

    # ===== 5. Write out =====
    start_ns = np.round(start_times * 1e9).astype(np.int64)
    if include_group:
        coflow_window_ns = int(round(coflow_window_ms * 1e6))
        if coflow_window_ns <= 0:
            raise ValueError(f"coflow_window_ms must be > 0, got {coflow_window_ms}")
        group_ids = np.floor_divide(start_ns, coflow_window_ns).astype(np.int64)
        flowmat = np.column_stack((src_list, dst_list, size_list, start_ns, group_ids))
        print(
            f"Coflow grouping enabled: window={coflow_window_ms:.3f} ms, "
            f"num_groups={len(np.unique(group_ids))}"
        )
    else:
        flowmat = np.column_stack((src_list, dst_list, size_list, start_ns))

    # ===== Extra reporting: unique src-dst pairs =====
    unique_pairs = set(zip(src_list, dst_list))
    print(f"Total flows = {nflows}")
    print(f"Unique (src, dst) pairs = {len(unique_pairs)}")

    actual_load = np.sum(size_list) / (totaltime * H * linkrate)
    print(f"\nSpecified fraction of capacity = {loadfrac0:.3f}")
    print(f"Actual fraction of capacity    = {actual_load:.3f}\n")

    write_to_htsim_file(flowmat, filename, output_dir, include_group=include_group)
    print(f"Done. Output file: {filename}.htsim\n")

    return flowmat


# ===== Command-line Interface =====
if __name__ == "__main__":
    np.random.seed(42) 
    parser = argparse.ArgumentParser(
        description="General inter-rack traffic generator (.htsim format, optimized)"
    )
    parser.add_argument("-t", "--topo-name", type=str, required=True)
    parser.add_argument("-r", "--nrack", type=int, required=True)
    parser.add_argument("-c", "--hosts-per-rack", type=int, required=True)
    parser.add_argument("-l", "--load", type=float, default=0.01)
    parser.add_argument("-T", "--time", type=float, default=1.001)
    parser.add_argument("--nics", type=int, default=1,
                        help="Number of NICs per host (default 1)")
    parser.add_argument("--nic-rate", type=float, default=100e9,
                        help="Rate of each NIC in bits/s (default 100Gbps)")
    parser.add_argument("--coflow-window-ms", type=float, default=20.0,
                        help="Coflow grouping window in ms (default 20)")
    parser.add_argument("--no-group", action="store_true",
                        help="Disable group_id column and emit legacy 4-column format")


    # NEW: workload & output directory
    parser.add_argument("--workload", type=str, required=True,
                        help="Path to workload CDF (CSV)")
    parser.add_argument("--outdir", type=str, required=True,
                        help="Directory to store output .htsim file")

    args = parser.parse_args()

    generate_general_traffic(
        topo_name=args.topo_name,
        Nrack=args.nrack,
        Hosts_p_rack=args.hosts_per_rack,
        workload_path=args.workload,
        output_dir=args.outdir,
        nics=args.nics,
        nic_rate=args.nic_rate,
        loadfrac0=args.load,
        totaltime=args.time,
        coflow_window_ms=args.coflow_window_ms,
        include_group=(not args.no_group),
    )
