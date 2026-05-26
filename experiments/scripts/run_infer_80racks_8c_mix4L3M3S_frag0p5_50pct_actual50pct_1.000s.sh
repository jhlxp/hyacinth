#!/usr/bin/env bash
set -u
set -o pipefail

# Standalone full pipeline for fixed infer traffic:
#   0) generate missing infer .htsim (auto)
#   1) route injection (10 schedulers, parallel)
#   2) flat simulation (parallel)
#   3) solve-time + fct-vs-bytes plots
#   4) traffic timeline plot (if placement csv exists)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTSIM_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INJECTOR_BIN="${INJECTOR_BIN:-$HTSIM_ROOT/traffic_route_injector_cpp/bin/route_trace_dep_injector}"
FLAT_BIN="${FLAT_BIN:-$HTSIM_ROOT/src/flat/run/htsim_bolt_flat}"
PLOT_SOLVE_TIME="${PLOT_SOLVE_TIME:-$HTSIM_ROOT/plot/plot_solve_time.py}"
PLOT_FCT_BYTES="${PLOT_FCT_BYTES:-$HTSIM_ROOT/plot/plot_fct_vs_bytes.py}"
PLOT_FCT_AVG_REL="${PLOT_FCT_AVG_REL:-$HTSIM_ROOT/plot/plot_fct_avg_relative_bar.py}"
PLOT_COFLOW_AVG_REL="${PLOT_COFLOW_AVG_REL:-$HTSIM_ROOT/plot/plot_coflow_avg_relative_bar.py}"
TIMELINE_PLOT_PY="${TIMELINE_PLOT_PY:-$HTSIM_ROOT/plot/plot_traffic_coflow_timeline.py}"
TRAFFIC_GEN_PY="${TRAFFIC_GEN_PY:-$HTSIM_ROOT/traffic_gene/generate_traffic_model_frag.py}"
TRAFFIC_WORKLOAD="${TRAFFIC_WORKLOAD:-$HTSIM_ROOT/traffic_gene/flow_distr/fbcoco.csv}"

TRAFFIC_IN="${TRAFFIC_IN:-$HTSIM_ROOT/experiments/traffic_coflow/infer_80racks_8c_mix4L3M3S_frag0p5_50pct_actual50pct_1.000s.htsim}"
TRAFFIC_TOPO_NAME="${TRAFFIC_TOPO_NAME:-dc}"
TRAFFIC_NRACK="${TRAFFIC_NRACK:-80}"
TRAFFIC_HOSTS_PER_RACK="${TRAFFIC_HOSTS_PER_RACK:-8}"
TRAFFIC_GPUS_PER_HOST="${TRAFFIC_GPUS_PER_HOST:-8}"
TRAFFIC_LOAD="${TRAFFIC_LOAD:-0.50}"
TRAFFIC_DURATION_SEC="${TRAFFIC_DURATION_SEC:-1.000}"
TRAFFIC_COFLOW_WINDOW_MS="${TRAFFIC_COFLOW_WINDOW_MS:-20}"
TRAFFIC_COFLOW_MODE="${TRAFFIC_COFLOW_MODE:-all2allv_event}"
TRAFFIC_NICS="${TRAFFIC_NICS:-1}"
TRAFFIC_NIC_RATE="${TRAFFIC_NIC_RATE:-100e9}"
TRAFFIC_MODEL_MIX="${TRAFFIC_MODEL_MIX:-4L,3M,3S}"
TRAFFIC_FRAG_LEVEL="${TRAFFIC_FRAG_LEVEL:-0.50}"
TRAFFIC_TOPK="${TRAFFIC_TOPK:-8}"
TRAFFIC_MODEL_WEIGHT="${TRAFFIC_MODEL_WEIGHT:-hosts}"
TRAFFIC_INSUFFICIENT_POLICY="${TRAFFIC_INSUFFICIENT_POLICY:-strict}"
TRAFFIC_SEED="${TRAFFIC_SEED:-42}"

TOPO_EPS0="${TOPO_EPS0:-$HTSIM_ROOT/experiments/topology/n80_k8_c8_eps0.txt}"
TOPO_EPS1="${TOPO_EPS1:-$HTSIM_ROOT/experiments/topology/n80_k7_c8_eps1.txt}"
TOPO_EPS8="${TOPO_EPS8:-$HTSIM_ROOT/experiments/topology/n80_k0_c8_eps8.txt}"

