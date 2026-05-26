#!/usr/bin/env bash
set -u
set -o pipefail

# =============================================================================
# Threshold Sweep Experiment (10-round multi-seed)
# =============================================================================
# Goal: Compare Helios (fixed-threshold large/small), Hyacinth-preset (fixed-
# threshold greedy), and Hyacinth-dynamic across EPS-threshold percentages,
# with 10 seeds for statistical robustness.
#
# 19 scheduler configs × 10 seeds = 190 htsim runs
#   Helios (ocs_eps_large_small)     threshold = 10%, 20%, ..., 90%
#   Hyacinth-preset (ocs_eps_preset_greedy) threshold = 10%, 20%, ..., 90%
#   Hyacinth-dynamic (ocs_eps_preset_dynamic_greedy) — no threshold, 1 run
#
# Base case: 40-rack, mix=3L,2M,1S, frag=0.5, workload=fbcoco.csv
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTSIM_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

EXPERIMENT_TYPE="threshold_sweep"
BATCH_TAG="${BATCH_TAG:-batch_$(date +%Y%m%d_%H%M%S)_${EXPERIMENT_TYPE}}"
BATCH_DIR="$HTSIM_ROOT/experiments/expe_logs_threshold_sweep/${EXPERIMENT_TYPE}/$BATCH_TAG"
mkdir -p "$BATCH_DIR"

INJECTOR_DIR="$HTSIM_ROOT/traffic_route_injector_cpp"
FLAT_DIR="$HTSIM_ROOT/src/flat"
INJECTOR_BIN="${INJECTOR_BIN:-$INJECTOR_DIR/bin/route_trace_dep_injector}"
FLAT_BIN="${FLAT_BIN:-$FLAT_DIR/run/htsim_bolt_flat}"
TOPO_GEN_PY="${TOPO_GEN_PY:-$HTSIM_ROOT/topology/expander_eps.py}"
TRAFFIC_GEN_PY="${TRAFFIC_GEN_PY:-$HTSIM_ROOT/traffic_gene/generate_traffic_model_frag.py}"

PLOT_SOLVE_TIME="${PLOT_SOLVE_TIME:-$HTSIM_ROOT/plot/plot_solve_time.py}"
PLOT_FCT_BYTES="${PLOT_FCT_BYTES:-$HTSIM_ROOT/plot/plot_fct_vs_bytes.py}"
PLOT_FCT_AVG_REL="${PLOT_FCT_AVG_REL:-$HTSIM_ROOT/plot/plot_fct_avg_relative_bar.py}"
PLOT_COFLOW_AVG_REL="${PLOT_COFLOW_AVG_REL:-$HTSIM_ROOT/plot/plot_coflow_avg_relative_bar.py}"
PLOT_AGG_SEED="${PLOT_AGG_SEED:-$HTSIM_ROOT/plot/aggregate_seed_summaries.py}"

FLOW_DISTR_DIR="$HTSIM_ROOT/traffic_gene/flow_distr"
BASE_WORKLOAD="$FLOW_DISTR_DIR/fbcoco.csv"
TOPO_DIR="$HTSIM_ROOT/experiments/topology"

# Fixed baseline knobs (same as 40tor mix base case)
HOSTS_PER_RACK=8
GPUS_PER_HOST=8
NRACK=40
MODEL_MIX="3L,2M,1S"
FRAG=0.5
LOAD=0.5
WORKLOAD="$BASE_WORKLOAD"

TRAFFIC_TOPO_NAME="dc"
TRAFFIC_DURATION_SEC=1.000
TRAFFIC_COFLOW_WINDOW_MS=20
TRAFFIC_COFLOW_MODE="all2allv_event"
TRAFFIC_MODE="infer_groups"
TRAFFIC_INFER_GROUPS=1
TRAFFIC_INFER_INTERVAL_MS=50
TRAFFIC_INFER_MODEL_PP1_SPREAD_MS=100
TRAFFIC_INFER_PP_JITTER_MS=5
TRAFFIC_NICS=1
TRAFFIC_NIC_RATE=100e9
TRAFFIC_TOPK=8
TRAFFIC_MODEL_WEIGHT="hosts"
TRAFFIC_INSUFFICIENT_POLICY="strict"

