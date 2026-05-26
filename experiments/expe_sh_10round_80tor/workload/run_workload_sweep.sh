#!/usr/bin/env bash
set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTSIM_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

EXPERIMENT_TYPE="workload"
BATCH_TAG="${BATCH_TAG:-batch_$(date +%Y%m%d_%H%M%S)_${EXPERIMENT_TYPE}}"
BATCH_DIR="$HTSIM_ROOT/experiments/expe_logs_10round_80tor/${EXPERIMENT_TYPE}/$BATCH_TAG"
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

# Fixed baseline knobs
HOSTS_PER_RACK=8
GPUS_PER_HOST=8
BASE_FRAG=0.5
BASE_LOAD=0.5
BASE_NRACK=80
BASE_MODEL_MIX="4L,3M,3S"
BASE_WORKLOAD_FILE="$BASE_WORKLOAD"

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
SMALL_FLOW_MODE="percent"
SMALL_FLOW_THRESHOLD=20.0

FLAT_SIMTIME=20
FLAT_UTILTIME=0.02
FLAT_Q=200

MAX_JOBS="${MAX_JOBS:-20}"
CASE_PARALLEL_JOBS="${CASE_PARALLEL_JOBS:-$MAX_JOBS}"
PER_CASE_MAX_JOBS="${PER_CASE_MAX_JOBS:-1}"
INJECT_TIMEOUT_SEC="${INJECT_TIMEOUT_SEC:-0}"
SIM_TIMEOUT_SEC="${SIM_TIMEOUT_SEC:-0}"
AUTO_BUILD_RAW="${AUTO_BUILD:-1}"
NPROC="${NPROC:-$(nproc)}"

SCHEDULERS_DEFAULT="ocs_eps_pruned,pure_ocs_ksp,eps_ecmp,pure_ocs_ksp_greedy,pure_ocs_pruned,ocs_eps_large_small,ocs_eps_global_ksp,pure_ocs_3hop_preset,ocs_eps_preset_greedy,ocs_eps_preset_dynamic_greedy"
SCHEDULERS_CSV="${SCHEDULERS:-$SCHEDULERS_DEFAULT}"

CASE_TAGS=(
  "cdf_fbcoco"
  "cdf_fbcoco_january_2024"
  "cdf_fbcoco_february_2024"
  "cdf_fbcoco_march_2024"
)
CASE_MODEL_MIX=(
  "$BASE_MODEL_MIX"
  "$BASE_MODEL_MIX"
  "$BASE_MODEL_MIX"
  "$BASE_MODEL_MIX"
)
CASE_FRAGS=(
  "$BASE_FRAG"
  "$BASE_FRAG"
  "$BASE_FRAG"
  "$BASE_FRAG"
)
CASE_LOADS=(
  "$BASE_LOAD"
  "$BASE_LOAD"
  "$BASE_LOAD"
  "$BASE_LOAD"
)
CASE_NRACKS=(
  "$BASE_NRACK"
  "$BASE_NRACK"
  "$BASE_NRACK"
  "$BASE_NRACK"
)
CASE_WORKLOADS=(
  "$FLOW_DISTR_DIR/fbcoco.csv"
  "$FLOW_DISTR_DIR/fbcoco_january_2024.csv"
  "$FLOW_DISTR_DIR/fbcoco_february_2024.csv"
  "$FLOW_DISTR_DIR/fbcoco_march_2024.csv"
)

# Expand each base case to multi-seed runs, e.g. case_seed42 ... case_seed51
BASE_CASE_TAGS=("${CASE_TAGS[@]}")
BASE_CASE_MODEL_MIX=("${CASE_MODEL_MIX[@]}")
BASE_CASE_FRAGS=("${CASE_FRAGS[@]}")
BASE_CASE_LOADS=("${CASE_LOADS[@]}")
BASE_CASE_NRACKS=("${CASE_NRACKS[@]}")
BASE_CASE_WORKLOADS=("${CASE_WORKLOADS[@]}")