NUM_TOR="${NUM_TOR:-80}"
RATE_TOR_TOR="${RATE_TOR_TOR:-12500000000.0}"  # 100Gbps => 1.25e10 B/s
RATE_TOR_EPS="${RATE_TOR_EPS:-12500000000.0}"
KSP_K="${KSP_K:-4}"
MAX_HOPS="${MAX_HOPS:-5}"
MAX_CANDIDATES="${MAX_CANDIDATES:-20}"
SMALL_FLOW_MODE="${SMALL_FLOW_MODE:-percent}"
SMALL_FLOW_THRESHOLD="${SMALL_FLOW_THRESHOLD:-20.0}"

FLAT_SIMTIME="${FLAT_SIMTIME:-100}"
FLAT_UTILTIME="${FLAT_UTILTIME:-0.02}"
FLAT_Q="${FLAT_Q:-200}"

MAX_JOBS="${MAX_JOBS:-30}"
INJECT_TIMEOUT_SEC="${INJECT_TIMEOUT_SEC:-0}"
SIM_TIMEOUT_SEC="${SIM_TIMEOUT_SEC:-0}"
SKIP_PLOT_RAW="${SKIP_PLOT:-0}"
SKIP_TRAFFIC_TIMELINE_PLOT="${SKIP_TRAFFIC_TIMELINE_PLOT:-false}"

SCHEDULERS_DEFAULT="ocs_eps_pruned,pure_ocs_ksp,eps_ecmp,pure_ocs_ksp_greedy,pure_ocs_pruned,ocs_eps_large_small,ocs_eps_global_ksp,ocs_eps_preset_greedy,ocs_eps_preset_dynamic_greedy"
SCHEDULERS_CSV="${SCHEDULERS:-$SCHEDULERS_DEFAULT}"

RUN_TAG="${RUN_TAG:-run_$(date +%Y%m%d_%H%M%S)_infer_80racks_8c_mix4L3M3S_frag0p5_50pct_actual50pct}"
RUN_DIR="${RUN_DIR:-$HTSIM_ROOT/experiments/logs/flat/$RUN_TAG}"

ROUTE_LOGS_DIR="$RUN_DIR/route_logs"
NATIVE_TRAFFIC_DIR="$RUN_DIR/native_traffic"
TRANSFORMED_DIR="$RUN_DIR/transformed_traffic"
SIM_LOGS_DIR="$RUN_DIR/sim_logs"
SUMMARY_DIR="$RUN_DIR/summary"
STATUS_DIR="$SUMMARY_DIR/status"
MPLCONFIGDIR="$RUN_DIR/.mplconfig"
TRAFFIC_SNAPSHOT="$NATIVE_TRAFFIC_DIR/traffic_common.htsim"

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

normalize_bool() {
  local raw="${1,,}"
  case "$raw" in
    1|true|yes|y) echo "1" ;;
    0|false|no|n|"") echo "0" ;;
    *) echo "-1" ;;
  esac
}

