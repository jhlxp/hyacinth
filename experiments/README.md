# experiments

All experiment records are stored under `experiments/logs`.

## Layout

- `scripts/`: experiment runner scripts
- `logs/flat/`
  - `run_<timestamp>/`: one folder per experiment
- `logs/flat_dep/`
  - `run_<timestamp>/`: one folder per experiment
- `topology/`: topology files used by experiments

## Rule

Each experiment run should create a new timestamped folder under:

- `experiments/logs/flat/` or
- `experiments/logs/flat_dep/`

Each run folder should contain:

- `native_traffic/`
- `transformed_traffic/`
- `route_logs/`
- `sim_logs/`
- `summary/`

Runner entrypoint:

- `/home/xuheng/Desktop/ToN2026/htsim/experiments/scripts/run_10alg_solve_time.py`
