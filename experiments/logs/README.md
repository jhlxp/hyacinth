# experiments/logs

Per-simulator experiment records.

- `flat/`
  - `run_<timestamp>/`: one folder per experiment
- `flat_dep/`
  - `run_<timestamp>/`: one folder per experiment

Each experiment folder should contain:

- `native_traffic/`
- `transformed_traffic/`
- `route_logs/`
- `sim_logs/`
- `summary/`

Use `/home/xuheng/Desktop/ToN2026/htsim/experiments/scripts/run_10alg_solve_time.py` to create new timestamped run folders automatically.