ensure_traffic_input() {
  require_file "$TRAFFIC_GEN_PY" "traffic generator"
  require_file "$TRAFFIC_WORKLOAD" "traffic workload csv"

  local traffic_dir
  traffic_dir="$(dirname "$TRAFFIC_IN")"
  local traffic_base
  traffic_base="$(basename "$TRAFFIC_IN")"
  traffic_base="${traffic_base%.htsim}"

  mkdir -p "$traffic_dir" "$SUMMARY_DIR"
  local gen_log="$SUMMARY_DIR/traffic_generate.log"

  if [[ -f "$TRAFFIC_IN" ]]; then
    echo "[traffic] existing traffic_in found, will regenerate and overwrite: $TRAFFIC_IN"
  else
    echo "[traffic] missing traffic_in, generate now"
  fi
  echo "[traffic] target file: $TRAFFIC_IN"
  echo "[traffic] cmd: python3 $TRAFFIC_GEN_PY -t $TRAFFIC_TOPO_NAME -r $TRAFFIC_NRACK -c $TRAFFIC_HOSTS_PER_RACK -l $TRAFFIC_LOAD -T $TRAFFIC_DURATION_SEC --coflow-window-ms $TRAFFIC_COFLOW_WINDOW_MS --coflow-mode $TRAFFIC_COFLOW_MODE --nics $TRAFFIC_NICS --nic-rate $TRAFFIC_NIC_RATE --workload $TRAFFIC_WORKLOAD --outdir $traffic_dir --gpus-per-host $TRAFFIC_GPUS_PER_HOST --model-mix $TRAFFIC_MODEL_MIX --frag-level $TRAFFIC_FRAG_LEVEL --topk $TRAFFIC_TOPK --model-weight $TRAFFIC_MODEL_WEIGHT --insufficient-policy $TRAFFIC_INSUFFICIENT_POLICY --seed $TRAFFIC_SEED --outfile $traffic_base"

  python3 "$TRAFFIC_GEN_PY" \
    -t "$TRAFFIC_TOPO_NAME" \
    -r "$TRAFFIC_NRACK" \
    -c "$TRAFFIC_HOSTS_PER_RACK" \
    -l "$TRAFFIC_LOAD" \
    -T "$TRAFFIC_DURATION_SEC" \
    --coflow-window-ms "$TRAFFIC_COFLOW_WINDOW_MS" \
    --coflow-mode "$TRAFFIC_COFLOW_MODE" \
    --nics "$TRAFFIC_NICS" \
    --nic-rate "$TRAFFIC_NIC_RATE" \
    --workload "$TRAFFIC_WORKLOAD" \
    --outdir "$traffic_dir" \
    --gpus-per-host "$TRAFFIC_GPUS_PER_HOST" \
    --model-mix "$TRAFFIC_MODEL_MIX" \
    --frag-level "$TRAFFIC_FRAG_LEVEL" \
    --topk "$TRAFFIC_TOPK" \
    --model-weight "$TRAFFIC_MODEL_WEIGHT" \
    --insufficient-policy "$TRAFFIC_INSUFFICIENT_POLICY" \
    --seed "$TRAFFIC_SEED" \
    --outfile "$traffic_base" \
    > "$gen_log" 2>&1

  if [[ ! -f "$TRAFFIC_IN" ]]; then
    echo "[fatal] traffic generation did not produce expected file: $TRAFFIC_IN" >&2
    echo "[fatal] see log: $gen_log" >&2
    exit 1
  fi
  echo "[traffic] generated: $TRAFFIC_IN"
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
    pure_ocs_ksp|pure_ocs_ksp_greedy|pure_ocs_pruned) echo "eps0" ;;
    *) echo "unknown" ;;
  esac
}

resolve_num_eps() {
  local s="$1"
  case "$s" in
    eps_ecmp) echo "8" ;;
    ocs_eps_pruned|ocs_eps_large_small|ocs_eps_global_ksp|ocs_eps_preset_greedy|ocs_eps_preset_dynamic_greedy) echo "1" ;;
    pure_ocs_ksp|pure_ocs_ksp_greedy|pure_ocs_pruned) echo "0" ;;
    *) echo "-1" ;;
  esac
}

resolve_topo_file() {
  local topo_key="$1"
  case "$topo_key" in
    eps0) echo "$TOPO_EPS0" ;;
    eps1) echo "$TOPO_EPS1" ;;
    eps8) echo "$TOPO_EPS8" ;;
    *) echo "" ;;
  esac
}

