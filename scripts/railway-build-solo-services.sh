#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if command -v python >/dev/null 2>&1; then
  PY_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
else
  echo "[railway-build] ERROR: python is not available on PATH" >&2
  exit 1
fi

# `maestro-solo` wheel metadata force-includes frontend assets from this path.
# In Railway builds, ignored local artifacts are absent, so create a minimal
# placeholder directory to keep service package install deterministic.
FRONTEND_DIST="$ROOT_DIR/workspace_frontend/dist"
if [[ ! -d "$FRONTEND_DIST" ]]; then
  echo "[railway-build] workspace_frontend/dist missing; creating placeholder"
  mkdir -p "$FRONTEND_DIST"
  cat >"$FRONTEND_DIST/index.html" <<'HTML'
<!doctype html><html><body>maestro-solo service build placeholder</body></html>
HTML
fi

echo "[railway-build] Using $PY_BIN"
"$PY_BIN" -m pip install --upgrade pip
"$PY_BIN" -m pip install -e "$ROOT_DIR/packages/maestro-engine" -e "$ROOT_DIR/packages/maestro-solo"

echo "[railway-build] Installed maestro-engine and maestro-solo"
