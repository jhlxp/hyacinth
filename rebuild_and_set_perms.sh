#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Build targets (add/remove here if your module list changes).
BUILD_DIRS=(
  "$ROOT_DIR/src/flat"
  "$ROOT_DIR/src/flat_dep"
  "$ROOT_DIR/traffic_route_injector_cpp"
)

echo "[rebuild] root: $ROOT_DIR"

for d in "${BUILD_DIRS[@]}"; do
  if [[ ! -d "$d" ]]; then
    echo "[rebuild] skip missing dir: $d"
    continue
  fi
  if [[ ! -f "$d/Makefile" && ! -f "$d/makefile" ]]; then
    echo "[rebuild] skip (no Makefile): $d"
    continue
  fi

  echo "[rebuild] entering: $d"
  (
    cd "$d"
    echo "[rebuild] make clean @ $d"
    make clean
    echo "[rebuild] make -j16 @ $d"
    make -j16
  )
done

echo "[perm] chmod -R 777 $ROOT_DIR/experiments/scripts"
chmod -R 777 "$ROOT_DIR/experiments/scripts"

echo "[perm] chmod -R 777 $ROOT_DIR/experiments/expe_sh"
chmod -R 777 "$ROOT_DIR/experiments/expe_sh"

echo "[done] rebuild + permissions completed"

