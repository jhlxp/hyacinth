#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INJECTOR_BIN="${INJECTOR_BIN:-$ROOT/traffic_route_injector_cpp/bin/route_trace_dep_injector}"
TOPO_FILE="${TOPO_FILE:-$ROOT/experiments/topology/n80_k7_c8_eps1.txt}"
TRAFFIC_IN="${TRAFFIC_IN:-$ROOT/experiments/traffic_coflow/flows_dc_80racks_8c_30pct_1.001s.htsim}"

NUM_TOR="${NUM_TOR:-80}"
NUM_EPS="${NUM_EPS:-1}"
RATE_TOR_TOR="${RATE_TOR_TOR:-12500000000.0}"
RATE_TOR_EPS="${RATE_TOR_EPS:-12500000000.0}"
KSP_K="${KSP_K:-4}"
MAX_HOPS="${MAX_HOPS:-5}"
MAX_CANDIDATES="${MAX_CANDIDATES:-20}"
SMALL_FLOW_MODE="${SMALL_FLOW_MODE:-percent}"
SMALL_FLOW_THRESHOLD="${SMALL_FLOW_THRESHOLD:-20.0}"

# Default schedulers focus on threshold-related behavior.
SCHEDULERS=("${@}")
if [[ ${#SCHEDULERS[@]} -eq 0 ]]; then
  SCHEDULERS=(
    ocs_eps_large_small
    ocs_eps_preset_greedy
    ocs_eps_preset_dynamic_greedy
  )
fi

RUN_TAG="${RUN_TAG:-run_$(date +%Y%m%d_%H%M%S)_ratio_only}"
OUT_DIR="${OUT_DIR:-$ROOT/experiments/logs/flat/$RUN_TAG}"
ROUTE_DIR="$OUT_DIR/transformed_traffic"
LOG_DIR="$OUT_DIR/route_logs"
SUMMARY_DIR="$OUT_DIR/summary"
SUMMARY_CSV="$SUMMARY_DIR/eps_ocs_ratio_summary.csv"

mkdir -p "$ROUTE_DIR" "$LOG_DIR" "$SUMMARY_DIR"

if [[ ! -x "$INJECTOR_BIN" ]]; then
  echo "[fatal] missing injector bin: $INJECTOR_BIN" >&2
  exit 1
fi
if [[ ! -f "$TOPO_FILE" ]]; then
  echo "[fatal] missing topo file: $TOPO_FILE" >&2
  exit 1
fi
if [[ ! -f "$TRAFFIC_IN" ]]; then
  echo "[fatal] missing traffic file: $TRAFFIC_IN" >&2
  exit 1
fi

echo "scheduler,eps_flow_pct,ocs_flow_pct,eps_bytes_pct,ocs_bytes_pct,total_flows,total_bytes" > "$SUMMARY_CSV"

echo "[run] out_dir=$OUT_DIR"
echo "[run] topo=$TOPO_FILE"
echo "[run] traffic=$TRAFFIC_IN"
echo "[run] threshold=${SMALL_FLOW_MODE}:${SMALL_FLOW_THRESHOLD}"

printf "%-34s | %10s | %10s | %11s | %11s | %10s | %14s\n" \
  "scheduler" "eps_flow%" "ocs_flow%" "eps_bytes%" "ocs_bytes%" "flows" "bytes"
printf "%s\n" "--------------------------------------------------------------------------------------------------------------------------------"

for scheduler in "${SCHEDULERS[@]}"; do
  out_traffic="$ROUTE_DIR/traffic_routed.${scheduler}.txt"
  route_log="$LOG_DIR/${scheduler}.log"

  {
    echo "\$ $INJECTOR_BIN --topo_file $TOPO_FILE --traffic_in $TRAFFIC_IN --traffic_out $out_traffic --num_tor $NUM_TOR --num_eps $NUM_EPS --rate_tor_tor $RATE_TOR_TOR --rate_tor_eps $RATE_TOR_EPS --scheduler $scheduler --ksp_k $KSP_K --max_hops $MAX_HOPS --max_candidates $MAX_CANDIDATES --small_flow_mode $SMALL_FLOW_MODE --small_flow_threshold $SMALL_FLOW_THRESHOLD"
    "$INJECTOR_BIN" \
      --topo_file "$TOPO_FILE" \
      --traffic_in "$TRAFFIC_IN" \
      --traffic_out "$out_traffic" \
      --num_tor "$NUM_TOR" \
      --num_eps "$NUM_EPS" \
      --rate_tor_tor "$RATE_TOR_TOR" \
      --rate_tor_eps "$RATE_TOR_EPS" \
      --scheduler "$scheduler" \
      --ksp_k "$KSP_K" \
      --max_hops "$MAX_HOPS" \
      --max_candidates "$MAX_CANDIDATES" \
      --small_flow_mode "$SMALL_FLOW_MODE" \
      --small_flow_threshold "$SMALL_FLOW_THRESHOLD"
  } > "$route_log" 2>&1

  stats=$(awk -v num_tor="$NUM_TOR" '
    BEGIN{total_f=total_b=eps_f=eps_b=ocs_f=ocs_b=0}
    NF>=6 {
      path=$6; sub(/^path=/,"",path); split(path,a,",");
      use_eps=0;
      for(i in a){
        if((a[i]+0) >= num_tor){use_eps=1; break}
      }
      bytes=$3+0;
      total_f++; total_b+=bytes;
      if(use_eps){eps_f++; eps_b+=bytes}else{ocs_f++; ocs_b+=bytes}
    }
    END{
      eps_flow_pct = (total_f ? 100.0*eps_f/total_f : 0.0);
      ocs_flow_pct = (total_f ? 100.0*ocs_f/total_f : 0.0);
      eps_bytes_pct = (total_b ? 100.0*eps_b/total_b : 0.0);
      ocs_bytes_pct = (total_b ? 100.0*ocs_b/total_b : 0.0);
      printf("%.4f,%.4f,%.4f,%.4f,%d,%.0f", eps_flow_pct, ocs_flow_pct, eps_bytes_pct, ocs_bytes_pct, total_f, total_b);
    }
  ' "$out_traffic")

  IFS=',' read -r eps_flow_pct ocs_flow_pct eps_bytes_pct ocs_bytes_pct total_flows total_bytes <<< "$stats"

  printf "%-34s | %10.2f | %10.2f | %11.2f | %11.2f | %10d | %14.0f\n" \
    "$scheduler" "$eps_flow_pct" "$ocs_flow_pct" "$eps_bytes_pct" "$ocs_bytes_pct" "$total_flows" "$total_bytes"

  echo "$scheduler,$eps_flow_pct,$ocs_flow_pct,$eps_bytes_pct,$ocs_bytes_pct,$total_flows,$total_bytes" >> "$SUMMARY_CSV"
done

echo "[ok] summary_csv=$SUMMARY_CSV"
