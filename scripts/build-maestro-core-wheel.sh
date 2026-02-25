#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist/core}"

mkdir -p "$OUT_DIR"

python3 -m pip install --upgrade build
python3 -m build --wheel "$ROOT_DIR/packages/maestro-engine" --outdir "$OUT_DIR"
python3 -m build --wheel "$ROOT_DIR/packages/maestro-solo" --outdir "$OUT_DIR"

echo "Core wheel artifacts written to: $OUT_DIR"
