# Threshold Sweep Experiment

## Motivation

The paper's headline improvement (75.8%) comes from comparing against a fixed-threshold hybrid baseline (Helios-20%). Reviewers may question whether the 20% threshold is a strawman. This experiment sweeps the EPS threshold percentage across multiple values for both Helios and Hyacinth-preset, then compares against Hyacinth-dynamic (which needs no threshold) to demonstrate that **dynamic threshold selection consistently outperforms any fixed threshold**.

## Experiment Design

### Schedulers & Thresholds

| Run | Scheduler | CLI Name | Threshold | Description |
|-----|-----------|----------|-----------|-------------|
| 1 | Helios | `ocs_eps_large_small` | 10% | Small-flow split, 10% bytes → EPS |
| 2 | Helios | `ocs_eps_large_small` | 20% | Small-flow split, 20% bytes → EPS |
| 3 | Helios | `ocs_eps_large_small` | 30% | Small-flow split, 30% bytes → EPS |
| 4 | Helios | `ocs_eps_large_small` | 40% | Small-flow split, 40% bytes → EPS |
| 5 | Helios | `ocs_eps_large_small` | 50% | Small-flow split, 50% bytes → EPS |
| 6 | Helios | `ocs_eps_large_small` | 60% | Small-flow split, 60% bytes → EPS |
| 7 | Helios | `ocs_eps_large_small` | 70% | Small-flow split, 70% bytes → EPS |
| 8 | Helios | `ocs_eps_large_small` | 80% | Small-flow split, 80% bytes → EPS |
| 9 | Helios | `ocs_eps_large_small` | 90% | Small-flow split, 90% bytes → EPS |
| 10 | Hyacinth-preset | `ocs_eps_preset_greedy` | 10% | Greedy with 10% EPS tail |
| 11 | Hyacinth-preset | `ocs_eps_preset_greedy` | 20% | Greedy with 20% EPS tail |
| 12 | Hyacinth-preset | `ocs_eps_preset_greedy` | 30% | Greedy with 30% EPS tail |
| 13 | Hyacinth-preset | `ocs_eps_preset_greedy` | 40% | Greedy with 40% EPS tail |
| 14 | Hyacinth-preset | `ocs_eps_preset_greedy` | 50% | Greedy with 50% EPS tail |
| 15 | Hyacinth-preset | `ocs_eps_preset_greedy` | 60% | Greedy with 60% EPS tail |
| 16 | Hyacinth-preset | `ocs_eps_preset_greedy` | 70% | Greedy with 70% EPS tail |
| 17 | Hyacinth-preset | `ocs_eps_preset_greedy` | 80% | Greedy with 80% EPS tail |
| 18 | Hyacinth-preset | `ocs_eps_preset_greedy` | 90% | Greedy with 90% EPS tail |
| 19 | Hyacinth-dynamic | `ocs_eps_preset_dynamic_greedy` | — | Dynamic OCS/EPS selection |

**Total: 190 htsim simulations** (19 scheduler configs × 10 seeds)

### Base Case Configuration (matches 40tor mix base case)

- **Topology**: 40 racks, degree=4 (OCS=3, EPS=1), 8 hosts/rack, 8 GPUs/host
- **Traffic**: mix=3L,2M,1S, frag=0.5, seed=42, workload=fbcoco.csv
- **Inference**: 1 group, interval=50ms, PP1 spread=100ms, PP jitter=5ms
- **Simulation**: htsim Bolt, simtime=20, q=200

### Key Parameters

- `--small_flow_mode percent` — threshold is a percentage of coflow bytes
- `--small_flow_threshold X` — X% of bytes go to EPS (for fixed-threshold schedulers)
- For `ocs_eps_preset_dynamic_greedy`, threshold is ignored; the scheduler dynamically decides OCS/EPS per flow

## Output Structure

```
experiments/expe_logs_threshold_sweep/threshold_sweep/batch_<timestamp>/
├── shared_traffic/                          # Generated traffic (shared)
├── results/
│   ├── helios_t10/                          # Helios threshold=10%
│   │   ├── route_logs/
│   │   ├── transformed_traffic/
│   │   ├── sim_logs/
│   │   └── summary/
│   ├── helios_t20/                          # Helios threshold=20%
│   ├── helios_t30/                          # Helios threshold=30%
│   ├── helios_t40/                          # Helios threshold=40%
│   ├── helios_t50/                          # Helios threshold=50%
│   ├── helios_t60/                          # Helios threshold=60%
│   ├── helios_t70/                          # Helios threshold=70%
│   ├── helios_t80/                          # Helios threshold=80%
│   ├── helios_t90/                          # Helios threshold=90%
│   ├── hyacinth_preset_t10/                 # Hyacinth-preset threshold=10%
│   ├── hyacinth_preset_t20/                 # Hyacinth-preset threshold=20%
│   ├── hyacinth_preset_t30/                 # Hyacinth-preset threshold=30%
│   ├── hyacinth_preset_t40/                 # Hyacinth-preset threshold=40%
│   ├── hyacinth_preset_t50/                 # Hyacinth-preset threshold=50%
│   ├── hyacinth_preset_t60/                 # Hyacinth-preset threshold=60%
│   ├── hyacinth_preset_t70/                 # Hyacinth-preset threshold=70%
│   ├── hyacinth_preset_t80/                 # Hyacinth-preset threshold=80%
│   ├── hyacinth_preset_t90/                 # Hyacinth-preset threshold=90%
│   └── hyacinth_dynamic/                    # Hyacinth-dynamic (no threshold)
├── sim_logs_combined/                       # Merged sim logs for plotting
├── route_logs_combined/                     # Merged route logs for plotting
├── plots/
│   ├── solve_time_summary.png
│   ├── fct_vs_bytes_curve.png
│   ├── fct_avg_relative_summary.png         # Relative to dynamic
│   └── coflow_*_relative_*.png              # P100/P99/P95/AVG relative to dynamic
└── batch_summary.csv
```

## Running

```bash
cd /home/xuheng/hyacinth/experiments/expe_sh_threshold_sweep
bash run_threshold_sweep.sh
```

For the 80tor base case, use the separate script:

```bash
cd /home/xuheng/hyacinth/experiments/expe_sh_threshold_sweep
bash run_threshold_sweep_80tor.sh
```

It writes to the same parent directory, `experiments/expe_logs_threshold_sweep/threshold_sweep/`, with a timestamped batch tag ending in `_threshold_sweep_80tor`.

### Optional Overrides

```bash
# Use different seed
TRAFFIC_SEED=123 bash run_threshold_sweep.sh

# Limit parallelism
MAX_JOBS=100 bash run_threshold_sweep.sh

# Custom batch tag
BATCH_TAG=my_threshold_test bash run_threshold_sweep.sh
```

## Expected Outcome

The experiment should demonstrate that:

1. **No single fixed threshold is universally optimal** — different thresholds favor different metrics (FCT vs CCT, tail vs average)
2. **Helios-20% is not a strawman** — even the best fixed threshold for Helios underperforms dynamic
3. **Hyacinth-dynamic consistently matches or beats the best fixed threshold** across all metrics, without requiring threshold tuning
4. **The improvement of dynamic over fixed-threshold baselines is robust** regardless of the chosen threshold percentage
