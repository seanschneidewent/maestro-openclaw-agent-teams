#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist/fleet}"
WHEEL_DIR="$OUT_DIR/wheels"
BUILD_FRONTENDS_RAW="${MAESTRO_FLEET_BUILD_FRONTENDS:-auto}"
BUILD_FRONTENDS="auto"

normalize_build_frontends() {
  local clean
  clean="$(printf '%s' "$BUILD_FRONTENDS_RAW" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$clean" in
    auto|always|never|"") BUILD_FRONTENDS="${clean:-auto}" ;;
    *)
      echo "[fleet-build] ERROR: invalid MAESTRO_FLEET_BUILD_FRONTENDS='$BUILD_FRONTENDS_RAW' (expected auto, always, or never)" >&2
      exit 1
      ;;
  esac
}

build_frontends_if_needed() {
  local workspace_dist="$ROOT_DIR/workspace_frontend/dist"
  local command_center_dist="$ROOT_DIR/command_center_frontend/dist"
  local need_build=0

  if [[ "$BUILD_FRONTENDS" == "always" ]]; then
    need_build=1
  elif [[ "$BUILD_FRONTENDS" == "auto" ]]; then
    if [[ ! -d "$workspace_dist" || ! -d "$command_center_dist" ]]; then
      need_build=1
    fi
  fi

  if [[ "$need_build" != "1" ]]; then
    echo "[fleet-build] Reusing existing frontend dist artifacts."
    return 0
  fi

  command -v npm >/dev/null 2>&1 || {
    echo "[fleet-build] ERROR: npm is required to build frontend assets." >&2
    exit 1
  }

  echo "[fleet-build] Building workspace_frontend"
  npm install --prefix "$ROOT_DIR/workspace_frontend"
  npm run build --prefix "$ROOT_DIR/workspace_frontend"

  echo "[fleet-build] Building command_center_frontend"
  npm install --prefix "$ROOT_DIR/command_center_frontend"
  npm run build --prefix "$ROOT_DIR/command_center_frontend"
}

main() {
  normalize_build_frontends
  mkdir -p "$WHEEL_DIR"
  build_frontends_if_needed

  python3 -m pip install --upgrade build
  python3 -m build --wheel "$ROOT_DIR/packages/maestro-engine" --outdir "$WHEEL_DIR"
  python3 -m build --wheel "$ROOT_DIR" --outdir "$WHEEL_DIR"
  python3 -m build --wheel "$ROOT_DIR/packages/maestro-fleet" --outdir "$WHEEL_DIR"

  echo "[fleet-build] Fleet artifacts written to: $OUT_DIR"
  echo "[fleet-build] Wheels:"
  ls -1 "$WHEEL_DIR"
}

main "$@"