TRAFFIC_SEED_START="${TRAFFIC_SEED_START:-42}"
TRAFFIC_SEED_END="${TRAFFIC_SEED_END:-51}"

RATE_TOR_TOR=12500000000.0
RATE_TOR_EPS=12500000000.0
KSP_K=4
MAX_HOPS=5
MAX_CANDIDATES=20

FLAT_SIMTIME=20
FLAT_UTILTIME=0.02
FLAT_Q=200

# Run up to 100 htsim jobs in parallel by default.
MAX_JOBS="${MAX_JOBS:-100}"

# Threshold sweep values (percentage of bytes to EPS)
THRESHOLD_VALUES=(10 20 30 40 50 60 70 80 90)

# =============================================================================
# Helper functions
# =============================================================================

join_by_comma() {
  local IFS=","
  echo "$*"
}

require_file() {
  local p="$1"
  local what="$2"
  if [[ ! -f "$p" ]]; then
    echo "[fatal] missing $what: $p" >&2
    exit 1
  fi
}

total_degree_for_nrack() {
  local nrack="$1"
  case "$nrack" in
    80) echo "8" ;;
    20|40) echo "4" ;;
    *)
      echo "[fatal] unsupported nrack: $nrack" >&2
      return 1
      ;;
  esac
}

ensure_topology_file() {
  local nrack="$1"
  local k="$2"
  local eps="$3"
  local out_file="$4"

  if [[ -f "$out_file" ]]; then
    return 0
  fi

  echo "[topology] generating missing $(basename "$out_file")"
  python3 "$TOPO_GEN_PY" \
    -n "$nrack" \
    -k "$k" \
    -c "$HOSTS_PER_RACK" \
    --eps "$eps" \
    --seed 42 \
    --topo_dir "$TOPO_DIR" \
    --filename "$(basename "$out_file")" \
    > "$BATCH_DIR/topology_gen_n${nrack}_k${k}_eps${eps}.log" 2>&1

  if [[ ! -f "$out_file" ]]; then
    echo "[fatal] failed to generate topology: $out_file" >&2
    exit 1
  fi
}

# =============================================================================
# Step 1: Ensure topology file (shared across all runs, eps1)
# =============================================================================

echo "=== Step 1: Ensure topology files ==="

total_degree="$(total_degree_for_nrack "$NRACK")" || exit 1
hybrid_ocs_degree=$((total_degree - 1))
eps_count="$total_degree"

TOPO_EPS1="$TOPO_DIR/n${NRACK}_k${hybrid_ocs_degree}_c8_eps1.txt"
ensure_topology_file "$NRACK" "$hybrid_ocs_degree" 1 "$TOPO_EPS1"
echo "[topology] using $TOPO_EPS1"

# =============================================================================
# Step 2: Define scheduler configurations
# =============================================================================

echo "=== Step 2: Define scheduler configurations ==="

# Build run list: each entry is "scheduler_name threshold_tag threshold_value"
RUN_SCHEDS=()
RUN_THRESH_TAGS=()
RUN_THRESH_VALUES=()

# Helios (ocs_eps_large_small) with threshold sweep
for thresh in "${THRESHOLD_VALUES[@]}"; do
  RUN_SCHEDS+=("ocs_eps_large_small")
  RUN_THRESH_TAGS+=("helios_t${thresh}")
  RUN_THRESH_VALUES+=("$thresh")
done

# Hyacinth-preset (ocs_eps_preset_greedy) with threshold sweep
for thresh in "${THRESHOLD_VALUES[@]}"; do
  RUN_SCHEDS+=("ocs_eps_preset_greedy")
  RUN_THRESH_TAGS+=("hyacinth_preset_t${thresh}")
  RUN_THRESH_VALUES+=("$thresh")
done

