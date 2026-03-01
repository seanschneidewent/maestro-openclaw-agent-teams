#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT_DEFAULT="$HOME/.maestro"
FLEET_HOME_DEFAULT="$HOME/.maestro-fleet"
VENV_DIR_DEFAULT="$INSTALL_ROOT_DEFAULT/venv-maestro-fleet"
AUTO_APPROVE_DEFAULT="auto"

FLEET_HOME="${MAESTRO_FLEET_HOME:-$FLEET_HOME_DEFAULT}"
VENV_DIR="${MAESTRO_VENV_DIR:-$VENV_DIR_DEFAULT}"
PACKAGE_SPEC="${MAESTRO_FLEET_PACKAGE_SPEC:-}"
USE_LOCAL_REPO="${MAESTRO_USE_LOCAL_REPO:-0}"
AUTO_APPROVE_RAW="${MAESTRO_INSTALL_AUTO:-$AUTO_APPROVE_DEFAULT}"
REQUIRE_TAILSCALE_RAW="${MAESTRO_FLEET_REQUIRE_TAILSCALE:-0}"
AUTO_DEPLOY_RAW="${MAESTRO_FLEET_DEPLOY:-1}"
PYTHON_BIN=""
AUTO_APPROVE="0"
REQUIRE_TAILSCALE="0"
AUTO_DEPLOY="1"

SCRIPT_SOURCE="${0:-}"
if [[ -n "$SCRIPT_SOURCE" && "$SCRIPT_SOURCE" != "bash" && "$SCRIPT_SOURCE" != "-bash" && -f "$SCRIPT_SOURCE" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  SCRIPT_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  SCRIPT_DIR="$(pwd)"
  SCRIPT_REPO_ROOT="$SCRIPT_DIR"
fi

log() {
  printf '[maestro-fleet-install] %s\n' "$*"
}

warn() {
  printf '[maestro-fleet-install] WARN: %s\n' "$*" >&2
}

fatal() {
  printf '[maestro-fleet-install] ERROR: %s\n' "$*" >&2
  exit 1
}

prompt_yes_no() {
  local prompt="$1"
  local default="${2:-y}"
  local reply

  if [[ "$AUTO_APPROVE" == "1" ]]; then
    if [[ "$default" == "y" ]]; then
      log "$prompt (auto-yes)"
      return 0
    fi
    log "$prompt (auto-no)"
    return 1
  fi

  if [[ "$default" == "y" ]]; then
    read -r -p "$prompt [Y/n] " reply || true
    reply="${reply:-y}"
  else
    read -r -p "$prompt [y/N] " reply || true
    reply="${reply:-n}"
  fi

  case "$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

resolve_flag() {
  local raw="$1"
  local out_name="$2"
  local default="${3:-0}"
  local clean

  clean="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$clean" in
    1|true|yes|on) printf -v "$out_name" '1' ;;
    0|false|no|off) printf -v "$out_name" '0' ;;
    "")
      printf -v "$out_name" "$default"
      ;;
    auto)
      if [[ "$out_name" == "AUTO_APPROVE" ]]; then
        if [[ ! -t 0 || ! -t 1 ]]; then
          printf -v "$out_name" '1'
        else
          printf -v "$out_name" '0'
        fi
      else
        printf -v "$out_name" "$default"
      fi
      ;;
    *)
      fatal "Invalid value '$raw' for $out_name"
      ;;
  esac
}

python_version_ok() {
  if ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi
  local status
  status="$(python3 - <<'PY'
import sys
print("ok" if sys.version_info >= (3, 11) else "bad")
PY
)"
  [[ "$status" == "ok" ]]
}

ensure_python() {
  python_version_ok || fatal "Python 3.11+ is required."
  log "Python: $(python3 --version 2>&1)"
}

ensure_node_npm() {
  command -v node >/dev/null 2>&1 || fatal "Node.js is required."
  command -v npm >/dev/null 2>&1 || fatal "npm is required."
  log "Node: $(node --version 2>&1)"
  log "npm: $(npm --version 2>&1)"
}

