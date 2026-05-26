#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PY="${PYTHON:-python3}"

mkdir -p "$ROOT/plot/expe_fig/.mplconfig"
export MPLCONFIGDIR="$ROOT/plot/expe_fig/.mplconfig"

"$PY" "$SCRIPT_DIR/plot_fixed_dynamic.py"

echo "[ok] fixed-vs-dynamic figures generated under: $SCRIPT_DIR/figures"
