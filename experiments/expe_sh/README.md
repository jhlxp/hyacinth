# expe_sh Usage

This folder contains standalone sweep scripts for the 5 main inference experiment dimensions.

## Scripts

- `mix/run_mix_sweep.sh`
  - Sweep `TRAFFIC_MODEL_MIX`: `4L,3M,3S`, `10L`, `20S` (80 racks)
- `frag/run_frag_sweep.sh`
  - Sweep `TRAFFIC_FRAG_LEVEL`: `0.1, 0.3, 0.5, 0.7, 0.9`
- `start_spread/run_start_spread_sweep.sh`
  - Sweep model PP1 start spread window: `0, 25, 50, 75, 100 ms` (`100 ms` as base)
- `topo/run_topo_sweep.sh`
  - Sweep topology size + matching mix:
    - `20 racks -> 1L,1M,1S`
    - `40 racks -> 3L,2M,1S`
    - `80 racks -> 4L,3M,3S`
- `workload/run_workload_sweep.sh`
  - Sweep CDF workload: `fbcoco`, `datamining`, `websearch`, `boltrpc`

## Fixed Baseline Knobs

All 5 scripts use:

- `TRAFFIC_COFLOW_MODE=all2allv_event`
- `TRAFFIC_MODE=infer_groups`
- `TRAFFIC_INFER_GROUPS=1`
- `TRAFFIC_INFER_INTERVAL_MS=50`
- `TRAFFIC_TOPK=8`
- `TRAFFIC_SEED=42`
- `FLAT_SIMTIME=100`
- `FLAT_Q=200`
- `SMALL_FLOW_THRESHOLD=20.0` (percent mode)
- 10 schedulers, parallel cap `MAX_JOBS=10` by default

## Topology Degree Rule

Implemented in scripts:

- `nrack=80`: total degree = 8
- `nrack=20/40`: total degree = 4
- invariant: `OCS_degree + EPS_count = total_degree`

Hence for each `nrack`, scripts use:

- pure OCS: `k=total_degree, eps=0`
- OCS+EPS: `k=total_degree-1, eps=1`
- EPS ECMP: `k=0, eps=total_degree`

Missing topology files are auto-generated into `experiments/topology`.

## Output Logs

All outputs are under:

- `experiments/expe_logs/<type>/batch_<timestamp>_<type>/...`

Each case has:

- `native_traffic/`
- `transformed_traffic/`
- `route_logs/`
- `sim_logs/`
- `summary/` (manifest + plots)

## Run Examples

```bash
cd /home/xuheng/Desktop/ToN2026/hyacinth/experiments/expe_sh
bash mix/run_mix_sweep.sh
bash frag/run_frag_sweep.sh
bash start_spread/run_start_spread_sweep.sh
bash topo/run_topo_sweep.sh
bash workload/run_workload_sweep.sh
```

Optional overrides:

```bash
MAX_JOBS=10 AUTO_BUILD=1 bash mix/run_mix_sweep.sh
SCHEDULERS="ocs_eps_pruned,eps_ecmp" bash start_spread/run_start_spread_sweep.sh
```
