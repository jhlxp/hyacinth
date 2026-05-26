# Solve-Time Plot Pipeline

This folder benchmarks all 10 schedulers using `route_trace_dep_injector`, then plots solve time only.

## Files

- `run_10alg_solve_time.py`
  - Runs 10 schedulers with fixed topology mapping.
  - Writes per-scheduler logs and routed traffic outputs.
  - Calls `plot_solve_time.py` by default.
- `plot_solve_time.py`
  - Parses logs and draws one bar chart: `Avg Solve Time (ms)`.
  - Reuses order/color style from `plot_baseline_summary.py`.

## Topology Mapping

- `n80_k8_c8_eps0.txt`:
  - `pure_ocs_ksp`
  - `pure_ocs_ksp_greedy`
  - `pure_ocs_pruned`
- `n80_k7_c8_eps1.txt`:
  - `ocs_eps_pruned`
  - `ocs_eps_large_small`
  - `ocs_eps_global_ksp`
  - `ocs_eps_preset_greedy`
  - `ocs_eps_preset_dynamic_greedy`
- `n80_k0_c8_eps8.txt`:
  - `eps_ecmp`

## Usage

```bash
python3 /home/xuheng/Desktop/ToN2026/htsim/traffic_route_injector_cpp/plot/run_10alg_solve_time.py \
  --traffic_in /path/to/trace_dep.txt
```

If you want topology-specific traffic files:

```bash
python3 /home/xuheng/Desktop/ToN2026/htsim/traffic_route_injector_cpp/plot/run_10alg_solve_time.py \
  --traffic_eps0 /path/to/traffic_eps0.txt \
  --traffic_eps1 /path/to/traffic_eps1.txt \
  --traffic_eps8 /path/to/traffic_eps8.txt
```

Outputs are under:

- `.../plot/runs/run_<timestamp>/logs`
- `.../plot/runs/run_<timestamp>/summary/solve_time_summary.csv`
- `.../plot/runs/run_<timestamp>/summary/solve_time_summary.md`
- `.../plot/runs/run_<timestamp>/summary/solve_time_summary.png`

## Notes

- `traffic_in` must be legacy trace_dep format:
  - `src dst bytes comp_us group [deps...|-]`
- Solve-time plot uses average per coflow:
  - `avg_solve_time_ms = solveTimeMs / numSolveCalls`