run_one_scheduler() {
  local scheduler="$1"
  local topo_key="$2"
  local num_eps="$3"
  local topo_file="$4"

  local out_traffic="$TRANSFORMED_DIR/traffic_routed.${scheduler}.txt"
  local route_log="$ROUTE_LOGS_DIR/${scheduler}.log"
  local sim_log="$SIM_LOGS_DIR/${scheduler}.log"
  local sim_stdout="$SIM_LOGS_DIR/${scheduler}.stdout.txt"
  local sim_stderr="$SIM_LOGS_DIR/${scheduler}.stderr.txt"
  local status_file="$STATUS_DIR/${scheduler}.tsv"

  echo "[start] $scheduler topo=$topo_key num_eps=$num_eps"

  {
    echo "\$ $INJECTOR_BIN --topo_file $topo_file --traffic_in $TRAFFIC_IN --traffic_out $out_traffic --num_tor $NUM_TOR --num_eps $num_eps --rate_tor_tor $RATE_TOR_TOR --rate_tor_eps $RATE_TOR_EPS --scheduler $scheduler --ksp_k $KSP_K --max_hops $MAX_HOPS --max_candidates $MAX_CANDIDATES --small_flow_mode $SMALL_FLOW_MODE --small_flow_threshold $SMALL_FLOW_THRESHOLD"
    run_with_optional_timeout "$INJECT_TIMEOUT_SEC" \
      "$INJECTOR_BIN" \
      --topo_file "$topo_file" \
      --traffic_in "$TRAFFIC_IN" \
      --traffic_out "$out_traffic" \
      --num_tor "$NUM_TOR" \
      --num_eps "$num_eps" \
      --rate_tor_tor "$RATE_TOR_TOR" \
      --rate_tor_eps "$RATE_TOR_EPS" \
      --scheduler "$scheduler" \
      --ksp_k "$KSP_K" \
      --max_hops "$MAX_HOPS" \
      --max_candidates "$MAX_CANDIDATES" \
      --small_flow_mode "$SMALL_FLOW_MODE" \
      --small_flow_threshold "$SMALL_FLOW_THRESHOLD"
  } >"$route_log" 2>&1
  local inject_rc=$?

  local status="ok"
  if [[ $inject_rc -ne 0 ]]; then
    if [[ $inject_rc -eq 124 ]]; then
      status="inject_timeout"
    else
      status="inject_failed"
    fi
    : >"$sim_log"
    : >"$sim_stdout"
    : >"$sim_stderr"
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
    } >"$sim_stdout" 2>"$sim_stderr"
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
    "$scheduler" "$topo_file" "$num_eps" "$TRAFFIC_IN" "$TRAFFIC_SNAPSHOT" \
    "$out_traffic" "$route_log" "$sim_log" "$sim_stdout" "$sim_stderr" "$status" \
    >"$status_file"

  echo "[done]  $scheduler status=$status"
}

require_file "$INJECTOR_BIN" "injector_bin"
require_file "$FLAT_BIN" "flat_bin"
require_file "$TOPO_EPS0" "topo_eps0"
require_file "$TOPO_EPS1" "topo_eps1"
require_file "$TOPO_EPS8" "topo_eps8"
require_file "$PLOT_SOLVE_TIME" "plot_solve_time.py"
require_file "$PLOT_FCT_BYTES" "plot_fct_vs_bytes.py"
require_file "$PLOT_FCT_AVG_REL" "plot_fct_avg_relative_bar.py"
require_file "$PLOT_COFLOW_AVG_REL" "plot_coflow_avg_relative_bar.py"
ensure_traffic_input
require_file "$TRAFFIC_IN" "traffic_in"

mkdir -p "$ROUTE_LOGS_DIR" "$NATIVE_TRAFFIC_DIR" "$TRANSFORMED_DIR" "$SIM_LOGS_DIR" "$SUMMARY_DIR" "$STATUS_DIR" "$MPLCONFIGDIR"
cp "$TRAFFIC_IN" "$TRAFFIC_SNAPSHOT"
echo "Place simulator runtime logs here (flat stdout/stderr and FCT output logs)." > "$SIM_LOGS_DIR/README.txt"

# Plot traffic timeline as early as possible (right after traffic is ready).
skip_timeline="$(normalize_bool "$SKIP_TRAFFIC_TIMELINE_PLOT")"
if [[ "$skip_timeline" == "-1" ]]; then
  echo "[warn] unknown SKIP_TRAFFIC_TIMELINE_PLOT=$SKIP_TRAFFIC_TIMELINE_PLOT, skip timeline"
  skip_timeline="1"
fi

if [[ "$skip_timeline" != "1" ]]; then
  if [[ -f "$TIMELINE_PLOT_PY" ]]; then
    PLACEMENT_FILE="${PLACEMENT_FILE:-$TRAFFIC_IN.placement.csv}"
    if [[ -f "$PLACEMENT_FILE" ]]; then
      TIMELINE_OUT_PNG="$SUMMARY_DIR/traffic_timeline_by_model_pp.png"
      TIMELINE_OUT_CSV="$SUMMARY_DIR/traffic_timeline_by_model_pp.csv"
      TIMELINE_LOG="$SUMMARY_DIR/traffic_timeline_plot.log"
      echo "[plot] traffic timeline (early)"
      MPLCONFIGDIR="$MPLCONFIGDIR" python3 "$TIMELINE_PLOT_PY" \
        --traffic_file "$TRAFFIC_IN" \
        --placement_file "$PLACEMENT_FILE" \
        --out_png "$TIMELINE_OUT_PNG" \
        --out_csv "$TIMELINE_OUT_CSV" \
        --fig_w 10 \
        --fig_h 4 \
        --marker_size 26 \
        --font_size 14 \
        --legend_font_size 13 \
        > "$TIMELINE_LOG" 2>&1
    else
      echo "[warn] skip timeline plot: missing placement file $PLACEMENT_FILE"
    fi
  else
    echo "[warn] skip timeline plot: missing $TIMELINE_PLOT_PY"
  fi
