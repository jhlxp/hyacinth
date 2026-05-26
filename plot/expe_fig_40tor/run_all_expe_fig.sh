#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PY="${PYTHON:-python3}"
REBUILD_PY="$SCRIPT_DIR/rebuild_seed_avg.py"

mkdir -p "$SCRIPT_DIR/.mplconfig"
export MPLCONFIGDIR="$SCRIPT_DIR/.mplconfig"

detect_latest_batch() {
  local exp="$1"
  local parent="$ROOT/experiments/expe_logs_10round_40tor/$exp"
  local latest
  latest="$(ls -d "$parent"/batch_* 2>/dev/null | sort | tail -n1 || true)"
  if [[ -z "$latest" ]]; then
    echo "[fatal] no batch dir for exp=$exp under $parent" >&2
    exit 1
  fi
  echo "$latest"
}

echo "[run] rebuild seed_avg_summary (using aggregate_seed_summaries.py)"
for exp in frag mix start_spread workload; do
  scenario_root="$(detect_latest_batch "$exp")"
  echo "[run] rebuild exp=$exp scenario_root=$scenario_root"
  "$PY" "$REBUILD_PY" --scenario_root "$scenario_root"
done

echo "[run] draw figures"
"$PY" "$SCRIPT_DIR/frag/plot_frag.py"
"$PY" "$SCRIPT_DIR/mix/plot_mix.py"
"$PY" "$SCRIPT_DIR/start_spread/plot_start_spread.py"
"$PY" "$SCRIPT_DIR/workload/plot_workload.py"
"$PY" "$SCRIPT_DIR/main_trend/plot_main_trend.py"

echo "[ok] all done"
echo "[ok] figure roots:"
echo "  - $SCRIPT_DIR/frag/figures"
echo "  - $SCRIPT_DIR/mix/figures"
echo "  - $SCRIPT_DIR/start_spread/figures"
echo "  - $SCRIPT_DIR/workload/figures"
echo "  - $SCRIPT_DIR/main_trend/figures"
echo "[ok] logs:"
for exp in frag mix start_spread workload; do
  echo "  - $SCRIPT_DIR/$exp/figures/$exp.log"
done
echo "  - $SCRIPT_DIR/main_trend/figures/main_trend.log"