CASE_TAGS=()
CASE_MODEL_MIX=()
CASE_FRAGS=()
CASE_LOADS=()
CASE_NRACKS=()
CASE_WORKLOADS=()
CASE_SEEDS=()

for ((bi=0; bi<${#BASE_CASE_TAGS[@]}; ++bi)); do
  for seed in $(seq "$TRAFFIC_SEED_START" "$TRAFFIC_SEED_END"); do
    CASE_TAGS+=("${BASE_CASE_TAGS[$bi]}_seed${seed}")
    CASE_MODEL_MIX+=("${BASE_CASE_MODEL_MIX[$bi]}")
    CASE_FRAGS+=("${BASE_CASE_FRAGS[$bi]}")
    CASE_LOADS+=("${BASE_CASE_LOADS[$bi]}")
    CASE_NRACKS+=("${BASE_CASE_NRACKS[$bi]}")
    CASE_WORKLOADS+=("${BASE_CASE_WORKLOADS[$bi]}")
    CASE_SEEDS+=("$seed")
  done
done

join_by_comma() {
  local IFS=","
  echo "$*"
}

normalize_bool() {
  local raw="${1,,}"
  case "$raw" in
    1|true|yes|y) echo "1" ;;
    0|false|no|n|"") echo "0" ;;
    *) echo "-1" ;;
  esac
}

require_file() {
  local p="$1"
  local what="$2"
  if [[ ! -f "$p" ]]; then
    echo "[fatal] missing $what: $p" >&2
    exit 1
  fi
}

run_with_optional_timeout() {
  local timeout_sec="$1"
  shift
  if [[ "$timeout_sec" == "0" || "$timeout_sec" == "0.0" ]]; then
    "$@"
    return $?
  fi
  timeout "${timeout_sec}s" "$@"
  return $?
}

resolve_topo_key() {
  local s="$1"
  case "$s" in
    ocs_eps_pruned|ocs_eps_large_small|ocs_eps_global_ksp|ocs_eps_preset_greedy|ocs_eps_preset_dynamic_greedy) echo "eps1" ;;
    eps_ecmp) echo "eps8" ;;
    pure_ocs_ksp|pure_ocs_ksp_greedy|pure_ocs_pruned|pure_ocs_3hop_preset) echo "eps0" ;;
    *) echo "unknown" ;;
  esac
}

resolve_num_eps() {
  local s="$1"
  local eps_count="$2"
  case "$s" in
    eps_ecmp) echo "$eps_count" ;;
    ocs_eps_pruned|ocs_eps_large_small|ocs_eps_global_ksp|ocs_eps_preset_greedy|ocs_eps_preset_dynamic_greedy) echo "1" ;;
    pure_ocs_ksp|pure_ocs_ksp_greedy|pure_ocs_pruned|pure_ocs_3hop_preset) echo "0" ;;
    *) echo "-1" ;;
  esac
}

total_degree_for_nrack() {
  local nrack="$1"
  case "$nrack" in
    80) echo "8" ;;
    20|40) echo "4" ;;
    *)
      echo "[fatal] unsupported nrack for topology-degree rule: $nrack (supported: 20/40/80)" >&2
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

maybe_build_binaries() {
  echo "[build] skipped (disabled in this script)"
  return 0
}