# Hyacinth-dynamic (ocs_eps_preset_dynamic_greedy) — no threshold
RUN_SCHEDS+=("ocs_eps_preset_dynamic_greedy")
RUN_THRESH_TAGS+=("hyacinth_dynamic")
RUN_THRESH_VALUES+=("0")  # placeholder, not used

echo "[config] ${#RUN_SCHEDS[@]} scheduler configs defined:"
for ((i=0; i<${#RUN_SCHEDS[@]}; ++i)); do
  echo "  [$i] scheduler=${RUN_SCHEDS[$i]}, tag=${RUN_THRESH_TAGS[$i]}, threshold=${RUN_THRESH_VALUES[$i]}"
done

# =============================================================================
# Step 3: Build full run matrix
# =============================================================================

echo "=== Step 3: Build run matrix ==="

FULL_SCHEDS=()
FULL_THRESH_TAGS=()
FULL_THRESH_VALUES=()
FULL_SEEDS=()
SEED_COUNT=$((TRAFFIC_SEED_END - TRAFFIC_SEED_START + 1))

for ((s=0; s<${#RUN_SCHEDS[@]}; ++s)); do
  for seed in $(seq "$TRAFFIC_SEED_START" "$TRAFFIC_SEED_END"); do
    FULL_SCHEDS+=("${RUN_SCHEDS[$s]}")
    FULL_THRESH_TAGS+=("${RUN_THRESH_TAGS[$s]}")
    FULL_THRESH_VALUES+=("${RUN_THRESH_VALUES[$s]}")
    FULL_SEEDS+=("$seed")
  done
done

echo "[config] ${#FULL_SCHEDS[@]} total runs (${#RUN_SCHEDS[@]} scheduler configs × ${SEED_COUNT} seeds)"
echo "[config] MAX_JOBS=$MAX_JOBS"

# =============================================================================
# Step 4: Run injector + htsim configurations in parallel
# =============================================================================

echo "=== Step 4: Run injector + htsim for each configuration ==="

require_file "$INJECTOR_BIN" "injector binary"
require_file "$FLAT_BIN" "flat simulator binary"
require_file "$TOPO_EPS1" "topology file"

RESULTS_DIR="$BATCH_DIR/results"
mkdir -p "$RESULTS_DIR"

BATCH_SUMMARY="$BATCH_DIR/batch_summary.csv"
echo "scheduler,threshold_tag,threshold_pct,seed,num_eps,topo_file,traffic_in,status,run_dir" > "$BATCH_SUMMARY"

run_one_config() {
  local idx="$1"
  local scheduler="${FULL_SCHEDS[$idx]}"
  local thresh_tag="${FULL_THRESH_TAGS[$idx]}"
  local thresh_value="${FULL_THRESH_VALUES[$idx]}"
  local seed="${FULL_SEEDS[$idx]}"
  local num_eps=1

  local run_dir="$RESULTS_DIR/${thresh_tag}/seed_${seed}"
  local route_logs_dir="$run_dir/route_logs"
  local native_traffic_dir="$run_dir/native_traffic"
  local transformed_dir="$run_dir/transformed_traffic"
  local sim_logs_dir="$run_dir/sim_logs"
  local summary_dir="$run_dir/summary"
  local mplconfigdir="$run_dir/.mplconfig"

  mkdir -p "$route_logs_dir" "$native_traffic_dir" "$transformed_dir" "$sim_logs_dir" "$summary_dir" "$mplconfigdir"

  # Generate traffic for this seed
  local traffic_case_tag="mix3L2M1S_seed${seed}"
  local traffic_base="infer_${traffic_case_tag}_${NRACK}racks"
  local traffic_in="$native_traffic_dir/${traffic_base}.htsim"

  if [[ ! -f "$traffic_in" ]]; then
    python3 "$TRAFFIC_GEN_PY" \
      -t "$TRAFFIC_TOPO_NAME" \
      -r "$NRACK" \
      -c "$HOSTS_PER_RACK" \
      -T "$TRAFFIC_DURATION_SEC" \
      --coflow-window-ms "$TRAFFIC_COFLOW_WINDOW_MS" \
      --coflow-mode "$TRAFFIC_COFLOW_MODE" \
      --traffic-mode "$TRAFFIC_MODE" \
      --infer-groups "$TRAFFIC_INFER_GROUPS" \
      --infer-interval-ms "$TRAFFIC_INFER_INTERVAL_MS" \
      --infer-model-pp1-spread-ms "$TRAFFIC_INFER_MODEL_PP1_SPREAD_MS" \
      --infer-pp-jitter-ms "$TRAFFIC_INFER_PP_JITTER_MS" \
      --nics "$TRAFFIC_NICS" \
      --nic-rate "$TRAFFIC_NIC_RATE" \
      --workload "$WORKLOAD" \
      --outdir "$native_traffic_dir" \
      --gpus-per-host "$GPUS_PER_HOST" \
      --model-mix "$MODEL_MIX" \
      --frag-level "$FRAG" \
      --topk "$TRAFFIC_TOPK" \
      --model-weight "$TRAFFIC_MODEL_WEIGHT" \
      --insufficient-policy "$TRAFFIC_INSUFFICIENT_POLICY" \
      --seed "$seed" \
      --outfile "$traffic_base" \
      > "$native_traffic_dir/traffic_generate.log" 2>&1

    if [[ ! -f "$traffic_in" ]]; then
      echo "[fatal] traffic generation failed for seed=$seed" >&2
      return 1
    fi
  fi

  local out_traffic="$transformed_dir/traffic_routed.${thresh_tag}.txt"
  local route_log="$route_logs_dir/${thresh_tag}.log"
  local sim_log="$sim_logs_dir/${thresh_tag}.log"
  local sim_stdout="$sim_logs_dir/${thresh_tag}.stdout.txt"
  local sim_stderr="$sim_logs_dir/${thresh_tag}.stderr.txt"
  local status_file="$summary_dir/status.tsv"

  echo "[start] $thresh_tag seed=$seed (scheduler=$scheduler, threshold=$thresh_value)"

  # Build injector command
  local inject_cmd=(
    "$INJECTOR_BIN"
    --topo_file "$TOPO_EPS1"
    --traffic_in "$traffic_in"
    --traffic_out "$out_traffic"
    --num_tor "$NRACK"
    --num_eps "$num_eps"
    --rate_tor_tor "$RATE_TOR_TOR"
    --rate_tor_eps "$RATE_TOR_EPS"
    --scheduler "$scheduler"
    --ksp_k "$KSP_K"
    --max_hops "$MAX_HOPS"
    --max_candidates "$MAX_CANDIDATES"
    --small_flow_mode "percent"
    --small_flow_threshold "$thresh_value"
  )

  {
    echo "\$ ${inject_cmd[*]}"
    "${inject_cmd[@]}"
  } > "$route_log" 2>&1
  local inject_rc=$?

  local status="ok"
  if [[ $inject_rc -ne 0 ]]; then
    status="inject_failed"
    : > "$sim_log"
    : > "$sim_stdout"
    : > "$sim_stderr"
  else
    # Run htsim simulation
    local sim_cmd=(
      "$FLAT_BIN"
      -flowfile "$out_traffic"
      -topfile "$TOPO_EPS1"
      -outputfile "$sim_log"
      -simtime "$FLAT_SIMTIME"
      -utiltime "$FLAT_UTILTIME"
      -q "$FLAT_Q"
    )

    {
      echo "\$ ${sim_cmd[*]}"
      "${sim_cmd[@]}"
    } > "$sim_stdout" 2> "$sim_stderr"
    local sim_rc=$?
    if [[ $sim_rc -ne 0 ]]; then
      status="sim_failed"
    fi
  fi

  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$scheduler" "$thresh_tag" "$thresh_value" "$seed" "$num_eps" "$TOPO_EPS1" \
    "$traffic_in" "$out_traffic" "$route_log" "$sim_log" "$status" \
    > "$status_file"

  # Write run metadata
  {
    echo "experiment_type=$EXPERIMENT_TYPE"
    echo "threshold_tag=$thresh_tag"
    echo "scheduler=$scheduler"
    echo "threshold_pct=$thresh_value"
    echo "seed=$seed"
    echo "nrack=$NRACK"
    echo "hosts_per_rack=$HOSTS_PER_RACK"
    echo "gpus_per_host=$GPUS_PER_HOST"
    echo "model_mix=$MODEL_MIX"
    echo "frag_level=$FRAG"
    echo "load=$LOAD"
    echo "workload=$WORKLOAD"
    echo "traffic_seed=$seed"
    echo "topology_total_degree=$total_degree"
    echo "topology_hybrid_ocs_degree=$hybrid_ocs_degree"
    echo "topology_eps_count=$eps_count"
    echo "flat_simtime=$FLAT_SIMTIME"
    echo "flat_q=$FLAT_Q"
    echo "small_flow_mode=percent"
    echo "small_flow_threshold=$thresh_value"
    echo "run_dir=$run_dir"
  } > "$summary_dir/run_meta.txt"

  echo "[done]  $thresh_tag seed=$seed status=$status"
  return 0
}

BATCH_STATUS_DIR="$BATCH_DIR/_batch_status"
mkdir -p "$BATCH_STATUS_DIR"

for ((i=0; i<${#FULL_SCHEDS[@]}; ++i)); do
  (
    if run_one_config "$i"; then
      echo "ok" > "$BATCH_STATUS_DIR/${i}.status"
    else
      echo "failed" > "$BATCH_STATUS_DIR/${i}.status"
    fi
  ) &

  while true; do
    running_jobs=$(jobs -pr | wc -l)
    if [[ "$running_jobs" -lt "$MAX_JOBS" ]]; then
      break
    fi
    wait -n || true
  done
done
wait || true

echo ""
echo "=== All htsim runs completed, collecting results ==="

# =============================================================================
# Step 5: Collect results into batch_summary.csv
# =============================================================================

echo "=== Step 5: Collect results ==="

OK_RUNS=()
FAILED_RUNS=()

for ((i=0; i<${#FULL_SCHEDS[@]}; ++i)); do
  scheduler="${FULL_SCHEDS[$i]}"
  thresh_tag="${FULL_THRESH_TAGS[$i]}"
  thresh_value="${FULL_THRESH_VALUES[$i]}"
  seed="${FULL_SEEDS[$i]}"
  num_eps=1

  run_dir="$RESULTS_DIR/${thresh_tag}/seed_${seed}"
  status_file="$run_dir/summary/status.tsv"

  status="missing"
  if [[ -f "$status_file" ]]; then
    IFS=$'\t' read -r _ _ _ _ _ _ _ _ _ _ st < "$status_file"
    status="$st"
  fi

  echo "$scheduler,$thresh_tag,$thresh_value,$seed,$num_eps,$TOPO_EPS1,$run_dir/native_traffic/infer_mix3L2M1S_seed${seed}_${NRACK}racks.htsim,$status,$run_dir" >> "$BATCH_SUMMARY"

  if [[ "$status" == "ok" ]]; then
    OK_RUNS+=("${thresh_tag}_seed${seed}")
  else
    FAILED_RUNS+=("${thresh_tag}_seed${seed}")
    echo "[warn] $thresh_tag seed=$seed failed: status=$status"
  fi
done

echo ""
echo "=== Batch Summary (top 20 lines) ==="
head -21 "$BATCH_SUMMARY"
echo ""
echo "  ... total lines: $(wc -l < "$BATCH_SUMMARY")"
echo "  OK: ${#OK_RUNS[@]}, Failed: ${#FAILED_RUNS[@]}"

# =============================================================================
# Step 6: Per-seed plots + seed-aggregated plots
# =============================================================================

echo "=== Step 6: Generate plots ==="

# Collect all scheduler tags that have at least one ok run
OK_THRESH_TAGS=()
for ((s=0; s<${#RUN_SCHEDS[@]}; ++s)); do
  tag="${RUN_THRESH_TAGS[$s]}"
  has_ok=0
  for seed in $(seq "$TRAFFIC_SEED_START" "$TRAFFIC_SEED_END"); do
    sf="$RESULTS_DIR/${tag}/seed_${seed}/summary/status.tsv"
    if [[ -f "$sf" ]]; then
      IFS=$'\t' read -r _ _ _ _ _ _ _ _ _ _ st < "$sf"
      if [[ "$st" == "ok" ]]; then
        has_ok=1
        break
      fi
    fi
  done
  if [[ "$has_ok" == "1" ]]; then
    OK_THRESH_TAGS+=("$tag")
  fi
done

if [[ ${#OK_THRESH_TAGS[@]} -ge 2 ]]; then

  # Per-seed plots
  for seed in $(seq "$TRAFFIC_SEED_START" "$TRAFFIC_SEED_END"); do
    echo "[plot] per-seed plots for seed=$seed"

    SEED_SIM_DIR="$BATCH_DIR/sim_logs_seed${seed}"
    SEED_ROUTE_DIR="$BATCH_DIR/route_logs_seed${seed}"
    SEED_PLOT_DIR="$BATCH_DIR/plots_seed${seed}"
    mkdir -p "$SEED_SIM_DIR" "$SEED_ROUTE_DIR" "$SEED_PLOT_DIR"

    # Collect sim and route logs for this seed
    SEED_OK_TAGS=()
    for tag in "${OK_THRESH_TAGS[@]}"; do
      src_sim="$RESULTS_DIR/${tag}/seed_${seed}/sim_logs/${tag}.log"
      src_route="$RESULTS_DIR/${tag}/seed_${seed}/route_logs/${tag}.log"
      if [[ -f "$src_sim" ]]; then
        cp "$src_sim" "$SEED_SIM_DIR/${tag}.log"
        SEED_OK_TAGS+=("$tag")
      fi
      if [[ -f "$src_route" ]]; then
        cp "$src_route" "$SEED_ROUTE_DIR/${tag}.log"
      fi
    done

    if [[ ${#SEED_OK_TAGS[@]} -lt 2 ]]; then
      echo "[plot] skip seed=$seed: only ${#SEED_OK_TAGS[@]} ok runs"
      continue
    fi

    SEED_OK_CSV="$(join_by_comma "${SEED_OK_TAGS[@]}")"

    MPLCONFIGDIR="$BATCH_DIR/.mplconfig" python3 "$PLOT_SOLVE_TIME" \
      --log_dir "$SEED_ROUTE_DIR" \
      --out_csv "$SEED_PLOT_DIR/solve_time_summary.csv" \
      --out_md "$SEED_PLOT_DIR/solve_time_summary.md" \
      --out_png "$SEED_PLOT_DIR/solve_time_summary.png" \
      > "$SEED_PLOT_DIR/plot_solve_time.log" 2>&1 || echo "[warn] solve-time plot failed seed=$seed"

    MPLCONFIGDIR="$BATCH_DIR/.mplconfig" python3 "$PLOT_FCT_BYTES" \
      --sim_log_dir "$SEED_SIM_DIR" \
      --log_glob "*.log" \
      --schedulers "$SEED_OK_CSV" \
      --title "Flow Size vs Completion Time (Threshold Sweep seed=$seed)" \
      --out_csv "$SEED_PLOT_DIR/fct_vs_bytes_curve.csv" \
      --out_png "$SEED_PLOT_DIR/fct_vs_bytes_curve.png" \
      > "$SEED_PLOT_DIR/plot_fct_vs_bytes.log" 2>&1 || echo "[warn] fct-vs-bytes plot failed seed=$seed"

    # Check if dynamic is in ok set for relative plots
    has_dynamic=0
    for tag in "${SEED_OK_TAGS[@]}"; do
      if [[ "$tag" == "hyacinth_dynamic" ]]; then
        has_dynamic=1
        break
      fi
    done

    if [[ "$has_dynamic" == "1" ]]; then
      MPLCONFIGDIR="$BATCH_DIR/.mplconfig" python3 "$PLOT_FCT_AVG_REL" \
        --curve_csv "$SEED_PLOT_DIR/fct_vs_bytes_curve.csv" \
        --schedulers "$SEED_OK_CSV" \
        --title "Avg Relative FCT vs Dynamic (Threshold Sweep seed=$seed)" \
        --out_csv "$SEED_PLOT_DIR/fct_avg_relative_summary.csv" \
        --out_png "$SEED_PLOT_DIR/fct_avg_relative_summary.png" \
        > "$SEED_PLOT_DIR/plot_fct_avg_rel.log" 2>&1 || echo "[warn] avg-relative-fct plot failed seed=$seed"

      MPLCONFIGDIR="$BATCH_DIR/.mplconfig" python3 "$PLOT_COFLOW_AVG_REL" \
        --sim_log_dir "$SEED_SIM_DIR" \
        --log_glob "*.log" \
        --schedulers "$SEED_OK_CSV" \
        --emit_quad \
        --out_dir "$SEED_PLOT_DIR" \
        --title_template "{p} Relative Coflow CCT vs Dynamic (Threshold Sweep seed=$seed)" \
        > "$SEED_PLOT_DIR/plot_coflow_avg_rel.log" 2>&1 || echo "[warn] relative-coflow plot failed seed=$seed"
    fi
  done

  # Seed-aggregated plots
  echo "[plot] seed-aggregated plots"
  SEED_AVG_LOG="$BATCH_DIR/seed_avg_summary.log"
  python3 "$PLOT_AGG_SEED" \
    --batch_summary "$BATCH_SUMMARY" \
    --out_dir "$BATCH_DIR" \
    > "$SEED_AVG_LOG" 2>&1 || echo "[warn] seed-average aggregation failed"

  # Also build combined sim/route logs across all seeds for aggregate plots
  ALL_SIM_DIR="$BATCH_DIR/sim_logs_combined"
  ALL_ROUTE_DIR="$BATCH_DIR/route_logs_combined"
  mkdir -p "$ALL_SIM_DIR" "$ALL_ROUTE_DIR"

  for tag in "${OK_THRESH_TAGS[@]}"; do
    for seed in $(seq "$TRAFFIC_SEED_START" "$TRAFFIC_SEED_END"); do
      src_sim="$RESULTS_DIR/${tag}/seed_${seed}/sim_logs/${tag}.log"
      src_route="$RESULTS_DIR/${tag}/seed_${seed}/route_logs/${tag}.log"
      if [[ -f "$src_sim" ]]; then
        cp "$src_sim" "$ALL_SIM_DIR/${tag}_seed${seed}.log"
      fi
      if [[ -f "$src_route" ]]; then
        cp "$src_route" "$ALL_ROUTE_DIR/${tag}_seed${seed}.log"
      fi
    done
  done

else
  echo "[warn] Too few successful scheduler configs (${#OK_THRESH_TAGS[@]}) for meaningful plots"
fi

# =============================================================================
# Final status
# =============================================================================

echo ""
echo "==============================================="
echo "  Threshold Sweep Experiment Complete"
echo "==============================================="
echo "  Output dir: $BATCH_DIR"
echo "  Batch summary: $BATCH_SUMMARY"
echo "  Total runs: ${#FULL_SCHEDS[@]}"
echo "  Successful runs: ${#OK_RUNS[@]}"
echo "  Failed runs: ${#FAILED_RUNS[@]}"
if [[ ${#FAILED_RUNS[@]} -gt 0 ]]; then
  echo "  Failed (first 20): $(join_by_comma "${FAILED_RUNS[@]:0:20}")"
fi
echo ""

if [[ ${#FAILED_RUNS[@]} -gt 0 ]]; then
  echo "[batch] some runs failed" >&2
  exit 1
fi

echo "[batch] all runs completed successfully"
exit 0
