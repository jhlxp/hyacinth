#!/usr/bin/env bash
set -u

# Manual shell runner for flat simulation:
#   route injection (10 schedulers) + flat simulation + plotting
# Default profile:
#   traffic: 30% / 1.001s
#   workers: 10

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTSIM_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INJECTOR_BIN="${INJECTOR_BIN:-$HTSIM_ROOT/traffic_route_injector_cpp/bin/route_trace_dep_injector}"
FLAT_BIN="${FLAT_BIN:-$HTSIM_ROOT/src/flat/run/htsim_bolt_flat}"
PLOT_SOLVE_TIME="${PLOT_SOLVE_TIME:-$HTSIM_ROOT/plot/plot_solve_time.py}"
PLOT_FCT_BYTES="${PLOT_FCT_BYTES:-$HTSIM_ROOT/plot/plot_fct_vs_bytes.py}"
PLOT_FCT_AVG_REL="${PLOT_FCT_AVG_REL:-$HTSIM_ROOT/plot/plot_fct_avg_relative_bar.py}"
PLOT_COFLOW_AVG_REL="${PLOT_COFLOW_AVG_REL:-$HTSIM_ROOT/plot/plot_coflow_avg_relative_bar.py}"

TRAFFIC_IN="${TRAFFIC_IN:-$HTSIM_ROOT/experiments/traffic_coflow/flows_dc_80racks_8c_30pct_1.001s.htsim}"
AUTO_GEN_TRAFFIC_RAW="${AUTO_GEN_TRAFFIC:-1}"
TRAFFIC_GEN_PY="${TRAFFIC_GEN_PY:-$HTSIM_ROOT/traffic_gene/generate_traffic.py}"
TRAFFIC_WORKLOAD="${TRAFFIC_WORKLOAD:-$HTSIM_ROOT/traffic_gene/flow_distr/fbcoco.csv}"
TRAFFIC_OUTDIR="${TRAFFIC_OUTDIR:-$HTSIM_ROOT/experiments/traffic_coflow}"
TRAFFIC_TOPO_NAME="${TRAFFIC_TOPO_NAME:-dc}"
TRAFFIC_NRACK="${TRAFFIC_NRACK:-80}"
TRAFFIC_HOSTS_PER_RACK="${TRAFFIC_HOSTS_PER_RACK:-8}"
TRAFFIC_LOAD="${TRAFFIC_LOAD:-0.30}"
TRAFFIC_DURATION_SEC="${TRAFFIC_DURATION_SEC:-1.001}"
TRAFFIC_COFLOW_WINDOW_MS="${TRAFFIC_COFLOW_WINDOW_MS:-20}"
TRAFFIC_NICS="${TRAFFIC_NICS:-1}"
TRAFFIC_NIC_RATE="${TRAFFIC_NIC_RATE:-100e9}"
TOPO_EPS0="${TOPO_EPS0:-$HTSIM_ROOT/experiments/topology/n80_k8_c8_eps0.txt}"
TOPO_EPS1="${TOPO_EPS1:-$HTSIM_ROOT/experiments/topology/n80_k7_c8_eps1.txt}"
TOPO_EPS8="${TOPO_EPS8:-$HTSIM_ROOT/experiments/topology/n80_k0_c8_eps8.txt}"

NUM_TOR="${NUM_TOR:-80}"
# Keep consistent with traffic_gene (--nic-rate 100e9 bits/s):
# 100 Gbps = 1.25e10 Bytes/s
RATE_TOR_TOR="12500000000.0"
RATE_TOR_EPS="12500000000.0"
KSP_K="${KSP_K:-4}"
MAX_HOPS="${MAX_HOPS:-5}"
MAX_CANDIDATES="${MAX_CANDIDATES:-20}"
SMALL_FLOW_MODE="${SMALL_FLOW_MODE:-percent}"
SMALL_FLOW_THRESHOLD="${SMALL_FLOW_THRESHOLD:-20.0}"

