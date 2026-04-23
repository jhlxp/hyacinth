# experiments/scripts

Flat experiments (10 schedulers) shell runners.

## Main scripts

- `run_flat_10alg_30pct.sh`
  - Baseline traffic (30%, 10s) one-stop run:
    - optional traffic generation
    - route injection for 10 schedulers
    - flat simulation (parallel)
    - plots:
      - solve time
      - FCT vs bytes curve
      - avg relative FCT bar (`dynamic=1`)

- `run_infer_80racks_8c_mix4L3M3S_frag0p5_50pct_actual50pct_1.000s.sh`
  - Infer traffic one-stop run:
    - auto-generate infer traffic if missing
    - route injection for 10 schedulers
    - flat simulation (parallel)
    - plots:
      - solve time
      - FCT vs bytes curve
      - avg relative FCT bar (`dynamic=1`)
      - traffic timeline (when placement CSV exists)

- `plot_run_outputs.sh`
  - Re-plot from an existing `run_dir` without re-running simulation.

## Default output

- `/home/xuheng/Desktop/ToN2026/hyacinth/experiments/logs/flat/run_<timestamp>_.../`

## Examples

Run baseline:

```bash
bash /home/xuheng/Desktop/ToN2026/hyacinth/experiments/scripts/run_flat_10alg_30pct.sh
```

Run infer:

```bash
bash /home/xuheng/Desktop/ToN2026/hyacinth/experiments/scripts/run_infer_80racks_8c_mix4L3M3S_frag0p5_50pct_actual50pct_1.000s.sh
```

Only re-plot an existing run:

```bash
bash /home/xuheng/Desktop/ToN2026/hyacinth/experiments/scripts/plot_run_outputs.sh
```
