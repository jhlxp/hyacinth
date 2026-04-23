#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hierarchical Expander Topology Generator
---------------------------------------

Logical topology:

  - Level  0 : EPS / spine switches (optional)
  - Level -1 : ToR switches, connected as a flat expander
  - Level -2 : Agg switches, each ToR connects to c Aggs
  - Server is NOT an explicit graph node.
    Each Agg is treated as one server-facing access node.
    This is encoded by:
        dl = 1

Semantics:
  - -n : number of ToRs in the expander layer
  - -k : expander degree among ToRs
  - -c : number of Aggs per ToR
  - each Agg corresponds to exactly one server endpoint logically

Thus:
  total_aggs = n * c
  total_hosts = n * c
  dl = 1

Export order in adjacency matrix:
  1) all ToRs
  2) all EPS
  3) all Aggs

Routing:
  - Routing entries are written as Agg-to-Agg
  - Flow file host IDs are mapped directly to Agg IDs
    because Agg and Server are treated as one logical endpoint

Examples:
    python expander_eps.py -n 130 -k 7 -c 5 -m pure --eps 2

    python expander_eps.py -n 130 -k 7 -c 5 -m pure -p ksp -l 4 \
        --eps 2 --route_on full --write_routing \
        --flow_file flows.htsim --traffic web --load 0.6 --plot