run_case() {
  local idx="$1"
  local case_tag="${CASE_TAGS[$idx]}"
  local model_mix="${CASE_MODEL_MIX[$idx]}"
  local frag="${CASE_FRAGS[$idx]}"
  local load="${CASE_LOADS[$idx]}"
  local nrack="${CASE_NRACKS[$idx]}"
  local workload="${CASE_WORKLOADS[$idx]}"
  local traffic_seed="${CASE_SEEDS[$idx]}"
  local case_base="${case_tag%_seed*}"

  local run_dir="$BATCH_DIR/${case_base}/seed_${traffic_seed}"
  LAST_RUN_DIR="$run_dir"

  local route_logs_dir="$run_dir/route_logs"
  local native_traffic_dir="$run_dir/native_traffic"
  local transformed_dir="$run_dir/transformed_traffic"
  local sim_logs_dir="$run_dir/sim_logs"
  local summary_dir="$run_dir/summary"
  local status_dir="$summary_dir/status"
  local mplconfigdir="$run_dir/.mplconfig"

  mkdir -p "$route_logs_dir" "$native_traffic_dir" "$transformed_dir" "$sim_logs_dir" "$summary_dir" "$status_dir" "$mplconfigdir"

  local total_degree
  total_degree="$(total_degree_for_nrack "$nrack")" || return 1
  local hybrid_ocs_degree=$((total_degree - 1))
  local eps_count="$total_degree"
  if (( hybrid_ocs_degree < 0 )); then
    echo "[fatal] invalid hybrid ocs degree for nrack=$nrack" >&2
    return 1
  fi

  local topo_eps0="$TOPO_DIR/n${nrack}_k${total_degree}_c8_eps0.txt"
  local topo_eps1="$TOPO_DIR/n${nrack}_k${hybrid_ocs_degree}_c8_eps1.txt"
  local topo_epsN="$TOPO_DIR/n${nrack}_k0_c8_eps${eps_count}.txt"

  ensure_topology_file "$nrack" "$total_degree" 0 "$topo_eps0"
  ensure_topology_file "$nrack" "$hybrid_ocs_degree" 1 "$topo_eps1"
  ensure_topology_file "$nrack" 0 "$eps_count" "$topo_epsN"

  local traffic_base="infer_${case_tag}_${nrack}racks"
  local traffic_in="$native_traffic_dir/${traffic_base}.htsim"
  local traffic_snapshot="$native_traffic_dir/traffic_common.htsim"
  local traffic_gen_log="$summary_dir/traffic_generate.log"

  echo "[case] start $case_tag"
  echo "[traffic] generating $traffic_in"
  python3 "$TRAFFIC_GEN_PY" \
    -t "$TRAFFIC_TOPO_NAME" \
    -r "$nrack" \
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
    --workload "$workload" \
    --outdir "$native_traffic_dir" \
    --gpus-per-host "$GPUS_PER_HOST" \
    --model-mix "$model_mix" \
    --frag-level "$frag" \
    --topk "$TRAFFIC_TOPK" \
    --model-weight "$TRAFFIC_MODEL_WEIGHT" \
    --insufficient-policy "$TRAFFIC_INSUFFICIENT_POLICY" \
    --seed "$traffic_seed" \
    --outfile "$traffic_base" \
    > "$traffic_gen_log" 2>&1

  if [[ ! -f "$traffic_in" ]]; then
    echo "[case] fail $case_tag: traffic generation missing output" >&2
    return 1
  fi

  cp "$traffic_in" "$traffic_snapshot"

  local scheds_raw
  scheds_raw="$SCHEDULERS_CSV"
  IFS=',' read -r -a raw_scheds <<< "$scheds_raw"
  local sched_list=()
  local s
  for s in "${raw_scheds[@]}"; do
    s="${s//[[:space:]]/}"
    [[ -z "$s" ]] && continue
    if [[ "$(resolve_topo_key "$s")" == "unknown" ]]; then
      echo "[case] fail $case_tag: unknown scheduler $s" >&2
      return 1
    fi
    sched_list+=("$s")
  done

  if [[ ${#sched_list[@]} -eq 0 ]]; then
    echo "[case] fail $case_tag: empty scheduler list" >&2
    return 1
  fi

  {
    echo "experiment_type=$EXPERIMENT_TYPE"
    echo "case_tag=$case_tag"
    echo "run_dir=$run_dir"
    echo "nrack=$nrack"
    echo "hosts_per_rack=$HOSTS_PER_RACK"
    echo "gpus_per_host=$GPUS_PER_HOST"
    echo "model_mix=$model_mix"
    echo "frag_level=$frag"
    echo "load=$load"
    echo "workload=$workload"
    echo "traffic_file=$traffic_in"
    echo "traffic_seed=$traffic_seed"
    echo "traffic_topk=$TRAFFIC_TOPK"
    echo "traffic_coflow_mode=$TRAFFIC_COFLOW_MODE"
    echo "traffic_mode=$TRAFFIC_MODE"
    echo "traffic_infer_groups=$TRAFFIC_INFER_GROUPS"
    echo "traffic_infer_interval_ms=$TRAFFIC_INFER_INTERVAL_MS"
    echo "traffic_infer_model_pp1_spread_ms=$TRAFFIC_INFER_MODEL_PP1_SPREAD_MS"
    echo "traffic_infer_pp_jitter_ms=$TRAFFIC_INFER_PP_JITTER_MS"
    echo "traffic_duration_sec=$TRAFFIC_DURATION_SEC"
    echo "topology_total_degree=$total_degree"
    echo "topology_hybrid_ocs_degree=$hybrid_ocs_degree"
    echo "topology_eps_count=$eps_count"
    echo "flat_simtime=$FLAT_SIMTIME"
    echo "flat_q=$FLAT_Q"
    echo "small_flow_mode=$SMALL_FLOW_MODE"
    echo "small_flow_threshold=$SMALL_FLOW_THRESHOLD"
    echo "schedulers=$(join_by_comma "${sched_list[@]}")"
  } > "$summary_dir/run_meta.txt"

  run_one_scheduler() {
    local scheduler="$1"
    local topo_key="$2"
    local num_eps="$3"
    local topo_file="$4"

    local out_traffic="$transformed_dir/traffic_routed.${scheduler}.txt"
    local route_log="$route_logs_dir/${scheduler}.log"
    local sim_log="$sim_logs_dir/${scheduler}.log"
    local sim_stdout="$sim_logs_dir/${scheduler}.stdout.txt"
    local sim_stderr="$sim_logs_dir/${scheduler}.stderr.txt"
    local status_file="$status_dir/${scheduler}.tsv"

    echo "[start] $case_tag $scheduler topo=$topo_key num_eps=$num_eps"

    {
      echo "\$ $INJECTOR_BIN --topo_file $topo_file --traffic_in $traffic_in --traffic_out $out_traffic --num_tor $nrack --num_eps $num_eps --rate_tor_tor $RATE_TOR_TOR --rate_tor_eps $RATE_TOR_EPS --scheduler $scheduler --ksp_k $KSP_K --max_hops $MAX_HOPS --max_candidates $MAX_CANDIDATES --small_flow_mode $SMALL_FLOW_MODE --small_flow_threshold $SMALL_FLOW_THRESHOLD"
      run_with_optional_timeout "$INJECT_TIMEOUT_SEC" \
        "$INJECTOR_BIN" \
        --topo_file "$topo_file" \
        --traffic_in "$traffic_in" \
        --traffic_out "$out_traffic" \
        --num_tor "$nrack" \
        --num_eps "$num_eps" \
        --rate_tor_tor "$RATE_TOR_TOR" \
        --rate_tor_eps "$RATE_TOR_EPS" \
        --scheduler "$scheduler" \
        --ksp_k "$KSP_K" \
        --max_hops "$MAX_HOPS" \
        --max_candidates "$MAX_CANDIDATES" \
        --small_flow_mode "$SMALL_FLOW_MODE" \
        --small_flow_threshold "$SMALL_FLOW_THRESHOLD"
    } > "$route_log" 2>&1
    local inject_rc=$?

    local status="ok"
    if [[ $inject_rc -ne 0 ]]; then
      if [[ $inject_rc -eq 124 ]]; then
        status="inject_timeout"
      else
        status="inject_failed"
      fi
      : > "$sim_log"
      : > "$sim_stdout"
      : > "$sim_stderr"
    else
      {
        echo "\$ $FLAT_BIN -flowfile $out_traffic -topfile $topo_file -outputfile $sim_log -simtime $FLAT_SIMTIME -utiltime $FLAT_UTILTIME -q $FLAT_Q"
        run_with_optional_timeout "$SIM_TIMEOUT_SEC" \
          "$FLAT_BIN" \
          -flowfile "$out_traffic" \
          -topfile "$topo_file" \
          -outputfile "$sim_log" \
          -simtime "$FLAT_SIMTIME" \
          -utiltime "$FLAT_UTILTIME" \
          -q "$FLAT_Q"
      } > "$sim_stdout" 2> "$sim_stderr"
      local sim_rc=$?
      if [[ $sim_rc -ne 0 ]]; then
        if [[ $sim_rc -eq 124 ]]; then
          status="sim_timeout"
        else
          status="sim_failed"
        fi
      fi
    fi

    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$scheduler" "$topo_file" "$num_eps" "$traffic_in" "$traffic_snapshot" \
      "$out_traffic" "$route_log" "$sim_log" "$sim_stdout" "$sim_stderr" "$status" \
      > "$status_file"

    echo "[done]  $case_tag $scheduler status=$status"
  }

  echo "[case] run_dir: $run_dir"
  echo "[case] schedulers: $(join_by_comma "${sched_list[@]}")"

  for scheduler in "${sched_list[@]}"; do
    topo_key="$(resolve_topo_key "$scheduler")"
    num_eps="$(resolve_num_eps "$scheduler" "$eps_count")"
    case "$topo_key" in
      eps0) topo_file="$topo_eps0" ;;
      eps1) topo_file="$topo_eps1" ;;
      eps8) topo_file="$topo_epsN" ;;
      *)
        echo "[case] fail $case_tag: invalid topo key $topo_key" >&2
        return 1
        ;;
    esac

    run_one_scheduler "$scheduler" "$topo_key" "$num_eps" "$topo_file" &

    while true; do
      running_jobs=$(jobs -pr | wc -l)
      if [[ "$running_jobs" -lt "$PER_CASE_MAX_JOBS" ]]; then
        break
      fi
      wait -n || true
    done
  done
  wait || true

  local manifest_csv="$summary_dir/run_manifest.csv"
  {
    echo "scheduler,topology,num_eps,traffic_in,traffic_snapshot,transformed_traffic,route_log,sim_log,sim_stdout,sim_stderr,status"
    for scheduler in "${sched_list[@]}"; do
      status_file="$status_dir/${scheduler}.tsv"
      if [[ ! -f "$status_file" ]]; then
        echo "$scheduler,,,,,,,,,,missing_status"
        continue
      fi
      IFS=$'\t' read -r c1 c2 c3 c4 c5 c6 c7 c8 c9 c10 c11 < "$status_file"
      echo "$c1,$c2,$c3,$c4,$c5,$c6,$c7,$c8,$c9,$c10,$c11"
    done
  } > "$manifest_csv"

  local ok_scheds=()
  local failed_scheds=()
  for scheduler in "${sched_list[@]}"; do
    status_file="$status_dir/${scheduler}.tsv"
    if [[ ! -f "$status_file" ]]; then
      failed_scheds+=("$scheduler")
      continue
    fi
    IFS=$'\t' read -r _ _ _ _ _ _ _ _ _ sim_stderr status < "$status_file"
    if [[ "$status" == "ok" ]]; then
      ok_scheds+=("$scheduler")
    else
      failed_scheds+=("$scheduler")
    fi
    if [[ -f "$sim_stderr" ]]; then
      err_lines=$(wc -l < "$sim_stderr")
      echo "[stderr] $case_tag $scheduler lines=$err_lines"
    fi
  done

  echo "[plot] solve-time ($case_tag)"
  MPLCONFIGDIR="$mplconfigdir" python3 "$PLOT_SOLVE_TIME" \
    --log_dir "$route_logs_dir" \
    --out_csv "$summary_dir/solve_time_summary.csv" \
    --out_md "$summary_dir/solve_time_summary.md" \
    --out_png "$summary_dir/solve_time_summary.png" \
    > "$summary_dir/plot_solve_time.log" 2>&1 || echo "[warn] solve-time plot failed: $case_tag"

  if [[ ${#ok_scheds[@]} -gt 0 ]]; then
    echo "[plot] fct-vs-bytes ($case_tag)"
    MPLCONFIGDIR="$mplconfigdir" python3 "$PLOT_FCT_BYTES" \
      --sim_log_dir "$sim_logs_dir" \
      --log_glob "*.log" \
      --schedulers "$(join_by_comma "${ok_scheds[@]}")" \
      --title "Flow Size vs Completion Time ($EXPERIMENT_TYPE:$case_tag)" \
      --out_csv "$summary_dir/fct_vs_bytes_curve.csv" \
      --out_png "$summary_dir/fct_vs_bytes_curve.png" \
      > "$summary_dir/plot_fct_vs_bytes.log" 2>&1 || echo "[warn] fct-vs-bytes plot failed: $case_tag"

    local has_dynamic=0
    for s in "${ok_scheds[@]}"; do
      if [[ "$s" == "ocs_eps_preset_dynamic_greedy" ]]; then
        has_dynamic=1
        break
      fi
    done

    if [[ "$has_dynamic" == "1" ]]; then
      MPLCONFIGDIR="$mplconfigdir" python3 "$PLOT_FCT_AVG_REL" \
        --curve_csv "$summary_dir/fct_vs_bytes_curve.csv" \
        --schedulers "$(join_by_comma "${ok_scheds[@]}")" \
        --title "Avg Relative FCT ($EXPERIMENT_TYPE:$case_tag, dynamic=1)" \
        --out_csv "$summary_dir/fct_avg_relative_summary.csv" \
        --out_png "$summary_dir/fct_avg_relative_summary.png" \
        > "$summary_dir/plot_fct_avg_rel.log" 2>&1 || echo "[warn] avg-relative-fct plot failed: $case_tag"

      MPLCONFIGDIR="$mplconfigdir" python3 "$PLOT_COFLOW_AVG_REL" \
        --sim_log_dir "$sim_logs_dir" \
        --log_glob "*.log" \
        --schedulers "$(join_by_comma "${ok_scheds[@]}")" \
        --emit_quad \
        --out_dir "$summary_dir" \
        --title_template "{p} Relative Coflow CCT ($EXPERIMENT_TYPE:$case_tag, dynamic=1)" \
        > "$summary_dir/plot_coflow_avg_rel.log" 2>&1 || echo "[warn] relative-coflow plot (P100/P99/P95/AVG) failed: $case_tag"
    else
      echo "[warn] skip avg-relative plots: baseline scheduler not in ok set ($case_tag)"
    fi
  else
    echo "[warn] skip fct plots: no ok schedulers ($case_tag)"
  fi

  if [[ ${#failed_scheds[@]} -gt 0 ]]; then
    echo "[case] failed schedulers ($case_tag): $(join_by_comma "${failed_scheds[@]}")"
    return 1
  fi

  echo "[case] completed $case_tag"
  return 0
}

require_file "$TOPO_GEN_PY" "topology generator"
require_file "$TRAFFIC_GEN_PY" "traffic generator"
require_file "$PLOT_SOLVE_TIME" "plot_solve_time.py"
require_file "$PLOT_FCT_BYTES" "plot_fct_vs_bytes.py"
require_file "$PLOT_FCT_AVG_REL" "plot_fct_avg_relative_bar.py"
require_file "$PLOT_COFLOW_AVG_REL" "plot_coflow_avg_relative_bar.py"
require_file "$PLOT_AGG_SEED" "aggregate_seed_summaries.py"

if ! maybe_build_binaries; then
  echo "[fatal] build failed, see $BATCH_DIR/build_injector.log and $BATCH_DIR/build_flat.log" >&2
  exit 1
fi

require_file "$INJECTOR_BIN" "injector_bin"
require_file "$FLAT_BIN" "flat_bin"

if [[ ${#CASE_TAGS[@]} -ne ${#CASE_MODEL_MIX[@]} || \
      ${#CASE_TAGS[@]} -ne ${#CASE_FRAGS[@]} || \
      ${#CASE_TAGS[@]} -ne ${#CASE_LOADS[@]} || \
      ${#CASE_TAGS[@]} -ne ${#CASE_NRACKS[@]} || \
      ${#CASE_TAGS[@]} -ne ${#CASE_WORKLOADS[@]} || \
      ${#CASE_TAGS[@]} -ne ${#CASE_SEEDS[@]} ]]; then
  echo "[fatal] case array length mismatch" >&2
  exit 1
fi

BATCH_SUMMARY="$BATCH_DIR/batch_summary.csv"
echo "case_tag,seed,model_mix,frag,load,nrack,workload,status,run_dir" > "$BATCH_SUMMARY"

echo "[batch] experiment_type=$EXPERIMENT_TYPE"
echo "[batch] batch_dir=$BATCH_DIR"
echo "[batch] total_cases=${#CASE_TAGS[@]}"

FAILED_CASES=()
LAST_RUN_DIR=""
BATCH_STATUS_DIR="$BATCH_DIR/_batch_status"
mkdir -p "$BATCH_STATUS_DIR"

echo "[batch] case_parallel_jobs=$CASE_PARALLEL_JOBS per_case_max_jobs=$PER_CASE_MAX_JOBS (global cap ~= $((CASE_PARALLEL_JOBS * PER_CASE_MAX_JOBS)))"

for ((i=0; i<${#CASE_TAGS[@]}; ++i)); do
  status_file="$BATCH_STATUS_DIR/${i}.tsv"
  (
    LAST_RUN_DIR=""
    if run_case "$i"; then
      status="ok"
    else
      status="failed"
    fi
    printf '%s\t%s\n' "$status" "$LAST_RUN_DIR" > "$status_file"
  ) &

  while true; do
    running_jobs=$(jobs -pr | wc -l)
    if [[ "$running_jobs" -lt "$CASE_PARALLEL_JOBS" ]]; then
      break
    fi
    wait -n || true
  done
done
wait || true

for ((i=0; i<${#CASE_TAGS[@]}; ++i)); do
  case_tag="${CASE_TAGS[$i]}"
  traffic_seed="${CASE_SEEDS[$i]}"
  model_mix="${CASE_MODEL_MIX[$i]}"
  frag="${CASE_FRAGS[$i]}"
  load="${CASE_LOADS[$i]}"
  nrack="${CASE_NRACKS[$i]}"
  workload="${CASE_WORKLOADS[$i]}"

  status_file="$BATCH_STATUS_DIR/${i}.tsv"
  status="failed"
  run_dir=""
  if [[ -f "$status_file" ]]; then
    IFS=$'\t' read -r status run_dir < "$status_file"
  fi
  if [[ "$status" != "ok" ]]; then
    FAILED_CASES+=("$case_tag")
  fi

  printf '%s,%s,"%s",%s,%s,%s,"%s",%s,"%s"\n' "$case_tag" "$traffic_seed" "$model_mix" "$frag" "$load" "$nrack" "$workload" "$status" "$run_dir" >> "$BATCH_SUMMARY"
done

SEED_AVG_DIR="$BATCH_DIR"
SEED_AVG_LOG="$BATCH_DIR/seed_avg_summary.log"
python3 "$PLOT_AGG_SEED" \
  --batch_summary "$BATCH_SUMMARY" \
  --out_dir "$SEED_AVG_DIR" \
  > "$SEED_AVG_LOG" 2>&1 || echo "[warn] seed-average aggregation failed"

if [[ ${#FAILED_CASES[@]} -gt 0 ]]; then
  echo "[batch] failed cases: $(join_by_comma "${FAILED_CASES[@]}")" >&2
  echo "[batch] summary: $BATCH_SUMMARY"
  exit 1
fi

echo "[batch] all cases completed"
echo "[batch] summary: $BATCH_SUMMARY"
exit 0