fi

IFS=',' read -r -a raw_scheds <<< "$SCHEDULERS_CSV"
SCHED_LIST=()
for raw in "${raw_scheds[@]}"; do
  s="${raw//[[:space:]]/}"
  [[ -z "$s" ]] && continue
  topo_key="$(resolve_topo_key "$s")"
  if [[ "$topo_key" == "unknown" ]]; then
    echo "[fatal] unknown scheduler: $s" >&2
    exit 1
  fi
  SCHED_LIST+=("$s")
done

if [[ ${#SCHED_LIST[@]} -eq 0 ]]; then
  echo "[fatal] empty scheduler list" >&2
  exit 1
fi

{
  echo "run_dir=$RUN_DIR"
  echo "traffic_desc=$TRAFFIC_IN"
  echo "injector_bin=$INJECTOR_BIN"
  echo "flat_bin=$FLAT_BIN"
  echo "flat_simtime=$FLAT_SIMTIME"
  echo "flat_utiltime=$FLAT_UTILTIME"
  echo "flat_q=$FLAT_Q"
  echo "topo_eps0=$TOPO_EPS0"
  echo "topo_eps1=$TOPO_EPS1"
  echo "topo_eps8=$TOPO_EPS8"
  echo "small_flow_mode=$SMALL_FLOW_MODE"
  echo "small_flow_threshold=$SMALL_FLOW_THRESHOLD"
  echo "jobs=$MAX_JOBS"
  echo "inject_timeout_sec=$INJECT_TIMEOUT_SEC"
  echo "sim_timeout_sec=$SIM_TIMEOUT_SEC"
  echo "schedulers=$(join_by_comma "${SCHED_LIST[@]}")"
} > "$SUMMARY_DIR/run_meta.txt"

MANIFEST_CSV="$SUMMARY_DIR/run_manifest.csv"

echo "[run] run_dir         : $RUN_DIR"
echo "[run] traffic         : $TRAFFIC_IN"
echo "[run] flat_simtime    : $FLAT_SIMTIME"
echo "[run] schedulers      : $(join_by_comma "${SCHED_LIST[@]}")"
echo "[run] workers(max)    : $MAX_JOBS"

for scheduler in "${SCHED_LIST[@]}"; do
  topo_key="$(resolve_topo_key "$scheduler")"
  num_eps="$(resolve_num_eps "$scheduler")"
  topo_file="$(resolve_topo_file "$topo_key")"
  run_one_scheduler "$scheduler" "$topo_key" "$num_eps" "$topo_file" &

  while true; do
    running_jobs=$(jobs -pr | wc -l)
    if [[ "$running_jobs" -lt "$MAX_JOBS" ]]; then
      break
    fi
    wait -n || true
  done
done
wait || true

case "${SKIP_PLOT_RAW,,}" in
  1|true|yes|y) SKIP_PLOT=1 ;;
  0|false|no|n|"") SKIP_PLOT=0 ;;
  *)
    echo "[warn] unknown SKIP_PLOT=$SKIP_PLOT_RAW, fallback to 0"
    SKIP_PLOT=0
    ;;
esac

{
  echo "scheduler,topology,num_eps,traffic_in,traffic_snapshot,transformed_traffic,route_log,sim_log,sim_stdout,sim_stderr,status"
  for scheduler in "${SCHED_LIST[@]}"; do
    status_file="$STATUS_DIR/${scheduler}.tsv"
    if [[ ! -f "$status_file" ]]; then
      echo "$scheduler,,,,,,,,,,missing_status"
      continue
    fi
    IFS=$'\t' read -r c1 c2 c3 c4 c5 c6 c7 c8 c9 c10 c11 < "$status_file"
    echo "$c1,$c2,$c3,$c4,$c5,$c6,$c7,$c8,$c9,$c10,$c11"
  done
} > "$MANIFEST_CSV"