# Unified default sim time: 10s
FLAT_SIMTIME="${FLAT_SIMTIME:-100}"
FLAT_UTILTIME="${FLAT_UTILTIME:-0.02}"
FLAT_Q="${FLAT_Q:-200}"

MAX_JOBS="${MAX_JOBS:-30}"
INJECT_TIMEOUT_SEC="${INJECT_TIMEOUT_SEC:-0}"   # 0 means no timeout
SIM_TIMEOUT_SEC="${SIM_TIMEOUT_SEC:-0}"         # 0 means no timeout
SKIP_PLOT_RAW="${SKIP_PLOT:-0}"

SCHEDULERS_DEFAULT="ocs_eps_pruned,pure_ocs_ksp,eps_ecmp,pure_ocs_ksp_greedy,pure_ocs_pruned,ocs_eps_large_small,ocs_eps_global_ksp,ocs_eps_preset_greedy,ocs_eps_preset_dynamic_greedy"
SCHEDULERS_CSV="${SCHEDULERS:-$SCHEDULERS_DEFAULT}"

RUN_TAG="${RUN_TAG:-run_$(date +%Y%m%d_%H%M%S)_flat_10alg_30pct}"
RUN_DIR="${RUN_DIR:-$HTSIM_ROOT/experiments/logs/flat/$RUN_TAG}"

ROUTE_LOGS_DIR="$RUN_DIR/route_logs"
NATIVE_TRAFFIC_DIR="$RUN_DIR/native_traffic"
TRANSFORMED_DIR="$RUN_DIR/transformed_traffic"
SIM_LOGS_DIR="$RUN_DIR/sim_logs"
SUMMARY_DIR="$RUN_DIR/summary"
STATUS_DIR="$SUMMARY_DIR/status"
TRAFFIC_SNAPSHOT="$NATIVE_TRAFFIC_DIR/traffic_common.htsim"
MPLCONFIGDIR="$RUN_DIR/.mplconfig"

join_by_comma() {
  local IFS=",";
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

compute_generated_traffic_path() {
  python3 - "$TRAFFIC_OUTDIR" "$TRAFFIC_TOPO_NAME" "$TRAFFIC_NRACK" "$TRAFFIC_HOSTS_PER_RACK" "$TRAFFIC_LOAD" "$TRAFFIC_DURATION_SEC" <<'PY'
import pathlib
import sys

outdir, topo, nrack, hosts, load, dur = sys.argv[1:]
pct = int(100 * float(load))
dur_fmt = f"{float(dur):.3f}"
p = pathlib.Path(outdir) / f"flows_{topo}_{nrack}racks_{hosts}c_{pct}pct_{dur_fmt}s.htsim"
print(str(p))
PY
}

resolve_topo_key() {
  local s="$1"
  case "$s" in
    ocs_eps_pruned|ocs_eps_large_small|ocs_eps_global_ksp|ocs_eps_preset_greedy|ocs_eps_preset_dynamic_greedy)
      echo "eps1"
      ;;
    eps_ecmp)
      echo "eps8"
      ;;
    pure_ocs_ksp|pure_ocs_ksp_greedy|pure_ocs_pruned)
      echo "eps0"
      ;;
    *)
      echo "unknown"
      ;;
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

AUTO_GEN_TRAFFIC="$(normalize_bool "$AUTO_GEN_TRAFFIC_RAW")"
if [[ "$AUTO_GEN_TRAFFIC" == "-1" ]]; then
  echo "[fatal] unknown AUTO_GEN_TRAFFIC=$AUTO_GEN_TRAFFIC_RAW (use true/false or 1/0)" >&2
  exit 1
fi

