# htsim/plot

Plotting scripts for HTSIM experiments.

## Files

- `plot_solve_time.py`
  - Parse injector logs and draw solve-time bar chart
- `plot_fct_vs_bytes.py`
  - Plot bytes-vs-FCT curves from simulator logs
- `plot_fct_avg_relative_bar.py`
  - Build bar chart from `fct_vs_bytes_curve.csv`
  - Normalize to `ocs_eps_preset_dynamic_greedy = 1`
  - Average relative FCT across bytes bins per scheduler
- `plot_traffic_coflow_timeline.py`
  - Plot traffic coflow start distribution: `x=time`, `y=model`, color by `PP=1..8`

Manual plotting from an existing log folder:

```bash
python3 /home/xuheng/Desktop/ToN2026/htsim/plot/plot_solve_time.py \
  --log_dir /path/to/route_logs \
  --out_csv /path/to/summary.csv \
  --out_md /path/to/summary.md \
  --out_png /path/to/summary.png
```

For experiment execution (route injection + summary + plot), use:

- `/home/xuheng/Desktop/ToN2026/htsim/experiments/scripts/run_10alg_solve_time.py`

Manual traffic timeline plotting from generated `infer_*.htsim`:

```bash
python3 /home/xuheng/Desktop/ToN2026/htsim/plot/plot_traffic_coflow_timeline.py \
  --traffic_file /path/to/infer_xxx.htsim \
  --placement_file /path/to/infer_xxx.htsim.placement.csv \
  --out_png /path/to/coflow_timeline.png \
  --out_csv /path/to/coflow_timeline.csv \
  --time_unit s
```
