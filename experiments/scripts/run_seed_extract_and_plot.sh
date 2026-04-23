#!/usr/bin/env bash
set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTSIM_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 1) Change this list to ONE OR MORE case folders (each contains seed_*).
#    Example:
#    /home/xuheng/hyacinth/experiments/expe_logs_10round/topo/batch_20260422_200323_topo/n20_mix1L1M1S
#    /home/xuheng/hyacinth/experiments/expe_logs_10round/topo/batch_20260422_200323_topo/n40_mix3L2M1S
CASE_DIRS=(

  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/frag/batch_20260422_200323_frag/frag0p1"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/frag/batch_20260422_200323_frag/frag0p3"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/frag/batch_20260422_200323_frag/frag0p5"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/frag/batch_20260422_200323_frag/frag0p7"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/frag/batch_20260422_200323_frag/frag0p9"

  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/mix/batch_20260422_200323_mix/mix4L3M3S"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/mix/batch_20260422_200323_mix/mix10L"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/mix/batch_20260422_200323_mix/mix20S"

  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/start_spread/batch_20260422_200323_start_spread/spread0ms"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/start_spread/batch_20260422_200323_start_spread/spread25ms"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/start_spread/batch_20260422_200323_start_spread/spread50ms"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/start_spread/batch_20260422_200323_start_spread/spread75ms"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/start_spread/batch_20260422_200323_start_spread/spread100ms"

  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/topo/batch_20260422_200323_topo/n20_mix1L1M1S"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/topo/batch_20260422_200323_topo/n40_mix3L2M1S"
  # "/home/xuheng/hyacinth/experiments/expe_logs_10round/topo/batch_20260422_200323_topo/n80_mix4L3M3S"

  "/home/xuheng/hyacinth/experiments/expe_logs_10round/workload/batch_20260422_200323_workload/cdf_fbcoco"
  "/home/xuheng/hyacinth/experiments/expe_logs_10round/workload/batch_20260422_200323_workload/cdf_fbcoco_january_2024"
  "/home/xuheng/hyacinth/experiments/expe_logs_10round/workload/batch_20260422_200323_workload/cdf_fbcoco_february_2024"
  "/home/xuheng/hyacinth/experiments/expe_logs_10round/workload/batch_20260422_200323_workload/cdf_fbcoco_march_2024"
)

# Optional override.
# If empty:
# - same parent CASE_DIRS -> use that parent
# - mixed parent CASE_DIRS -> auto-create a merge output dir
OUT_DIR=""

PLOT_AGG_SEED="$HTSIM_ROOT/plot/aggregate_seed_summaries.py"
BATCH_SUMMARY_REBUILT=""
AGG_LOG=""

csv_escape() {
  local s="$1"
  s="${s//\"/\"\"}"
  printf "\"%s\"" "$s"
}

kv_get() {
  local file="$1"
  local key="$2"
  if [[ ! -f "$file" ]]; then
    echo ""
    return 0
  fi
  awk -F= -v key="$key" '$1 == key {print substr($0, index($0, "=") + 1)}' "$file" | tail -n 1
}

seed_status_from_manifest() {
  local manifest="$1"
  if [[ ! -f "$manifest" ]]; then
    echo "failed"
    return 0
  fi

  awk -F',' '
    NR == 1 {
      for (i = 1; i <= NF; ++i) {
        if ($i == "status") {
          status_col = i
          break
        }
      }
      next
    }
    {
      row_count++
      if (status_col <= 0) {
        bad = 1
        next
      }
      gsub(/^[ \t"]+|[ \t"]+$/, "", $status_col)
      if ($status_col != "ok") {
        bad = 1
      }
    }
    END {
      if (status_col <= 0 || row_count == 0 || bad) print "failed"
      else print "ok"
    }
  ' "$manifest"
}

