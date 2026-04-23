#!/usr/bin/env bash

# nohup bash ./run_5_sweeps_serial.sh > /dev/null 2>&1 &


set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXPE_SH_DIR="$ROOT_DIR/experiments/expe_sh"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
MASTER_LOG="$SCRIPT_DIR/run_5_sweeps_parallel_${RUN_TS}.log"

SCRIPTS=(
  "$EXPE_SH_DIR/mix/run_mix_sweep.sh"
  "$EXPE_SH_DIR/frag/run_frag_sweep.sh"
  "$EXPE_SH_DIR/start_spread/run_start_spread_sweep.sh"
  "$EXPE_SH_DIR/topo/run_topo_sweep.sh"
  "$EXPE_SH_DIR/workload/run_workload_sweep.sh"
)

echo "[parallel] start: $(date '+%F %T')" | tee -a "$MASTER_LOG"
echo "[parallel] root : $ROOT_DIR" | tee -a "$MASTER_LOG"
echo "[parallel] log  : $MASTER_LOG" | tee -a "$MASTER_LOG"

for s in "${SCRIPTS[@]}"; do
  if [[ ! -x "$s" ]]; then
    echo "[fatal] missing executable script: $s" | tee -a "$MASTER_LOG"
    exit 1
  fi
done

PIDS=()
NAMES=()
LOGS=()

for s in "${SCRIPTS[@]}"; do
  name="$(basename "$(dirname "$s")")"
  child_log="$SCRIPT_DIR/${name}_${RUN_TS}.log"
  echo "" | tee -a "$MASTER_LOG"
  echo "[parallel] launch: $s" | tee -a "$MASTER_LOG"
  echo "[parallel] child_log: $child_log" | tee -a "$MASTER_LOG"
  bash "$s" > "$child_log" 2>&1 &
  pid=$!
  PIDS+=("$pid")
  NAMES+=("$name")
  LOGS+=("$child_log")
  echo "[parallel] pid=$pid started for $name" | tee -a "$MASTER_LOG"
done

FAILED=0
for i in "${!PIDS[@]}"; do
  pid="${PIDS[$i]}"
  name="${NAMES[$i]}"
  child_log="${LOGS[$i]}"
  if wait "$pid"; then
    echo "[parallel] done: $name status=ok pid=$pid log=$child_log @ $(date '+%F %T')" | tee -a "$MASTER_LOG"
  else
    FAILED=1
    echo "[parallel] done: $name status=failed pid=$pid log=$child_log @ $(date '+%F %T')" | tee -a "$MASTER_LOG"
  fi
done

if [[ "$FAILED" -ne 0 ]]; then
  echo "[parallel] completed with failures: $(date '+%F %T')" | tee -a "$MASTER_LOG"
  exit 1
fi

echo "[parallel] all done: $(date '+%F %T')" | tee -a "$MASTER_LOG"
