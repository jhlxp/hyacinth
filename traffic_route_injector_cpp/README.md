# traffic_route_injector_cpp

Pure C++ traffic route injector for `htsim`.

## Goal

Keep all existing scheduler core logic (10 algorithms) unchanged, and only add a new interface:

- Input: legacy `trace_dep`
  - `src dst bytes comp_us group [deps...|-]`
- Output: routed `trace_dep`
  - `src dst bytes comp_us group [deps...|-] path=tor0,tor1,...`

## Key Points

- Scheduler implementations are reused directly from original C++ code.
- New binary: `bin/route_trace_dep_injector`

## Build

```bash
cd /home/xuheng/Desktop/ToN2026/htsim/traffic_route_injector_cpp
make -j
```

## Run

```bash
/home/xuheng/Desktop/ToN2026/htsim/traffic_route_injector_cpp/bin/route_trace_dep_injector \
  --topo_file /path/to/topology.txt \
  --traffic_in /path/to/legacy_trace_dep.txt \
  --traffic_out /path/to/routed_trace_dep.txt \
  --num_tor 80 \
  --num_eps 1 \
  --rate_tor_tor 12500000000 \
  --rate_tor_eps 12500000000 \
  --scheduler ocs_eps_preset_dynamic_greedy
```

Optional scheduler knobs are the same as original:

- `--ksp_k`
- `--max_hops`
- `--max_candidates`
- `--small_flow_mode`
- `--small_flow_threshold`

## Solve-Time Plot

Use scripts under [`plot/`](/home/xuheng/Desktop/ToN2026/htsim/traffic_route_injector_cpp/plot):

- Run 10 schedulers and generate summary:
  - `python3 plot/run_10alg_solve_time.py --traffic_in /path/to/trace_dep.txt`
- Plot only from existing logs:
  - `python3 plot/plot_solve_time.py --log_dir /path/to/logs --out_png /path/to/solve_time.png`
