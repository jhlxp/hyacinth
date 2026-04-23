#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLOT_SOLVE_TIME="${PLOT_SOLVE_TIME:-$ROOT/plot/plot_solve_time.py}"
PLOT_FCT_BYTES="${PLOT_FCT_BYTES:-$ROOT/plot/plot_fct_vs_bytes.py}"
PLOT_FCT_AVG_REL="${PLOT_FCT_AVG_REL:-$ROOT/plot/plot_fct_avg_relative_bar.py}"
PLOT_COFLOW_AVG_REL="${PLOT_COFLOW_AVG_REL:-$ROOT/plot/plot_coflow_avg_relative_bar.py}"
PLOT_TIMELINE="${PLOT_TIMELINE:-$ROOT/plot/plot_traffic_coflow_timeline.py}"

# Edit this to one seed run directory: .../<case>/seed_xx
SEED_RUN_DIR="${SEED_RUN_DIR:-/home/xuheng/hyacinth/experiments/expe_logs_10round/workload/batch_20260422_200323_workload/cdf_fbcoco_march_2024/seed_51}"

if [[ ! -d "$SEED_RUN_DIR" ]]; then
  echo "[fatal] SEED_RUN_DIR not found: $SEED_RUN_DIR" >&2
  exit 1
fi
SEED_RUN_DIR="$(cd "$SEED_RUN_DIR" && pwd)"

ROUTE_LOGS_DIR="$SEED_RUN_DIR/route_logs"
SIM_LOGS_DIR="$SEED_RUN_DIR/sim_logs"
SUMMARY_DIR="$SEED_RUN_DIR/summary"
RUN_META="$SUMMARY_DIR/run_meta.txt"
MANIFEST_CSV="$SUMMARY_DIR/run_manifest.csv"

if [[ ! -d "$ROUTE_LOGS_DIR" ]]; then
  echo "[fatal] missing route_logs: $ROUTE_LOGS_DIR" >&2
  exit 1
fi
if [[ ! -d "$SIM_LOGS_DIR" ]]; then
  echo "[fatal] missing sim_logs: $SIM_LOGS_DIR" >&2
  exit 1
fi

for p in "$PLOT_SOLVE_TIME" "$PLOT_FCT_BYTES" "$PLOT_FCT_AVG_REL" "$PLOT_COFLOW_AVG_REL"; do
  if [[ ! -f "$p" ]]; then
    echo "[fatal] missing plot script: $p" >&2
    exit 1
  fi
done

mkdir -p "$SUMMARY_DIR" "$SEED_RUN_DIR/.mplconfig"
export MPLCONFIGDIR="$SEED_RUN_DIR/.mplconfig"

echo "[seed] $SEED_RUN_DIR"
echo "[plot] solve-time"
python3 "$PLOT_SOLVE_TIME" \
  --log_dir "$ROUTE_LOGS_DIR" \
  --out_csv "$SUMMARY_DIR/solve_time_summary.csv" \
  --out_md "$SUMMARY_DIR/solve_time_summary.md" \
  --out_png "$SUMMARY_DIR/solve_time_summary.png"

OK_SCHEDS=""
if [[ -f "$MANIFEST_CSV" ]]; then
  OK_SCHEDS="$(awk -F, 'NR>1 && $11=="ok"{print $1}' "$MANIFEST_CSV" | paste -sd, -)"
fi
if [[ -z "$OK_SCHEDS" ]]; then
  # fallback: infer scheduler names from sim logs
  OK_SCHEDS="$(find "$SIM_LOGS_DIR" -maxdepth 1 -type f -name '*.log' -printf '%f\n' \
    | sed -E 's/\.log$//' \
    | paste -sd, -)"
fi

echo "[plot] fct-vs-bytes"
python3 "$PLOT_FCT_BYTES" \
  --sim_log_dir "$SIM_LOGS_DIR" \
  --log_glob "*.log" \
  --schedulers "$OK_SCHEDS" \
  --title "Flow Size vs Completion Time (single seed)" \
  --out_csv "$SUMMARY_DIR/fct_vs_bytes_curve.csv" \
  --out_png "$SUMMARY_DIR/fct_vs_bytes_curve.png"

