# expe_fig

This folder contains section-level figure scripts for the 10-seed experiment summary.

## Goals

- Use cross-seed data (`seed_avg_summary`) instead of single-seed special cases.
- Support per-algorithm on/off control via `algorithm_switches.py`.
- Produce multiple figures per experiment section (bar + CDF).
- Save plotting prints into `.log` files for later analysis writing.

## Layout

- `algorithm_switches.py`
  - Toggle each scheduler `True/False`.
- `rebuild_seed_avg.py`
  - Rebuilds `batch_summary_rebuilt_selected_cases.csv` from case `seed_*` folders.
  - Calls `plot/aggregate_seed_summaries.py` to refresh `seed_avg_summary`.
- `common_plot.py`
  - Shared plotting and CSV utilities.
- `<section>/plot_<section>.py`
  - One script per experiment class (isolated by folder):
    - `frag/plot_frag.py`
    - `mix/plot_mix.py`
    - `start_spread/plot_start_spread.py`
    - `topo/plot_topo.py`
    - `workload/plot_workload.py`
  - Outputs:
    - `<section>/figures/*.png`
    - `<section>/figures/<section>.log`
- `run_all_expe_fig.sh`
  - Rebuild all scenario-level seed summaries and then draw all section figures.

## Run

```bash
cd /home/xuheng/Desktop/ToN2026/hyacinth
bash plot/expe_fig/run_all_expe_fig.sh
```

Outputs:

- Figures: `plot/expe_fig/<section>/figures/*.png`
- Logs: `plot/expe_fig/<section>/figures/<section>.log`