"""

import argparse
import os
import time
from itertools import islice
from math import sqrt

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import eigsh


# ==============================================================================
# Routing helpers
# ==============================================================================

def limit_ecmp(G, src, dst, total_limit=8):
    """
    Round-robin next-hop ECMP:
    - Ensures next-hop diversity
    - Ensures strict shortest-path correctness
    - Enumerates paths in breadth-first manner across next-hops
    """
    try:
        shortest_len = nx.shortest_path_length(G, src, dst)
    except nx.NetworkXNoPath:
        return []

    results = []
    seen = set()

    nh_generators = {}
    for nh in G[src]:
        try:
            nh_generators[nh] = nx.shortest_simple_paths(G, nh, dst)
        except nx.NetworkXNoPath:
            pass

    active_nh = list(nh_generators.keys())

    while active_nh and len(results) < total_limit:
        next_round = []

        for nh in active_nh:
            gen = nh_generators[nh]

            try:
                tail = next(gen)
            except StopIteration:
                continue

            full = [src] + tail
            hop = len(full) - 1

            if hop != shortest_len:
                continue

            tup = tuple(full)
            if tup not in seen:
                seen.add(tup)
                results.append(full)

            next_round.append(nh)

            if len(results) >= total_limit:
                break

        active_nh = next_round

    return results


def load_unique_agg_pairs(flow_files, total_aggs):
    """
    Read flow file(s) as logical endpoint pairs.
    Since Agg and Server are treated as one logical endpoint,
    flow host IDs are interpreted directly as Agg IDs.

    Expected valid range: [0, total_aggs - 1]
    """
    pairs = set()

    total_lines = 0
    valid = 0
    invalid = 0
    invalid_same = 0
    invalid_other = 0

    for flow_file in flow_files:
        with open(flow_file, "r", encoding="utf-8") as f:
            for line in f:
                total_lines += 1
                line = line.strip()

                if not line:
                    invalid += 1
                    invalid_other += 1
                    continue

                if line.startswith("#"):
                    invalid += 1
                    invalid_other += 1
                    continue

                s = line.split()
                if len(s) < 2:
                    invalid += 1
                    invalid_other += 1
                    continue

                try:
                    src = int(s[0])
                    dst = int(s[1])
                except ValueError:
                    invalid += 1
                    invalid_other += 1
                    continue

                if not (0 <= src < total_aggs and 0 <= dst < total_aggs):
                    invalid += 1
                    invalid_other += 1
                    continue

                if src == dst:
                    invalid += 1
                    invalid_same += 1
                    continue

                valid += 1
                pairs.add((src, dst))
                pairs.add((dst, src))

    print("=== Flow File Statistics ===")
    print(f"Total lines        : {total_lines}")
    print(f"Valid pairs        : {valid}")
    print(f"Invalid lines      : {invalid}")
    print(f"  ├─ Same endpoint : {invalid_same}")
    print(f"  └─ Other invalid : {invalid_other}")
    print(f"Unique src-dst     : {len(pairs)} (after adding reverse pairs)")
    print("================================")

    return pairs


# ==============================================================================
# Base expander construction
# ==============================================================================

def build_random_regular_graph(n: int, degree: int, seed: int = None) -> nx.Graph:
    if degree < 0 or degree > n - 1:
        raise ValueError("degree must be within [0, n-1]")
    if (n * degree) % 2 != 0:
        raise ValueError("n * degree must be even for a regular graph to exist")
    return nx.random_regular_graph(d=degree, n=n, seed=seed)


def const_rama_py(N: int, u: int, seed: int = None, max_trials: int = 2000) -> nx.Graph:
    """
    Constructs a u-regular Ramanujan-like expander graph.
    """
    if not (0 < u < N):
        raise ValueError("Require 0 < u < N.")
    if (u * N) % 2 != 0:
        raise ValueError("u * N must be even to admit a u-regular graph.")

    rng = np.random.default_rng(seed)
    rama_bound = 2 * sqrt(u - 1)

    for trial in range(1, max_trials + 1):
        i_pool, j_pool = np.triu_indices(N, k=1)
        in_pool = np.ones_like(i_pool, dtype=bool)
        A = np.zeros((N, N), dtype=int)
        deg = np.zeros(N, dtype=int)
        npop = (u * N) // 2
        zeroed = np.zeros(N, dtype=bool)

        success = True
        for _ in range(npop):
            available = np.flatnonzero(in_pool)
            if available.size == 0:
                success = False
                break

            pick = rng.choice(available)
            ipick, jpick = i_pool[pick], j_pool[pick]
            in_pool[pick] = False

            if deg[ipick] < u and deg[jpick] < u and A[ipick, jpick] == 0:
                A[ipick, jpick] = 1
                A[jpick, ipick] = 1
                deg[ipick] += 1
                deg[jpick] += 1

                for node in (ipick, jpick):
                    if deg[node] == u and not zeroed[node]:
                        mask = (i_pool == node) | (j_pool == node)
                        in_pool[mask] = False
                        zeroed[node] = True

        if not success or np.min(deg) != u:
            continue

        evals = np.linalg.eigvalsh(A)
        lambda2 = np.sort(np.abs(evals))[-2]
        if lambda2 <= rama_bound:
            print(f"Found Ramanujan-like graph at trial {trial}: λ₂={lambda2:.3f}, bound={rama_bound:.3f}")
            return nx.from_numpy_array(A)

    raise RuntimeError(f"Failed to find Ramanujan-like graph within {max_trials} trials.")


# ==============================================================================
# Hierarchical expander construction
# ==============================================================================

def build_hierarchical_expander(n: int, degree: int, aggs_per_tor: int,
                                mode: str, eps_count: int = 0, seed: int = None):
    """
    Build:
      level  0 : EPS layer (optional)
      level -1 : ToR layer (expander)
      level -2 : Agg layer (c Aggs per ToR)

    Server is implicit and merged with Agg logically.

    Returns:
      full_G       : full layered graph
      tor_subgraph : ToR-only expander graph
      tor_nodes    : ordered ToR names
      eps_nodes    : ordered EPS names
      agg_nodes    : ordered Agg names
    """
    if mode == "pure":
        base = build_random_regular_graph(n=n, degree=degree, seed=seed)
    elif mode == "rama":
        base = const_rama_py(N=n, u=degree, seed=seed)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    full_G = nx.Graph()

    tor_nodes = [f"ToR_{i}" for i in range(n)]
    eps_nodes = [f"EPS_{i}" for i in range(eps_count)]
    agg_nodes = []

    # ToR nodes
    for tor in tor_nodes:
        full_G.add_node(tor, type="switch", role="tor", level=-1)

    # Expander links between ToRs
    for u, v in base.edges():
        full_G.add_edge(f"ToR_{u}", f"ToR_{v}", link_type="expander")

    # EPS layer
    for eps in eps_nodes:
        full_G.add_node(eps, type="switch", role="higher_switch", level=0)
        for tor in tor_nodes:
            full_G.add_edge(eps, tor, link_type="eps")

    # Agg layer
    for i in range(n):
        tor = f"ToR_{i}"
        for j in range(aggs_per_tor):
            agg = f"Agg_{i}_{j}"
            full_G.add_node(agg, type="switch", role="agg", level=-2)
            full_G.add_edge(tor, agg, link_type="tor-agg")
            agg_nodes.append(agg)

    tor_subgraph = full_G.subgraph(tor_nodes).copy()
    return full_G, tor_subgraph, tor_nodes, eps_nodes, agg_nodes


# ==============================================================================
# Stats
# ==============================================================================

def validate_degrees(G: nx.Graph, target_degree: int) -> bool:
    degrees = [deg for _, deg in G.degree()]
    print(f"[validate_degrees] min={min(degrees)}, max={max(degrees)}, target={target_degree}")
    return all(deg == target_degree for deg in degrees)


def pairwise_shortest_path_stats(G: nx.Graph):
    if G.number_of_nodes() == 0:
        return float("inf"), -1
    if not nx.is_connected(G):
        return float("inf"), -1
    mean_distance = nx.average_shortest_path_length(G)
    diameter = nx.diameter(G)
    return mean_distance, diameter


def spectral_stats(G: nx.Graph):
    if G.number_of_nodes() < 2:
        return 0.0
    if G.number_of_edges() == 0:
        return 0.0
    A = nx.to_numpy_array(G)
    A_sparse = csr_matrix(A)
    try:
        eigvals, _ = eigsh(A_sparse, k=2, which="LM")
        return sorted(np.abs(eigvals))[-2]
    except Exception:
        dense_vals = np.linalg.eigvalsh(A)
        if dense_vals.size < 2:
            return 0.0
        return sorted(np.abs(dense_vals))[-2]


def print_level_degree_stats(G: nx.Graph):
    level_deg = {}
    for node, data in G.nodes(data=True):
        lvl = data.get("level")
        deg = G.degree(node)
        level_deg.setdefault(lvl, []).append(deg)

    print("\n=== Degree Statistics per Level ===")
    for lvl in sorted(level_deg.keys()):
        degs = level_deg[lvl]
        print(
            f"Level {lvl:2d} | "
            f"count={len(degs):4d}  "
            f"min={min(degs):3d}  "
            f"max={max(degs):3d}  "
            f"avg={sum(degs)/len(degs):.2f}"
        )
    print("")


# ==============================================================================
# Layout / plot
# ==============================================================================

def hierarchical_layout(G: nx.Graph, level_gap: float = 1.8, width_factor: float = 1.2):
    level_dict = {}
    for node, data in G.nodes(data=True):
        lvl = data.get("level", 0)
        level_dict.setdefault(lvl, []).append(node)

    levels = sorted(level_dict.keys(), reverse=True)
    pos = {}

    for i, lvl in enumerate(levels):
        nodes = sorted(level_dict[lvl])
        num = len(nodes)
        width = width_factor * (len(G.nodes()) ** 0.5) * (1 + 0.2 * (len(levels) - i))
        xs = list(range(num))
        center_shift = (num - 1) / 2.0 if num > 1 else 0.0

        for j, node in enumerate(nodes):
            pos[node] = ((xs[j] - center_shift) * (width / max(num, 1)), -i * level_gap)

    return pos


def visualize_hierarchical_expander(G: nx.Graph, filename_png: str):
    pos = hierarchical_layout(G)
    plt.figure(figsize=(12, 7))

    colors = []
    for node in G.nodes:
        role = G.nodes[node].get("role")
        if role == "agg":
            colors.append("gold")
        elif role == "tor":
            colors.append("lightcoral")
        else:
            colors.append("skyblue")

    nx.draw(
        G,
        pos,
        node_color=colors,
        with_labels=False,
        node_size=70,
        edge_color="gray",
        width=0.5
    )

    plt.title("Hierarchical Expander: EPS / ToR(expander) / Agg(server-integrated)", fontsize=12)
    plt.tight_layout()
    plt.savefig(filename_png, dpi=300)
    plt.close()
    print(f"Figure saved to {filename_png}")


# ==============================================================================
# Helpers for layered routing export
# ==============================================================================

def build_agg_parent_maps(agg_nodes):
    """
    Return:
      agg_to_tor : Agg_i_j -> ToR_i
    """
    agg_to_tor = {}
    for agg in agg_nodes:
        _, i, j = agg.split("_")
        agg_to_tor[agg] = f"ToR_{int(i)}"
    return agg_to_tor


def dedup_paths(paths):
    out = []
    seen = set()
    for p in paths:
        t = tuple(p)
        if t not in seen:
            seen.add(t)
            out.append(p)
    return out


# ==============================================================================
# HTSIM export
# ==============================================================================

def write_topology_htsim_layered(
    G: nx.Graph,
    tor_route_G: nx.Graph,
    H: int,
    dl: int,
    ul: int,
    ntor: int,
    nics: int,
    filename: str,
    K: int,
    mode: str,
    flow_files,
    write_routing: bool = False,
    route_on: str = "full"
):
    # Strict required order:
    #   1) all ToRs
    #   2) all EPS
    #   3) all Aggs
    tor_nodes = [n for n, d in G.nodes(data=True) if d.get("role") == "tor"]
    eps_nodes = [n for n, d in G.nodes(data=True) if d.get("role") == "higher_switch"]
    agg_nodes = [n for n, d in G.nodes(data=True) if d.get("role") == "agg"]

    tor_nodes.sort(key=lambda x: int(x.split("_")[1]))                  # ToR_i
    eps_nodes.sort(key=lambda x: int(x.split("_")[1]))                  # EPS_i
    agg_nodes.sort(key=lambda x: tuple(map(int, x.split("_")[1:])))     # Agg_i_j

    ordered_nodes = tor_nodes + eps_nodes + agg_nodes
    mapping = {node: idx for idx, node in enumerate(ordered_nodes)}

    G_relabel = nx.relabel_nodes(G, mapping, copy=True)
    tor_route_G_relabel = nx.relabel_nodes(tor_route_G, mapping, copy=True)

    agg_to_tor_name = build_agg_parent_maps(agg_nodes)
    agg_to_tor = {mapping[a]: mapping[t] for a, t in agg_to_tor_name.items()}

    # Agg IDs in flow file are 0..H-1, but in graph they are shifted by:
    agg_base = len(tor_nodes) + len(eps_nodes)

    N = G_relabel.number_of_nodes()
    print(f"[HTSIM] Writing topology: H={H}, dl={dl}, ul={ul}, ntor={ntor}, N={N}, nics={nics}")

    def k_shortest_paths(Gx, src, dst, Kx):
        return list(islice(nx.shortest_simple_paths(Gx, src, dst), Kx))

    def ecmp_shortest_paths(Gx, src, dst):
        shortest_len = nx.shortest_path_length(Gx, src, dst)
        paths = []
        for path in nx.all_simple_paths(Gx, src, dst, cutoff=shortest_len):
            if len(path) - 1 == shortest_len:
                paths.append(path)
        return paths

    def compute_paths_on_graph(Gx, src, dst):
        if mode == "ecmp":
            return ecmp_shortest_paths(Gx, src, dst)
        elif mode == "ksp":
            return k_shortest_paths(Gx, src, dst, K)
        elif mode == "limit_ecmp":
            return limit_ecmp(Gx, src, dst, K)
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    f = open(filename, "w", encoding="utf-8")

    PRINT_INTERVAL = 100_000
    line_buffer = []
    line_count = 0
    total_paths = 0
    t_last = time.time()

    def flush_if_needed(force=False):
        nonlocal line_buffer, line_count, t_last
        if force or len(line_buffer) >= PRINT_INTERVAL:
            for ln in line_buffer:
                f.write(ln + "\n")
            f.flush()

            now = time.time()
            delta = now - t_last
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] written {line_count:,} lines, delta={delta:.2f}s")
            t_last = now
            line_buffer = []

    # Header
    # header = f"{H} {dl} {ul} {ntor} {N} {nics}"
    header = f"{H} {dl} {ul} {ntor} {N}"
    line_buffer.append(header)
    line_count += 1
    flush_if_needed()

    # Adjacency matrix
    A = nx.to_numpy_array(G_relabel, dtype=int, nodelist=range(N))
    for i in range(N):
        row = " ".join(map(str, A[i].astype(int)))
        line_buffer.append(row)
        line_count += 1
        flush_if_needed()

    # If routing is disabled, stop here
    if not write_routing:
        if line_buffer:
            for ln in line_buffer[:-1]:
                f.write(ln + "\n")
            f.write(line_buffer[-1])
        f.close()
        print(f"[HTSIM DONE] Saved topology only to {filename}, total lines={line_count:,}")
        return

    # Routing entries are Agg-to-Agg
    pairs = load_unique_agg_pairs(flow_files, H)
    print(f"[INFO] Writing routing for {len(pairs)} Agg-to-Agg pairs")

    for src, dst in pairs:
        if src == dst:
            continue

        # convert logical Agg IDs [0, H-1] to graph node IDs
        src_agg = agg_base + src
        dst_agg = agg_base + dst

        if route_on == "full":
            try:
                paths = compute_paths_on_graph(G_relabel, src_agg, dst_agg)
            except nx.NetworkXNoPath:
                continue

        elif route_on == "expander":
            src_tor = agg_to_tor[src_agg]
            dst_tor = agg_to_tor[dst_agg]

            if src_tor == dst_tor:
                # Same parent ToR
                paths = [[src_agg, src_tor, dst_agg]]
            else:
                try:
                    tor_paths = compute_paths_on_graph(tor_route_G_relabel, src_tor, dst_tor)
                except nx.NetworkXNoPath:
                    continue

                paths = []
                for tp in tor_paths:
                    full_p = [src_agg] + tp + [dst_agg]
                    paths.append(full_p)

                paths = dedup_paths(paths)
        else:
            raise ValueError(f"Unsupported route_on: {route_on}")

        for path in paths:
            middle = path[1:-1]
            if middle:
                line = f"{path[0]} {path[-1]} " + " ".join(map(str, middle))
            else:
                line = f"{path[0]} {path[-1]}"

            line_buffer.append(line)
            total_paths += 1
            line_count += 1
            flush_if_needed()

    if line_buffer:
        for ln in line_buffer[:-1]:
            f.write(ln + "\n")
        f.write(line_buffer[-1])

    f.close()
    print(f"[HTSIM DONE] Saved to {filename}, total lines={line_count:,}, total paths={total_paths:,}")


# ==============================================================================
# Main
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Hierarchical Expander Generator (EPS + ToR expander + Agg(server-integrated))"
    )

    parser.add_argument("-n", type=int, default=130, help="number of ToRs in expander layer")
    parser.add_argument("-k", type=int, default=8, help="expander degree among ToRs")
    parser.add_argument("-c", type=int, default=1, help="number of Aggs per ToR; each Agg is one logical server endpoint")
    parser.add_argument("-m", type=str, choices=["pure", "rama"], default="pure",
                        help="graph generation mode")
    parser.add_argument("-p", type=str, choices=["ksp", "ecmp", "limit_ecmp"], default="ksp",
                        help="path generation mode")
    parser.add_argument("-l", type=int, default=8, help="number of paths for KSP/limit-ECMP")

    parser.add_argument(
        "--eps",
        type=int,
        default=0,
        help="number of top-layer EPS/spine switches; each EPS connects to all ToRs. Set 0 to disable the top layer."
    )
    parser.add_argument(
        "--route_on",
        type=str,
        choices=["expander", "full"],
        default="full",
        help="routing graph: ToR expander only, or full topology"
    )
    parser.add_argument(
        "--write_routing",
        action="store_true",
        help="if set, compute and write routing entries; otherwise only write header + adjacency matrix"
    )

    parser.add_argument(
        "--flow_file",
        type=str,
        nargs="+",
        default=None,
        help="One or multiple flow files (.htsim) used to extract unique logical endpoint pairs"
    )
    parser.add_argument("--load", type=str, default="none", help="Traffic load intensity (saved to output filename)")
    parser.add_argument("--traffic", type=str, default="none", help="Traffic type")
    parser.add_argument("--seed", type=int, default=None, help="random seed")
    parser.add_argument("--plot", action="store_true", help="if set, draw and save the generated topology figure")
    parser.add_argument("--topo_dir", type=str, default=".", help="output directory for topology file")
    parser.add_argument(
        "--filename",
        type=str,
        default=None,
        help="Optional custom output filename. If not provided, use auto-generated name."
    )

    args = parser.parse_args()

    if args.n <= 0:
        raise ValueError("Require n > 0.")
    if args.k < 0:
        raise ValueError("Require k >= 0.")
    if args.eps < 0:
        raise ValueError("Require eps >= 0.")
    if args.c <= 0:
        raise ValueError("Require c > 0.")
    if args.write_routing and not args.flow_file:
        raise ValueError("--flow_file is required when --write_routing is enabled.")

    print("=== Constructing Hierarchical Expander ===")
    print(
        f"mode={args.m}, ToR={args.n}, expander_degree={args.k}, "
        f"aggs_per_tor={args.c}, eps={args.eps}, write_routing={args.write_routing}"
    )

    G, tor_G, tor_nodes, eps_nodes, agg_nodes = build_hierarchical_expander(
        n=args.n,
        degree=args.k,
        aggs_per_tor=args.c,
        mode=args.m,
        eps_count=args.eps,
        seed=args.seed
    )

    print("\n=== Logical Topology Layers ===")
    print(f"Level  0 : EPS    = {len(eps_nodes)}")
    print(f"Level -1 : ToR    = {len(tor_nodes)}")
    print(f"Level -2 : Agg    = {len(agg_nodes)} ({args.c} per ToR)")
    print(f"Total graph nodes = {G.number_of_nodes()}")

    print("\n=== Expander Layer Stats (ToR-only) ===")
    print(f"ToRs={len(tor_nodes)}, EPS={len(eps_nodes)}, Aggs={len(agg_nodes)}, total_graph_nodes={G.number_of_nodes()}")
    print(f"expander_edges={tor_G.number_of_edges()}, degree_ok={validate_degrees(tor_G, args.k)}")

    mean_distance, diameter = pairwise_shortest_path_stats(tor_G)
    lambda2 = spectral_stats(tor_G)
    rama_bound = 2 * np.sqrt(args.k - 1) if args.k >= 1 else 0.0

    print(f"mean_shortest_path={mean_distance:.4f}, diameter={diameter}")
    print(f"λ₂={lambda2:.3f}, bound={rama_bound:.3f}, valid={lambda2 <= rama_bound if args.k >= 1 else True}")

    print_level_degree_stats(G)

    # Semantics:
    #   Agg is the access node and also the logical server endpoint
    H = len(agg_nodes)         # total logical hosts/endpoints
    dl = 1                     # one server per Agg
    ul = 1                     # one uplink from Agg to ToR
    ntor = len(agg_nodes)      # access-layer node count (Agg count)
    nics = 1                   # one NIC / one logical endpoint per Agg

    os.makedirs(args.topo_dir, exist_ok=True)

    auto_filename = (
        f"{args.traffic}_hier_expander_"
        f"N{args.n}_K{args.k}_C{args.c}_EPS{args.eps}_"
        f"{args.m}_{args.p}_route-{args.route_on}_wr{int(args.write_routing)}_load{args.load}.txt"
    )
    final_name = args.filename if args.filename is not None else auto_filename
    filename = os.path.join(args.topo_dir, final_name)

    write_topology_htsim_layered(
        G=G,
        tor_route_G=tor_G,
        H=H,
        dl=dl,
        ul=ul,
        ntor=ntor,
        nics=nics,
        filename=filename,
        K=args.l,
        mode=args.p,
        flow_files=args.flow_file or [],
        write_routing=args.write_routing,
        route_on=args.route_on
    )

    if args.plot:
        fig_name = filename.replace(".txt", ".png")
        visualize_hierarchical_expander(G, fig_name)

    print(f"HTSIM file saved: {filename}")


if __name__ == "__main__":
    main()