REL_SCHEDS="$OK_SCHEDS"
if [[ ",$REL_SCHEDS," == *",ocs_eps_preset_dynamic_greedy,"* ]]; then
  echo "[plot] avg-relative-fct (dynamic=1)"
  python3 "$PLOT_FCT_AVG_REL" \
    --curve_csv "$SUMMARY_DIR/fct_vs_bytes_curve.csv" \
    --schedulers "$REL_SCHEDS" \
    --title "Avg Relative FCT by Scheduler (dynamic=1)" \
    --out_csv "$SUMMARY_DIR/fct_avg_relative_summary.csv" \
    --out_png "$SUMMARY_DIR/fct_avg_relative_summary.png"

  echo "[plot] relative-coflow-cct quad (P100/P99/P95/AVG, dynamic=1)"
  python3 "$PLOT_COFLOW_AVG_REL" \
    --sim_log_dir "$SIM_LOGS_DIR" \
    --log_glob "*.log" \
    --schedulers "$REL_SCHEDS" \
    --emit_quad \
    --out_dir "$SUMMARY_DIR" \
    --title_template "{p} Relative Coflow CCT by Scheduler (dynamic=1)"
else
  echo "[warn] skip relative bars: missing baseline scheduler ocs_eps_preset_dynamic_greedy"
fi

TRAFFIC_IN=""
if [[ -f "$RUN_META" ]]; then
  TRAFFIC_IN="$(grep '^traffic_file=' "$RUN_META" | tail -n1 | cut -d= -f2- || true)"
  if [[ -z "$TRAFFIC_IN" ]]; then
    TRAFFIC_IN="$(grep '^traffic_desc=' "$RUN_META" | tail -n1 | cut -d= -f2- || true)"
  fi
fi

if [[ -n "$TRAFFIC_IN" && ! -f "$TRAFFIC_IN" ]]; then
  base="$(basename "$TRAFFIC_IN")"
  if [[ -f "$SEED_RUN_DIR/native_traffic/$base" ]]; then
    TRAFFIC_IN="$SEED_RUN_DIR/native_traffic/$base"
  fi
fi
if [[ -z "$TRAFFIC_IN" && -f "$SEED_RUN_DIR/native_traffic/traffic_common.htsim" ]]; then
  TRAFFIC_IN="$SEED_RUN_DIR/native_traffic/traffic_common.htsim"
fi
if [[ -z "$TRAFFIC_IN" && -d "$SEED_RUN_DIR/native_traffic" ]]; then
  TRAFFIC_IN="$(find "$SEED_RUN_DIR/native_traffic" -maxdepth 1 -type f -name '*.htsim' | sort | head -n1 || true)"
fi

TRAFFIC_PLACEMENT=""
if [[ -n "$TRAFFIC_IN" && -f "${TRAFFIC_IN}.placement.csv" ]]; then
  TRAFFIC_PLACEMENT="${TRAFFIC_IN}.placement.csv"
fi
if [[ -z "$TRAFFIC_PLACEMENT" && -d "$SEED_RUN_DIR/native_traffic" ]]; then
  shopt -s nullglob
  pcs=( "$SEED_RUN_DIR/native_traffic"/*.placement.csv )
  shopt -u nullglob
  if [[ ${#pcs[@]} -gt 0 ]]; then
    TRAFFIC_PLACEMENT="${pcs[0]}"
  fi
fi

if [[ -n "$TRAFFIC_IN" && -n "$TRAFFIC_PLACEMENT" && -f "$PLOT_TIMELINE" ]]; then
  echo "[plot] traffic timeline"
  python3 "$PLOT_TIMELINE" \
    --traffic_file "$TRAFFIC_IN" \
    --placement_file "$TRAFFIC_PLACEMENT" \
    --out_png "$SUMMARY_DIR/traffic_timeline_by_model_pp.png" \
    --out_csv "$SUMMARY_DIR/traffic_timeline_by_model_pp.csv" \
    --fig_w 10 --fig_h 4 --marker_size 26 --font_size 14 --legend_font_size 13
else
  echo "[warn] skip timeline (traffic=$TRAFFIC_IN placement=$TRAFFIC_PLACEMENT)"
fi

echo "[ok] seed plots written to: $SUMMARY_DIR"
exit 0