if [[ "$AUTO_GEN_TRAFFIC" == "1" ]]; then
  require_file "$TRAFFIC_GEN_PY" "traffic generator"
  require_file "$TRAFFIC_WORKLOAD" "traffic workload csv"
  mkdir -p "$TRAFFIC_OUTDIR"

  echo "[traffic] generating .htsim first"
  echo "[traffic] cmd: python3 $TRAFFIC_GEN_PY -t $TRAFFIC_TOPO_NAME -r $TRAFFIC_NRACK -c $TRAFFIC_HOSTS_PER_RACK -l $TRAFFIC_LOAD -T $TRAFFIC_DURATION_SEC --coflow-window-ms $TRAFFIC_COFLOW_WINDOW_MS --nics $TRAFFIC_NICS --nic-rate $TRAFFIC_NIC_RATE --outdir $TRAFFIC_OUTDIR --workload $TRAFFIC_WORKLOAD"
  python3 "$TRAFFIC_GEN_PY" \
    -t "$TRAFFIC_TOPO_NAME" \
    -r "$TRAFFIC_NRACK" \
    -c "$TRAFFIC_HOSTS_PER_RACK" \
    -l "$TRAFFIC_LOAD" \
    -T "$TRAFFIC_DURATION_SEC" \
    --coflow-window-ms "$TRAFFIC_COFLOW_WINDOW_MS" \
    --nics "$TRAFFIC_NICS" \
    --nic-rate "$TRAFFIC_NIC_RATE" \
    --outdir "$TRAFFIC_OUTDIR" \
    --workload "$TRAFFIC_WORKLOAD"

  TRAFFIC_IN="$(compute_generated_traffic_path)"
  if [[ ! -f "$TRAFFIC_IN" ]]; then
    echo "[fatal] generated traffic file not found: $TRAFFIC_IN" >&2
    exit 1
  fi
  echo "[traffic] generated: $TRAFFIC_IN"
fi

require_file "$TRAFFIC_IN" "traffic_in"

mkdir -p "$ROUTE_LOGS_DIR" "$NATIVE_TRAFFIC_DIR" "$TRANSFORMED_DIR" "$SIM_LOGS_DIR" "$SUMMARY_DIR" "$STATUS_DIR" "$MPLCONFIGDIR"
cp "$TRAFFIC_IN" "$TRAFFIC_SNAPSHOT"
echo "Place simulator runtime logs here (flat stdout/stderr and FCT output logs)." > "$SIM_LOGS_DIR/README.txt"

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
  echo "auto_gen_traffic=$AUTO_GEN_TRAFFIC"
  echo "traffic_gen_py=$TRAFFIC_GEN_PY"
  echo "traffic_workload=$TRAFFIC_WORKLOAD"
  echo "traffic_outdir=$TRAFFIC_OUTDIR"
  echo "traffic_topo_name=$TRAFFIC_TOPO_NAME"
  echo "traffic_nrack=$TRAFFIC_NRACK"
  echo "traffic_hosts_per_rack=$TRAFFIC_HOSTS_PER_RACK"
  echo "traffic_load=$TRAFFIC_LOAD"
  echo "traffic_duration_sec=$TRAFFIC_DURATION_SEC"
  echo "traffic_coflow_window_ms=$TRAFFIC_COFLOW_WINDOW_MS"
  echo "traffic_nics=$TRAFFIC_NICS"
  echo "traffic_nic_rate=$TRAFFIC_NIC_RATE"
  echo "schedulers=$(join_by_comma "${SCHED_LIST[@]}")"
} > "$SUMMARY_DIR/run_meta.txt"

MANIFEST_CSV="$SUMMARY_DIR/run_manifest.csv"

echo "[run] run_dir         : $RUN_DIR"
echo "[run] traffic         : $TRAFFIC_IN"
echo "[run] auto_gen_traffic: $AUTO_GEN_TRAFFIC"
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
  IFS=$'\t' read -r _ _ _ _ _ _ _ sim_log _ sim_stderr status < "$status_file"
  if [[ "$status" == "ok" ]]; then
    OK_SCHEDS+=("$scheduler")
  else
    FAILED_SCHEDS+=("$scheduler")
  fi
  # Quick stderr check print
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