if [[ ${#CASE_DIRS[@]} -eq 0 ]]; then
  echo "[fatal] CASE_DIRS is empty" >&2
  exit 1
fi
if [[ ! -f "$PLOT_AGG_SEED" ]]; then
  echo "[fatal] missing aggregate script: $PLOT_AGG_SEED" >&2
  exit 1
fi

common_parent="$(dirname "${CASE_DIRS[0]}")"
parent_mismatch=0
for case_dir in "${CASE_DIRS[@]}"; do
  if [[ ! -d "$case_dir" ]]; then
    echo "[fatal] missing CASE_DIR: $case_dir" >&2
    exit 1
  fi
  if [[ "$(dirname "$case_dir")" != "$common_parent" ]]; then
    parent_mismatch=1
  fi
done

if [[ -z "$OUT_DIR" ]]; then
  if [[ "$parent_mismatch" -eq 1 ]]; then
    run_ts="$(date +%Y%m%d_%H%M%S)"
    OUT_DIR="$HTSIM_ROOT/experiments/seed_extract_outputs/mixed_cases_$run_ts"
    echo "[warn] CASE_DIRS have different parents; using auto OUT_DIR: $OUT_DIR"
  else
    OUT_DIR="$common_parent"
  fi
fi

if [[ ! -d "$OUT_DIR" ]]; then
  mkdir -p "$OUT_DIR"
fi

BATCH_SUMMARY_REBUILT="${BATCH_SUMMARY_REBUILT:-$OUT_DIR/batch_summary_rebuilt_selected_cases.csv}"
AGG_LOG="${AGG_LOG:-$OUT_DIR/seed_avg_summary_rebuilt.log}"

echo "case_tag,seed,model_mix,frag,load,nrack,workload,status,run_dir" > "$BATCH_SUMMARY_REBUILT"

case_count=0
seed_count=0
ok_count=0
failed_count=0

shopt -s nullglob
for case_dir in "${CASE_DIRS[@]}"; do
  seed_dirs=("$case_dir"/seed_*)
  if [[ ${#seed_dirs[@]} -eq 0 ]]; then
    echo "[fatal] CASE_DIR must contain seed_*: $case_dir" >&2
    exit 1
  fi

  case_base="$(basename "$case_dir")"
  ((case_count++))

  for seed_dir in "${seed_dirs[@]}"; do
    [[ -d "$seed_dir" ]] || continue
    seed_name="$(basename "$seed_dir")"
    if [[ ! "$seed_name" =~ ^seed_[0-9]+$ ]]; then
      continue
    fi

    traffic_seed="${seed_name#seed_}"
    # Use "..._seed42" form so aggregate parser groups all seed rounds into one case.
    case_tag="${case_base}_seed${traffic_seed}"
    run_meta="$seed_dir/summary/run_meta.txt"
    manifest="$seed_dir/summary/run_manifest.csv"

    model_mix="$(kv_get "$run_meta" "model_mix")"
    frag="$(kv_get "$run_meta" "frag_level")"
    load="$(kv_get "$run_meta" "load")"
    nrack="$(kv_get "$run_meta" "nrack")"
    workload="$(kv_get "$run_meta" "workload")"
    status="$(seed_status_from_manifest "$manifest")"

    ((seed_count++))
    if [[ "$status" == "ok" ]]; then
      ((ok_count++))
    else
      ((failed_count++))
    fi

    printf "%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
      "$(csv_escape "$case_tag")" \
      "$(csv_escape "$traffic_seed")" \
      "$(csv_escape "$model_mix")" \
      "$(csv_escape "$frag")" \
      "$(csv_escape "$load")" \
      "$(csv_escape "$nrack")" \
      "$(csv_escape "$workload")" \
      "$(csv_escape "$status")" \
      "$(csv_escape "$seed_dir")" \
      >> "$BATCH_SUMMARY_REBUILT"
  done
done

if [[ "$seed_count" -eq 0 ]]; then
  echo "[fatal] no seed_* runs found under: $BATCH_DIR" >&2
  exit 1
fi

echo "[extract] cases   : $case_count"
echo "[extract] seeds   : $seed_count"
echo "[extract] ok      : $ok_count"
echo "[extract] failed  : $failed_count"
echo "[extract] rebuilt : $BATCH_SUMMARY_REBUILT"

python3 "$PLOT_AGG_SEED" \
  --batch_summary "$BATCH_SUMMARY_REBUILT" \
  --out_dir "$OUT_DIR" \
  > "$AGG_LOG" 2>&1
rc=$?

if [[ $rc -ne 0 ]]; then
  echo "[fatal] aggregation failed, see: $AGG_LOG" >&2
  exit $rc
fi

echo "[plot] done"
echo "[plot] log : $AGG_LOG"
echo "[plot] global   : $OUT_DIR/seed_avg_summary"
echo "[plot] case dirs:"
for case_dir in "${CASE_DIRS[@]}"; do
  echo "  - $case_dir/seed_avg_summary"
done
exit 0