ensure_openclaw() {
  command -v openclaw >/dev/null 2>&1 || fatal "OpenClaw CLI is required."
  log "OpenClaw: $(openclaw --version 2>&1 || echo 'available')"
}

ensure_tailscale_if_required() {
  if [[ "$REQUIRE_TAILSCALE" != "1" ]]; then
    return 0
  fi
  command -v tailscale >/dev/null 2>&1 || fatal "Tailscale is required when MAESTRO_FLEET_REQUIRE_TAILSCALE=1."
  local ip
  ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
  [[ -n "$ip" ]] || fatal "Tailscale is installed but not connected (run tailscale up)."
  log "Tailscale IPv4: $ip"
}

ensure_virtualenv() {
  mkdir -p "$(dirname "$VENV_DIR")" "$FLEET_HOME"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    log "Creating virtualenv: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  PYTHON_BIN="$VENV_DIR/bin/python"
  [[ -x "$PYTHON_BIN" ]] || fatal "Virtualenv python missing at $PYTHON_BIN"
  "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
}

install_fleet_packages() {
  if [[ "$USE_LOCAL_REPO" == "1" ]]; then
    if [[ ! -d "$SCRIPT_REPO_ROOT/packages/maestro-fleet" || ! -d "$SCRIPT_REPO_ROOT/maestro" ]]; then
      fatal "MAESTRO_USE_LOCAL_REPO=1 requires this script to run from the Maestro repo root."
    fi
    log "Installing Fleet from local repository checkout (development mode)"
    "$PYTHON_BIN" -m pip install -e "$SCRIPT_REPO_ROOT" -e "$SCRIPT_REPO_ROOT/packages/maestro-fleet"
    return 0
  fi

  [[ -n "$PACKAGE_SPEC" ]] || fatal "MAESTRO_FLEET_PACKAGE_SPEC is empty. Set it to wheel URL(s)."
  local spec_normalized="${PACKAGE_SPEC//,/ }"
  local -a pip_args=()
  read -r -a pip_args <<<"$spec_normalized"
  [[ "${#pip_args[@]}" -gt 0 ]] || fatal "No wheel arguments parsed from MAESTRO_FLEET_PACKAGE_SPEC."

  log "Installing Fleet package spec (${#pip_args[@]} pip arg(s))"
  "$PYTHON_BIN" -m pip install "${pip_args[@]}"
}

validate_install() {
  "$VENV_DIR/bin/maestro-fleet" --help >/dev/null
  log "maestro-fleet CLI installed."
}

run_deploy_if_enabled() {
  if [[ "$AUTO_DEPLOY" != "1" ]]; then
    log "Install complete. Run manually: $VENV_DIR/bin/maestro-fleet deploy"
    return 0
  fi
  local -a cmd=("$VENV_DIR/bin/maestro-fleet" "deploy")
  if [[ "$REQUIRE_TAILSCALE" == "1" ]]; then
    cmd+=("--require-tailscale")
  fi
  cmd+=("$@")
  log "Starting Fleet deploy workflow."
  exec "${cmd[@]}"
}

main() {
  resolve_flag "$AUTO_APPROVE_RAW" AUTO_APPROVE 0
  resolve_flag "$REQUIRE_TAILSCALE_RAW" REQUIRE_TAILSCALE 0
  resolve_flag "$AUTO_DEPLOY_RAW" AUTO_DEPLOY 1

  ensure_python
  ensure_node_npm
  ensure_openclaw
  ensure_tailscale_if_required
  ensure_virtualenv
  install_fleet_packages
  validate_install

  if [[ "$AUTO_DEPLOY" == "1" && "$AUTO_APPROVE" == "0" ]]; then
    if prompt_yes_no "Run maestro-fleet deploy now?" "y"; then
      run_deploy_if_enabled "$@"
      return 0
    fi
    log "Skipping deploy. Run manually: $VENV_DIR/bin/maestro-fleet deploy"
    return 0
  fi

  if [[ "$AUTO_DEPLOY" == "1" ]]; then
    run_deploy_if_enabled "$@"
    return 0
  fi

  log "Install complete. Run manually: $VENV_DIR/bin/maestro-fleet deploy"
}

main "$@"
