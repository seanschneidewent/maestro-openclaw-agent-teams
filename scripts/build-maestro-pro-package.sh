#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist/pro}"
WHEEL_DIR="$OUT_DIR/wheels"
BUILD_BINARY_RAW="${MAESTRO_BUILD_PRO_BINARY:-0}"
BUILD_BINARY=0

BUILD_BINARY_NORMALIZED="$(printf '%s' "$BUILD_BINARY_RAW" | tr '[:upper:]' '[:lower:]')"

case "$BUILD_BINARY_NORMALIZED" in
  1|true|yes) BUILD_BINARY=1 ;;
esac

mkdir -p "$WHEEL_DIR"

python3 -m pip install --upgrade build
python3 -m build --wheel "$ROOT_DIR/packages/maestro-engine" --outdir "$WHEEL_DIR"
python3 -m build --wheel "$ROOT_DIR/packages/maestro-solo" --outdir "$WHEEL_DIR"

echo "Pro artifacts written to: $OUT_DIR"
echo "  Wheels: $WHEEL_DIR"

if [[ "$BUILD_BINARY" == "1" ]]; then
  BUILD_VENV="$OUT_DIR/build-venv"
  BIN_DIR="$OUT_DIR/bin"
  mkdir -p "$BIN_DIR"

  python3 -m venv "$BUILD_VENV"
  "$BUILD_VENV/bin/python" -m pip install --upgrade pip
  "$BUILD_VENV/bin/python" -m pip install "$WHEEL_DIR"/maestro_engine-*.whl "$WHEEL_DIR"/maestro_solo-*.whl

  if ! "$BUILD_VENV/bin/python" -m pip show nuitka >/dev/null 2>&1; then
    "$BUILD_VENV/bin/python" -m pip install "nuitka[onefile]"
  fi

  cat >"$OUT_DIR/maestro_pro_entry.py" <<'PY'
from maestro_solo.cli import main

if __name__ == "__main__":
    main()
PY

  "$BUILD_VENV/bin/python" -m nuitka \
    --onefile \
    --output-dir="$BIN_DIR" \
    --output-filename=maestro-pro \
    "$OUT_DIR/maestro_pro_entry.py"

  echo "  Binary: $BIN_DIR/maestro-pro"
else
  echo "  Binary: skipped (set MAESTRO_BUILD_PRO_BINARY=1 to enable)"
fi
