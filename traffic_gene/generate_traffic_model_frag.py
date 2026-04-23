#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Model+Fragmentation aware traffic generator (host-level .htsim)
---------------------------------------------------------------
This is a copied-and-extended generator for multi-tenant inference style traffic.

Compared to the legacy generator, this script adds:
- model deployment mix (S/M/L templates)
- host-level fragmented placement across ToRs
- PP-group scoped all2allv-like communication sets
- top-k fanout (GPU-level picks mapped to host-level flows)

Output line format (.htsim):
    src_host dst_host flow_size_bytes start_time_ns group_id
"""

import argparse
import csv
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np


MODEL_TEMPLATES = {
    "S": {"gpus": 256, "pp": 8, "ep": 32, "tp": 1, "dp": 1, "hosts": 32},
    "M": {"gpus": 320, "pp": 8, "ep": 40, "tp": 1, "dp": 1, "hosts": 40},
    "L": {"gpus": 512, "pp": 8, "ep": 64, "tp": 1, "dp": 1, "hosts": 64},
}

# Default experiment knobs (keep close to model templates for quick tuning).
DEFAULT_MODEL_MIX = "5L,4M,4S"
DEFAULT_FRAG_LEVEL = 0.5
COFLOW_MODE_TIME_WINDOW = "time_window"
COFLOW_MODE_ALL2ALLV_EVENT = "all2allv_event"
INSUFFICIENT_POLICY_STRICT = "strict"
INSUFFICIENT_POLICY_SKIP_MODEL = "skip_model"
TRAFFIC_MODE_LOAD_POISSON = "load_poisson"
TRAFFIC_MODE_INFER_GROUPS = "infer_groups"


@dataclass
class ModelPlacement:
    model_id: str
    model_type: str
    hosts: List[int]
    pp_groups: List[List[int]]
    t_min: int
    t_max: int
    t_used: int
    frag: float



def parse_model_mix(mix: str) -> List[str]:
    """Parse '5L,4M,1S' into ['L1'...'S1'] with type kept in id prefix."""
    parts = [p.strip() for p in mix.split(",") if p.strip()]
    if not parts:
        raise ValueError("model_mix is empty")

    count_by_type = {"S": 0, "M": 0, "L": 0}
    model_ids: List[str] = []

    for p in parts:
        m = re.fullmatch(r"(\d+)\s*([SMLsml])", p)
        if not m:
            raise ValueError(f"Invalid model mix token: {p}")
        cnt = int(m.group(1))
        typ = m.group(2).upper()
        if cnt <= 0:
            raise ValueError(f"Model count must be > 0 in token: {p}")
        for _ in range(cnt):
            count_by_type[typ] += 1
            model_ids.append(f"{typ}{count_by_type[typ]}")

    return model_ids



def build_model_mix_tag(model_ids: Sequence[str]) -> str:
    count_by_type = {"S": 0, "M": 0, "L": 0}
    for model_id in model_ids:
        t = model_id[0].upper()
        if t not in count_by_type:
            raise ValueError(f"Unknown model type in model id: {model_id}")
        count_by_type[t] += 1
    parts = []
    for t in ("L", "M", "S"):
        if count_by_type[t] > 0:
            parts.append(f"{count_by_type[t]}{t}")
    return "".join(parts)


def build_frag_tag(frag_level: float) -> str:
    return f"{frag_level:.3f}".rstrip("0").rstrip(".").replace(".", "p")


def build_pct_tag(load_fraction: float) -> str:
    pct = 100.0 * load_fraction
    return f"{pct:.2f}".rstrip("0").rstrip(".").replace(".", "p") + "pct"



def adjust_last_coflow_to_target_bytes(
    flows: List[Tuple[int, int, int, int, int]],
    target_total_bytes: int,
    max_flow_size_bytes: int,
) -> Tuple[List[Tuple[int, int, int, int, int]], int]:
    if not flows:
        return flows, target_total_bytes

    total_bytes = int(sum(f[2] for f in flows))
    delta = int(target_total_bytes - total_bytes)
    if delta == 0:
        return flows, 0

    last_gid = max(f[4] for f in flows)
    idxs = [i for i, f in enumerate(flows) if f[4] == last_gid]
    if not idxs:
        return flows, delta

    out = list(flows)
    if delta > 0:
        # First, top up existing flows in the last coflow, but never exceed
        # CDF max flow size for a single flow record.
        delta_left = int(delta)
        cap_single = max(1, int(max_flow_size_bytes))
        for i in idxs:
            if delta_left <= 0:
                break
            src, dst, b, st, gid = out[i]
            add_cap = max(0, cap_single - int(b))
            if add_cap <= 0:
                continue
            add = min(add_cap, delta_left)
            out[i] = (src, dst, int(b + add), st, gid)
            delta_left -= add

        # If still not enough bytes, append extra flow records in the same
        # last coflow (same src/dst/start/gid), each also capped by CDF max.
        rr = 0
        while delta_left > 0:
            base_i = idxs[rr % len(idxs)]
            src, dst, _b, st, gid = out[base_i]
            chunk = min(cap_single, delta_left)
            out.append((int(src), int(dst), int(chunk), int(st), int(gid)))
            delta_left -= chunk
            rr += 1
    else:
        trim = -delta
        for i in reversed(idxs):
            src, dst, b, st, gid = out[i]
            if trim <= 0:
                break
            if b <= trim:
                out[i] = (src, dst, 0, st, gid)
                trim -= b
            else:
                out[i] = (src, dst, int(b - trim), st, gid)
                trim = 0
        # If the last coflow is still insufficient for trimming, keep trimming
        # from earlier flows globally (newest first) to match target bytes.
        if trim > 0:
            for i in range(len(out) - 1, -1, -1):
                if trim <= 0:
                    break
                src, dst, b, st, gid = out[i]
                if b <= 0:
                    continue
                if b <= trim:
                    out[i] = (src, dst, 0, st, gid)
                    trim -= b
                else:
                    out[i] = (src, dst, int(b - trim), st, gid)
                    trim = 0
        out = [f for f in out if f[2] > 0]

    residual = int(target_total_bytes - sum(f[2] for f in out))
    return out, residual


def check_gpu_capacity_or_raise(
    model_ids: Sequence[str],
    nrack: int,
    hosts_per_rack: int,
    gpus_per_host: int,
) -> None:
    total_cluster_gpus = nrack * hosts_per_rack * gpus_per_host
    required_gpus = 0
    model_cnt: Dict[str, int] = {"S": 0, "M": 0, "L": 0}

    for model_id in model_ids:
        model_type = model_id[0].upper()
        if model_type not in MODEL_TEMPLATES:
            raise ValueError(f"Unknown model type in model id: {model_id}")
        model_cnt[model_type] += 1
        required_gpus += int(MODEL_TEMPLATES[model_type]["gpus"])

    if required_gpus > total_cluster_gpus:
        raise ValueError(
            "Model deployment exceeds cluster GPU capacity: "
            f"required_gpus={required_gpus}, cluster_gpus={total_cluster_gpus}, "
            f"model_count(S/M/L)={model_cnt['S']}/{model_cnt['M']}/{model_cnt['L']}"
        )



def load_cdf(path: str) -> Tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(path, delimiter=",")
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"Invalid CDF file: {path}")
    flow_size = data[:, 0].astype(float)
    flow_cdf = data[:, 1].astype(float)

    if len(flow_size) < 2:
        raise ValueError("CDF must have at least 2 rows")
    if not np.all(np.diff(flow_cdf) >= 0):
        raise ValueError("CDF values must be non-decreasing")
    if flow_cdf[-1] < 0.99:
        raise ValueError("CDF tail should end near 1.0")

    return flow_size, flow_cdf



def sample_size_from_cdf(rng: np.random.Generator, flow_size: np.ndarray, flow_cdf: np.ndarray) -> int:
    r = float(rng.random())
    idx = int(np.searchsorted(flow_cdf, r, side="left"))
    if idx >= len(flow_size):
        idx = len(flow_size) - 1
    return max(1, int(round(float(flow_size[idx]))))



def init_tor_hosts(num_tor: int, hosts_per_tor: int) -> Dict[int, List[int]]:
    tor_hosts: Dict[int, List[int]] = {}
    for tor in range(num_tor):
        base = tor * hosts_per_tor
        tor_hosts[tor] = [base + i for i in range(hosts_per_tor)]
    return tor_hosts



def pick_tor_set_with_capacity(
    rng: np.random.Generator,
    tor_hosts: Dict[int, List[int]],
    target_t: int,
    need_hosts: int,
) -> List[int]:
    avail = [t for t, hs in tor_hosts.items() if hs]
    if not avail:
        raise RuntimeError("No ToR has free host slots")

    target_t = max(1, min(target_t, len(avail)))

    # Try random subsets first.
    for _ in range(256):
        cand = list(rng.choice(avail, size=target_t, replace=False))
        cap = sum(len(tor_hosts[t]) for t in cand)
        if cap >= need_hosts:
            return cand

    # Greedy fallback by remaining capacity.
    ranked = sorted(avail, key=lambda t: len(tor_hosts[t]), reverse=True)
    cand: List[int] = []
    cap = 0
    for t in ranked:
        cand.append(t)
        cap += len(tor_hosts[t])
        if len(cand) >= target_t and cap >= need_hosts:
            return cand

    raise RuntimeError(
        f"Cannot find ToR subset with enough capacity (need_hosts={need_hosts}, target_t={target_t})"
    )



def allocate_model_hosts(
    rng: np.random.Generator,
    tor_hosts: Dict[int, List[int]],
    hosts_per_tor: int,
    need_hosts: int,
    frag_level: float,
) -> Tuple[List[int], int, int, int, float]:
    avail_caps = sorted((len(hs) for hs in tor_hosts.values() if hs), reverse=True)
    if not avail_caps:
        raise RuntimeError("No ToR has free host slots")
    if sum(avail_caps) < need_hosts:
        raise RuntimeError(
            f"Host pool exhausted while allocating model: need_hosts={need_hosts}, "
            f"remaining_hosts={sum(avail_caps)}"
        )

    # Effective bounds under current residual capacity (not idealized full-capacity bounds).
    t_min = 0
    cap_acc = 0
    for c in avail_caps:
        t_min += 1
        cap_acc += c
        if cap_acc >= need_hosts:
            break
    t_max = int(min(need_hosts, len(avail_caps)))

    if t_max == t_min:
        target_t = t_min
    else:
        target_t = int(round(t_min + frag_level * (t_max - t_min)))
        target_t = max(t_min, min(t_max, target_t))

    selected_tors = pick_tor_set_with_capacity(rng, tor_hosts, target_t, need_hosts)
    rng.shuffle(selected_tors)

    assigned: List[int] = []
    # Phase-1: guarantee at least one host on every selected ToR.
    for tor in selected_tors:
        if len(assigned) >= need_hosts:
            break
        if not tor_hosts[tor]:
            raise RuntimeError(f"Selected ToR has no free hosts unexpectedly: tor={tor}")
        assigned.append(tor_hosts[tor].pop())

    # Phase-2: fill remaining hosts from the selected set.
    while len(assigned) < need_hosts:
        candidates = [t for t in selected_tors if tor_hosts[t]]
        if not candidates:
            raise RuntimeError(
                f"Selected ToR set cannot satisfy need_hosts after phase-1, "
                f"need_hosts={need_hosts}, assigned={len(assigned)}, selected_tors={len(selected_tors)}"
            )

        weights = np.array([len(tor_hosts[t]) for t in candidates], dtype=float)
        weights = weights / weights.sum()
        tor = int(rng.choice(candidates, p=weights))
        host = tor_hosts[tor].pop()
        assigned.append(host)

    used_tors = len(set(h // hosts_per_tor for h in assigned))
    if t_max == t_min:
        frag = 0.0
    else:
        frag = (used_tors - t_min) / float(t_max - t_min)
    frag = float(max(0.0, min(1.0, frag)))

    return assigned, t_min, t_max, used_tors, float(frag)



def build_model_placements(
    rng: np.random.Generator,
    num_tor: int,
    hosts_per_tor: int,
    gpus_per_host: int,
    model_ids: Sequence[str],
    frag_level: float,
) -> List[ModelPlacement]:
    tor_hosts = init_tor_hosts(num_tor, hosts_per_tor)
    placements: List[ModelPlacement] = []

    for model_id in model_ids:
        model_type = model_id[0].upper()
        if model_type not in MODEL_TEMPLATES:
            raise ValueError(f"Unknown model type in model id: {model_id}")
        tpl = MODEL_TEMPLATES[model_type]
        need_hosts = int(tpl["hosts"])
        pp = int(tpl["pp"])

        hosts, t_min, t_max, t_used, frag = allocate_model_hosts(
            rng=rng,
            tor_hosts=tor_hosts,
            hosts_per_tor=hosts_per_tor,
            need_hosts=need_hosts,
            frag_level=frag_level,
        )

        if len(hosts) % pp != 0:
            raise RuntimeError(
                f"Model {model_id}: hosts={len(hosts)} not divisible by PP={pp}, cannot split PP groups"
            )

        group_size_hosts = len(hosts) // pp
        shuffled = list(hosts)
        rng.shuffle(shuffled)

        pp_groups: List[List[int]] = []
        for i in range(pp):
            pp_groups.append(shuffled[i * group_size_hosts : (i + 1) * group_size_hosts])

        placements.append(
            ModelPlacement(
                model_id=model_id,
                model_type=model_type,
                hosts=hosts,
                pp_groups=pp_groups,
                t_min=t_min,
                t_max=t_max,
                t_used=t_used,
                frag=frag,
            )
        )

    return placements



def build_group_endpoints(pp_group_hosts: List[int], gpus_per_host: int) -> List[Tuple[int, int]]:
    endpoints: List[Tuple[int, int]] = []
    for h in pp_group_hosts:
        for g in range(gpus_per_host):
            endpoints.append((h, g))
    return endpoints



def write_htsim(
    flows: List[Tuple[int, int, int, int, int]],
    out_path: str,
    coflow_window_ms: float,
    coflow_mode: str,
) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    window_ns = 0
    if coflow_mode == COFLOW_MODE_TIME_WINDOW:
        window_ns = int(round(coflow_window_ms * 1e6))
        if window_ns <= 0:
            raise ValueError(f"coflow_window_ms must be > 0, got {coflow_window_ms}")
    elif coflow_mode != COFLOW_MODE_ALL2ALLV_EVENT:
        raise ValueError(
            f"Unknown coflow_mode={coflow_mode}, "
            f"valid modes: {COFLOW_MODE_TIME_WINDOW}, {COFLOW_MODE_ALL2ALLV_EVENT}"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        for i, (src, dst, size_b, start_ns, event_gid) in enumerate(flows):
            if coflow_mode == COFLOW_MODE_TIME_WINDOW:
                gid = start_ns // window_ns
            else:
                gid = event_gid
            line = f"{src} {dst} {size_b} {start_ns} {gid}"
            if i + 1 < len(flows):
                f.write(line + "\n")
            else:
                f.write(line)



def write_placement_csv(placements: List[ModelPlacement], out_csv: str, hosts_per_tor: int) -> None:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "model_id",
                "model_type",
                "num_hosts",
                "t_min",
                "t_max",
                "t_used",
                "frag_model",
                "tors_used",
                "pp_groups_hosts",
            ]
        )
        for p in placements:
            tors = sorted(set(h // hosts_per_tor for h in p.hosts))
            pp_groups = ["[" + ",".join(str(h) for h in g) + "]" for g in p.pp_groups]
            w.writerow(
                [
                    p.model_id,
                    p.model_type,
                    len(p.hosts),
                    p.t_min,
                    p.t_max,
                    p.t_used,
                    f"{p.frag:.6f}",
                    "[" + ",".join(str(t) for t in tors) + "]",
                    "|".join(pp_groups),
                ]
            )



def generate_model_fragmented_traffic(args: argparse.Namespace) -> None:
    t0 = time.time()
    rng = np.random.default_rng(args.seed)

    model_ids = parse_model_mix(args.model_mix)
    model_mix_tag = build_model_mix_tag(model_ids)
    frag_tag = build_frag_tag(args.frag_level)
    check_gpu_capacity_or_raise(
        model_ids=model_ids,
        nrack=args.nrack,
        hosts_per_rack=args.hosts_per_rack,
        gpus_per_host=args.gpus_per_host,
    )
    print("\n=== Model+Fragmentation Traffic Generation ===")
    print(f"Topology: {args.topo_name}")
    print(f"Nrack={args.nrack}, Hosts_per_rack={args.hosts_per_rack}, GPUs_per_host={args.gpus_per_host}")
    print(f"Model mix: {args.model_mix} -> {len(model_ids)} models")
    print(f"Frag level target: {args.frag_level:.3f}")
    print(f"Top-k fanout: {args.topk}")
    print("PP scheduling: round-robin per model (PP1->PP8)")
    print(f"Coflow mode: {args.coflow_mode}")
    if args.traffic_mode == TRAFFIC_MODE_LOAD_POISSON:
        print(f"Traffic mode: {args.traffic_mode} (load-driven)")
        print(f"Load fraction={args.load:.3f}, Duration={args.time:.3f}s")
    else:
        print(f"Traffic mode: {args.traffic_mode} (inference groups)")
        print(f"Inference groups={args.infer_groups}, interval={args.infer_interval_ms:.3f} ms")
        print(
            f"PP1 random start in [0, {args.infer_model_pp1_spread_ms:.3f}] ms, "
            f"PP-step jitter in [0, {args.infer_pp_jitter_ms:.3f}] ms"
        )
    print(f"Workload CDF: {args.workload}")
    print(f"Output dir: {args.outdir}")
    print("--------------------------------------------------------")

    flow_size, flow_cdf = load_cdf(args.workload)
    avg_edge_bytes = float(np.sum(flow_size[1:] * np.diff(flow_cdf)))
    if avg_edge_bytes <= 0:
        raise ValueError("avg_edge_bytes must be > 0")

    placements = build_model_placements(
        rng=rng,
        num_tor=args.nrack,
        hosts_per_tor=args.hosts_per_rack,
        gpus_per_host=args.gpus_per_host,
        model_ids=model_ids,
        frag_level=args.frag_level,
    )

    host_weight_sum = float(sum(len(p.hosts) for p in placements))
    frag_mt = float(sum(len(p.hosts) * p.frag for p in placements) / host_weight_sum)
    print(f"Actual multi-tenant fragmentation F_MT = {frag_mt:.6f}")

    # Build endpoint caches for GPU-level topk sampling.
    # One EP corresponds to one GPU endpoint: (host_id, gpu_local_id).
    group_endpoints: Dict[Tuple[str, int], List[Tuple[int, int]]] = {}
    model_endpoints: Dict[str, List[Tuple[int, int]]] = {}
    for p in placements:
        model_endpoints[p.model_id] = build_group_endpoints(p.hosts, args.gpus_per_host)
        for gi, g_hosts in enumerate(p.pp_groups):
            group_endpoints[(p.model_id, gi)] = build_group_endpoints(g_hosts, args.gpus_per_host)

    total_hosts_cluster = args.nrack * args.hosts_per_rack
    linkrate_bytes_s = (args.nic_rate * args.nics) / 8.0
    target_total_bytes = 0

    # Model selection weights for load-driven mode.
    if args.model_weight == "uniform":
        m_weights = np.ones(len(placements), dtype=float)
    else:
        m_weights = np.array([len(p.hosts) for p in placements], dtype=float)
    m_weights = m_weights / m_weights.sum()
    next_pp_idx_by_model: Dict[str, int] = {p.model_id: 0 for p in placements}

    # Build event plan:
    # each item is (event_gid, start_time_sec, model_index, pp_index)
    event_plan: List[Tuple[int, float, int, int]] = []
    if args.traffic_mode == TRAFFIC_MODE_LOAD_POISSON:
        # Event-level offered load model.
        # One coflow event = one PP-group round where every EP GPU sends to top-k GPUs:
        # per-event edges ~= EP * topk.
        target_bytes_per_sec = args.load * total_hosts_cluster * linkrate_bytes_s
        target_total_bytes = int(round(target_bytes_per_sec * args.time))

        # EP-level event source count.
        ep_sizes = np.array(
            [len(group_endpoints[(p.model_id, 0)]) for p in placements],
            dtype=float,
        )
        expected_ep = float(np.sum(m_weights * ep_sizes))
        if expected_ep <= 0.0:
            raise ValueError("Expected EP size must be > 0")

        avg_event_bytes = expected_ep * args.topk * avg_edge_bytes
        lambda_event = target_bytes_per_sec / avg_event_bytes
        n_events_est = int(math.ceil(lambda_event * args.time))

        print(
            f"avg_edge_bytes={avg_edge_bytes:.2f}, expected_ep={expected_ep:.2f}, "
            f"avg_event_bytes={avg_event_bytes:.2f}"
        )
        print(f"Estimated event count ≈ {n_events_est}")

        # Poisson event times.
        crt_time = 0.0
        event_times: List[float] = []
        while crt_time < args.time:
            crt_time += -math.log(1.0 - float(rng.random())) / lambda_event
            event_times.append(crt_time)

        event_times_np = np.array(event_times, dtype=float)
        event_times_np = event_times_np[event_times_np < args.time]
        print(f"Generated {len(event_times_np)} event times")

        for event_gid, t_event in enumerate(event_times_np):
            # Pick a preferred model by weights, then fallback model-by-model if
            # current model cannot satisfy topk destination selection.
            first_idx = int(rng.choice(len(placements), p=m_weights))
            trial_indices = [first_idx] + [i for i in range(len(placements)) if i != first_idx]
            if len(trial_indices) > 1:
                tail = trial_indices[1:]
                rng.shuffle(tail)
                trial_indices = [trial_indices[0]] + tail

            selected: Tuple[int, int] | None = None
            for p_idx in trial_indices:
                p_try = placements[p_idx]
                pp_idx_try = int(next_pp_idx_by_model[p_try.model_id] % len(p_try.pp_groups))
                pp_eps_try = group_endpoints[(p_try.model_id, pp_idx_try)]
                if len(pp_eps_try) <= 1:
                    continue

                feasible = True
                for src_host_try, _ in pp_eps_try:
                    src_host_try = int(src_host_try)
                    cand_eps_try = [ep for ep in pp_eps_try if ep[0] != src_host_try]
                    if len(cand_eps_try) < args.topk:
                        extra_eps_try = [ep for ep in model_endpoints[p_try.model_id] if ep[0] != src_host_try]
                        cand_eps_try.extend(extra_eps_try)
                    if len(cand_eps_try) == 0:
                        feasible = False
                        break
                if feasible:
                    selected = (p_idx, pp_idx_try)
                    break

            if selected is None:
                if args.insufficient_policy == INSUFFICIENT_POLICY_STRICT:
                    raise ValueError(
                        "Insufficient topology/model resources for topk scheduling in one coflow event: "
                        f"event_gid={event_gid}, topk={args.topk}. "
                        "No model can provide enough destination candidates."
                    )
                continue

            p_idx, pp_idx = selected
            p = placements[p_idx]
            next_pp_idx_by_model[p.model_id] = (pp_idx + 1) % len(p.pp_groups)
            event_plan.append((int(event_gid), float(t_event), int(p_idx), int(pp_idx)))
    else:
        if args.infer_groups <= 0:
            raise ValueError(f"infer-groups must be > 0, got {args.infer_groups}")
        if args.infer_interval_ms < 0.0:
            raise ValueError(f"infer-interval-ms must be >= 0, got {args.infer_interval_ms}")
        if args.infer_model_pp1_spread_ms < 0.0:
            raise ValueError(
                f"infer-model-pp1-spread-ms must be >= 0, got {args.infer_model_pp1_spread_ms}"
            )
        if args.infer_pp_jitter_ms < 0.0:
            raise ValueError(f"infer-pp-jitter-ms must be >= 0, got {args.infer_pp_jitter_ms}")

        interval_s = float(args.infer_interval_ms) / 1000.0
        max_pp = max(len(p.pp_groups) for p in placements)
        gid = 0
        for infer_group in range(args.infer_groups):
            group_base_s = float(infer_group) * interval_s
            # Per-group start-time plan:
            # - each model's PP1 starts at a random time in [0, spread] ms
            # - same model PP2..PPn use cumulative jitter in [0, jitter] ms, so PP1 is earliest
            model_pp1_start_s: Dict[str, float] = {}
            model_pp_offsets_s: Dict[str, List[float]] = {}
            for p in placements:
                pp_cnt = len(p.pp_groups)
                pp1_delta_s = float(rng.uniform(0.0, args.infer_model_pp1_spread_ms)) / 1000.0
                model_pp1_start_s[p.model_id] = group_base_s + pp1_delta_s
                offsets = [0.0] * pp_cnt
                acc = 0.0
                for pi in range(1, pp_cnt):
                    acc += float(rng.uniform(0.0, args.infer_pp_jitter_ms)) / 1000.0
                    offsets[pi] = acc
                model_pp_offsets_s[p.model_id] = offsets

            # One inference group: each model's each PP appears exactly once.
            # Order is PP1..PP8 round-robin across models.
            for pp_idx in range(max_pp):
                for p_idx, p in enumerate(placements):
                    if pp_idx < len(p.pp_groups):
                        t_event = model_pp1_start_s[p.model_id] + model_pp_offsets_s[p.model_id][pp_idx]
                        event_plan.append((gid, t_event, p_idx, pp_idx))
                        gid += 1
        print(
            f"Generated inference event plan with startup jitter: "
            f"groups={args.infer_groups}, coflows/group={len(event_plan) // args.infer_groups}, "
            f"total_coflows={len(event_plan)}"
        )

    flows: List[Tuple[int, int, int, int, int]] = []
    total_edge_bytes = 0
    total_remote_bytes = 0
    total_local_bytes = 0
    skipped_events_insufficient = 0

    for event_gid, t_event, p_idx, pp_idx in event_plan:
        p = placements[p_idx]
        pp_eps = group_endpoints[(p.model_id, pp_idx)]

        start_ns = int(round(float(t_event) * 1e9))

        # One EP-group coflow: each src GPU endpoint sends to top-k GPU endpoints.
        # Per EP, the k flows share the same sampled bytes.
        for src_host, _ in pp_eps:
            src_host = int(src_host)
            # Hard constraint: dst GPU must be on a different host than src GPU.
            cand_eps = [ep for ep in pp_eps if ep[0] != src_host]
            if len(cand_eps) < args.topk:
                extra_eps = [ep for ep in model_endpoints[p.model_id] if ep[0] != src_host]
                cand_eps.extend(extra_eps)
            if len(cand_eps) == 0:
                raise ValueError(
                    f"No destination GPU candidates for topk={args.topk}: "
                    f"model={p.model_id}, pp_idx={pp_idx}, src_host={src_host}"
                )
            # topk is defined on GPU endpoints: choose k distinct dst GPUs.
            if len(cand_eps) < args.topk:
                if args.insufficient_policy == INSUFFICIENT_POLICY_STRICT:
                    raise ValueError(
                        f"Not enough distinct dst GPU endpoints for topk={args.topk}: "
                        f"model={p.model_id}, pp_idx={pp_idx}, src_host={src_host}, "
                        f"available={len(cand_eps)}"
                    )
                skipped_events_insufficient += 1
                continue
            dst_pick = rng.choice(len(cand_eps), size=args.topk, replace=False)

            edge_bytes = sample_size_from_cdf(rng, flow_size, flow_cdf)
            total_edge_bytes += edge_bytes * len(dst_pick)
            for di in dst_pick:
                dst_host = int(cand_eps[int(di)][0])
                if dst_host == src_host:
                    raise RuntimeError(
                        "Internal error: selected dst GPU on the same host as src "
                        f"(src_host={src_host}, dst_host={dst_host}, topk={args.topk})"
                    )
                total_remote_bytes += edge_bytes
                flows.append((int(src_host), int(dst_host), int(edge_bytes), start_ns, int(event_gid)))

    # Keep generation order: for each event, emit EP by EP, and each EP emits
    # its topk flows consecutively. This preserves "topk first, then next EP".

    load_residual_bytes = 0
    if args.traffic_mode == TRAFFIC_MODE_LOAD_POISSON and not args.no_last_coflow_adjust:
        flows, load_residual_bytes = adjust_last_coflow_to_target_bytes(
            flows,
            target_total_bytes,
            max_flow_size_bytes=int(np.max(flow_size)),
        )

    total_bytes = sum(f[2] for f in flows)
    dur_fmt = f"{args.time:.3f}"
    if args.traffic_mode == TRAFFIC_MODE_LOAD_POISSON:
        actual_load = total_bytes / (args.time * total_hosts_cluster * linkrate_bytes_s)
        target_pct_tag = build_pct_tag(args.load)
        actual_pct_tag = build_pct_tag(actual_load)
        default_name = (
            f"infer_{args.nrack}racks_{args.hosts_per_rack}c_"
            f"mix{model_mix_tag}_frag{frag_tag}_{target_pct_tag}_actual{actual_pct_tag}_{dur_fmt}s"
        )
    else:
        interval_tag = f"{args.infer_interval_ms:.3f}".rstrip("0").rstrip(".").replace(".", "p")
        default_name = (
            f"infer_{args.nrack}racks_{args.hosts_per_rack}c_"
            f"mix{model_mix_tag}_frag{frag_tag}_ng{args.infer_groups}_int{interval_tag}ms_{dur_fmt}s"
        )
    out_name = args.outfile if args.outfile else default_name
    if out_name.endswith(".htsim"):
        out_path = os.path.join(args.outdir, out_name)
    else:
        out_path = os.path.join(args.outdir, f"{out_name}.htsim")

    write_htsim(flows, out_path, args.coflow_window_ms, args.coflow_mode)

    placement_csv = args.placement_out
    if not placement_csv:
        placement_csv = out_path + ".placement.csv"
    write_placement_csv(placements, placement_csv, args.hosts_per_rack)

    print(f"Total host-level flows = {len(flows)}")
    print(f"Total emitted bytes    = {total_bytes}")
    print(f"Remote bytes ratio     = {total_remote_bytes / max(1, total_edge_bytes):.4f}")
    print(f"Local bytes ratio      = {total_local_bytes / max(1, total_edge_bytes):.4f}")
    if args.traffic_mode == TRAFFIC_MODE_LOAD_POISSON and not args.no_last_coflow_adjust:
        print(f"Last coflow adjust residual bytes = {load_residual_bytes}")
    if args.insufficient_policy == INSUFFICIENT_POLICY_SKIP_MODEL:
        print(f"Skipped events(insufficient-topk) = {skipped_events_insufficient}")
    if args.traffic_mode == TRAFFIC_MODE_LOAD_POISSON:
        print(f"Specified load fraction= {args.load:.3f}")
        print(f"Actual load fraction   = {actual_load:.3f}")
    print(f"Traffic file           = {out_path}")
    print(f"Placement summary      = {placement_csv}")
    print(f"Finished in {time.time() - t0:.2f}s\n")



def main() -> None:
    parser = argparse.ArgumentParser(
        description="Model+fragmentation aware host-level traffic generator (.htsim format)"
    )

    # Keep legacy args for compatibility with existing shell wrappers.
    parser.add_argument("-t", "--topo-name", type=str, required=True)
    parser.add_argument("-r", "--nrack", type=int, required=True)
    parser.add_argument("-c", "--hosts-per-rack", type=int, required=True)
    parser.add_argument("-l", "--load", type=float, default=0.01)
    parser.add_argument("-T", "--time", type=float, default=1.001)
    parser.add_argument("--nics", type=int, default=1)
    parser.add_argument("--nic-rate", type=float, default=100e9, help="bits/s per NIC")
    parser.add_argument("--coflow-window-ms", type=float, default=20.0)
    parser.add_argument(
        "--coflow-mode",
        type=str,
        default=COFLOW_MODE_TIME_WINDOW,
        choices=[COFLOW_MODE_TIME_WINDOW, COFLOW_MODE_ALL2ALLV_EVENT],
        help="coflow group id policy: time-window or per-all2allv-event",
    )
    parser.add_argument(
        "--traffic-mode",
        type=str,
        default=TRAFFIC_MODE_LOAD_POISSON,
        choices=[TRAFFIC_MODE_LOAD_POISSON, TRAFFIC_MODE_INFER_GROUPS],
        help="traffic event generation mode: load-driven Poisson or fixed inference groups",
    )
    parser.add_argument("--workload", type=str, required=True)
    parser.add_argument("--outdir", type=str, required=True)

    # New knobs.
    parser.add_argument("--gpus-per-host", type=int, default=8)
    parser.add_argument("--model-mix", type=str, default=DEFAULT_MODEL_MIX)
    parser.add_argument("--frag-level", type=float, default=DEFAULT_FRAG_LEVEL, help="target fragmentation in [0,1]")
    parser.add_argument("--topk", type=int, default=8)
    parser.add_argument("--infer-groups", type=int, default=1, help="number of inference groups in infer_groups mode")
    parser.add_argument("--infer-interval-ms", type=float, default=20.0, help="interval(ms) between inference groups")
    parser.add_argument(
        "--infer-model-pp1-spread-ms",
        type=float,
        default=100.0,
        help="for infer_groups mode: each model PP1 starts at random in [0, spread] ms",
    )
    parser.add_argument(
        "--infer-pp-jitter-ms",
        type=float,
        default=5.0,
        help="for infer_groups mode: cumulative per-PP jitter step in [0, jitter] ms (PP1 earliest)",
    )
    parser.add_argument("--model-weight", type=str, default="hosts", choices=["hosts", "uniform"])
    parser.add_argument(
        "--insufficient-policy",
        type=str,
        default=INSUFFICIENT_POLICY_STRICT,
        choices=[INSUFFICIENT_POLICY_STRICT, INSUFFICIENT_POLICY_SKIP_MODEL],
        help="Behavior when a coflow event cannot find enough destination candidates.",
    )
    parser.add_argument(
        "--no-last-coflow-adjust",
        action="store_true",
        help="Disable final load matching by adjusting the last coflow.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--outfile", type=str, default="", help="basename or .htsim filename")
    parser.add_argument("--placement-out", type=str, default="", help="placement csv output path")

    args = parser.parse_args()

    if not (0.0 <= args.frag_level <= 1.0):
        raise ValueError(f"frag-level must be in [0,1], got {args.frag_level}")
    if args.topk <= 0:
        raise ValueError(f"topk must be > 0, got {args.topk}")
    if args.nrack <= 0 or args.hosts_per_rack <= 0 or args.gpus_per_host <= 0:
        raise ValueError("nrack/hosts-per-rack/gpus-per-host must be > 0")

    generate_model_fragmented_traffic(args)


if __name__ == "__main__":
    main()