OK_SCHEDS=()
FAILED_SCHEDS=()
for scheduler in "${SCHED_LIST[@]}"; do
  status_file="$STATUS_DIR/${scheduler}.tsv"
  if [[ ! -f "$status_file" ]]; then
    FAILED_SCHEDS+=("$scheduler")
    continue
  fi
  IFS=$'\t' read -r _ _ _ _ _ _ _ _ _ sim_stderr status < "$status_file"
  if [[ "$status" == "ok" ]]; then
    OK_SCHEDS+=("$scheduler")
  else
    FAILED_SCHEDS+=("$scheduler")
  fi
  if [[ -f "$sim_stderr" ]]; then
    err_lines=$(wc -l < "$sim_stderr")
    echo "[stderr] $scheduler lines=$err_lines"
  fi
done

if [[ "$SKIP_PLOT" != "1" ]]; then
  echo "[plot] solve-time"
  MPLCONFIGDIR="$MPLCONFIGDIR" python3 "$PLOT_SOLVE_TIME" \
    --log_dir "$ROUTE_LOGS_DIR" \
    --out_csv "$SUMMARY_DIR/solve_time_summary.csv" \
    --out_md "$SUMMARY_DIR/solve_time_summary.md" \
    --out_png "$SUMMARY_DIR/solve_time_summary.png"

  if [[ ${#OK_SCHEDS[@]} -gt 0 ]]; then
    echo "[plot] fct-vs-bytes"
    MPLCONFIGDIR="$MPLCONFIGDIR" python3 "$PLOT_FCT_BYTES" \
      --sim_log_dir "$SIM_LOGS_DIR" \
      --log_glob "*.log" \
      --schedulers "$(join_by_comma "${OK_SCHEDS[@]}")" \
      --title "Flow Size vs Completion Time (flat)" \
      --out_csv "$SUMMARY_DIR/fct_vs_bytes_curve.csv" \
      --out_png "$SUMMARY_DIR/fct_vs_bytes_curve.png"

    has_dynamic=0
    for s in "${OK_SCHEDS[@]}"; do
      if [[ "$s" == "ocs_eps_preset_dynamic_greedy" ]]; then
        has_dynamic=1
        break
      fi
    done
    if [[ "$has_dynamic" == "1" ]]; then
      echo "[plot] avg-relative-fct (dynamic=1)"
      MPLCONFIGDIR="$MPLCONFIGDIR" python3 "$PLOT_FCT_AVG_REL" \
        --curve_csv "$SUMMARY_DIR/fct_vs_bytes_curve.csv" \
        --schedulers "$(join_by_comma "${OK_SCHEDS[@]}")" \
        --title "Avg Relative FCT by Scheduler (dynamic=1)" \
        --out_csv "$SUMMARY_DIR/fct_avg_relative_summary.csv" \
        --out_png "$SUMMARY_DIR/fct_avg_relative_summary.png"

      echo "[plot] avg-relative-coflow-cct (dynamic=1)"
      MPLCONFIGDIR="$MPLCONFIGDIR" python3 "$PLOT_COFLOW_AVG_REL" \
        --sim_log_dir "$SIM_LOGS_DIR" \
        --log_glob "*.log" \
        --schedulers "$(join_by_comma "${OK_SCHEDS[@]}")" \
        --title "Avg Relative Coflow CCT by Scheduler (dynamic=1)" \
        --out_csv "$SUMMARY_DIR/coflow_avg_relative_summary.csv" \
        --out_png "$SUMMARY_DIR/coflow_avg_relative_summary.png"
    else
      echo "[warn] skip avg-relative-fct/coflow-cct plot: missing baseline scheduler ocs_eps_preset_dynamic_greedy in ok schedulers"
    fi
  else
    echo "[warn] skip fct-vs-bytes plot: no ok scheduler"
  fi
else
  echo "[run] SKIP_PLOT=1, skip plotting"
fi

echo "[run] run_dir         : $RUN_DIR"
echo "[run] manifest_csv    : $MANIFEST_CSV"
if [[ ${#FAILED_SCHEDS[@]} -gt 0 ]]; then
  echo "[warn] failed schedulers: $(join_by_comma "${FAILED_SCHEDS[@]}")"
  exit 1
fi

echo "[ok] all schedulers completed"
exit 0
