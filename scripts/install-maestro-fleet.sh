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
OPENCLAW_PROFILE_RAW="${MAESTRO_OPENCLAW_PROFILE:-maestro-fleet}"
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

is_macos() {
  [[ "$(uname -s)" == "Darwin" ]]
}

is_linux() {
  [[ "$(uname -s)" == "Linux" ]]
}

refresh_path_for_brew() {
  if [[ -x "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x "/usr/local/bin/brew" ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

run_privileged() {
  if [[ "${EUID:-$(id -u)}" == "0" ]]; then
    "$@"
    return 0
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    fatal "Command requires elevated privileges but sudo is unavailable: $*"
  fi
  if [[ "$AUTO_APPROVE" == "1" ]]; then
    sudo -n "$@" || fatal "Unable to run with sudo non-interactively: $*"
  else
    sudo "$@"
  fi
}

ensure_homebrew() {
  refresh_path_for_brew
  if command -v brew >/dev/null 2>&1; then
    log "Homebrew: found"
    return 0
  fi

  warn "Homebrew is missing."
  if ! prompt_yes_no "Install Homebrew now?" "y"; then
    fatal "Homebrew is required for automatic prerequisite setup on macOS."
  fi

  if [[ "$AUTO_APPROVE" == "1" ]]; then
    env NONINTERACTIVE=1 CI=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  else
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi

  refresh_path_for_brew
  command -v brew >/dev/null 2>&1 || fatal "Homebrew install succeeded but brew is not on PATH. Open a new terminal and rerun."
  log "Homebrew: installed"
}

ensure_apt() {
  command -v apt-get >/dev/null 2>&1 || fatal "Automatic Linux prerequisite setup currently expects apt-get."
  run_privileged apt-get update -y
}

install_npm_global_user() {
  mkdir -p "$HOME/.npm-global/bin"
  npm config set prefix "$HOME/.npm-global"
  export PATH="$HOME/.npm-global/bin:$PATH"
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
  if ! python_version_ok; then
    warn "Python 3.11+ is required."
    if ! prompt_yes_no "Install/upgrade Python now?" "y"; then
      fatal "Python 3.11+ is required."
    fi

    if is_macos; then
      ensure_homebrew
      brew install python
    elif is_linux; then
      ensure_apt
      run_privileged apt-get install -y python3 python3-venv python3-pip
    else
      fatal "Unsupported platform for automatic Python install: $(uname -s)"
    fi
  fi

  python_version_ok || fatal "Python 3.11+ is still unavailable after install attempt."
  log "Python: $(python3 --version 2>&1)"
}

ensure_node_npm() {
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    warn "Node.js/npm are required."
    if ! prompt_yes_no "Install Node.js and npm now?" "y"; then
      fatal "Node.js and npm are required."
    fi

    if is_macos; then
      ensure_homebrew
      brew install node
    elif is_linux; then
      ensure_apt
      run_privileged apt-get install -y nodejs npm
    else
      fatal "Unsupported platform for automatic Node install: $(uname -s)"
    fi
  fi

  command -v node >/dev/null 2>&1 || fatal "Node.js install failed."
  command -v npm >/dev/null 2>&1 || fatal "npm install failed."
  log "Node: $(node --version 2>&1)"
  log "npm: $(npm --version 2>&1)"
}

ensure_openclaw() {
  if ! command -v openclaw >/dev/null 2>&1; then
    warn "OpenClaw CLI is required."
    if ! prompt_yes_no "Install OpenClaw now (npm install -g openclaw)?" "y"; then
      fatal "OpenClaw CLI is required."
    fi
    if ! npm install -g openclaw; then
      warn "Global npm install failed; retrying with user npm prefix (~/.npm-global)."
      install_npm_global_user
      npm install -g openclaw || fatal "OpenClaw install failed."
    fi
  fi
  command -v openclaw >/dev/null 2>&1 || fatal "OpenClaw CLI not found on PATH after install."
  log "OpenClaw: $(openclaw --version 2>&1 || echo 'available')"
}

wait_for_tailscale_ip() {
  local timeout_seconds="${1:-90}"
  local elapsed=0
  local step=3
  local ip=""

  while [[ "$elapsed" -lt "$timeout_seconds" ]]; do
    ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
    if [[ -n "$ip" ]]; then
      printf '%s' "$ip"
      return 0
    fi
    sleep "$step"
    elapsed=$((elapsed + step))
  done
  return 1
}

ensure_tailscale_if_required() {
  if [[ "$REQUIRE_TAILSCALE" != "1" ]]; then
    return 0
  fi

  if ! command -v tailscale >/dev/null 2>&1; then
    warn "Tailscale is required in this deploy mode."
    if ! prompt_yes_no "Install Tailscale now?" "y"; then
      fatal "Tailscale is required when MAESTRO_FLEET_REQUIRE_TAILSCALE=1."
    fi

    if is_macos; then
      ensure_homebrew
      brew install --cask tailscale
      open -a Tailscale >/dev/null 2>&1 || true
    elif is_linux; then
      run_privileged sh -c "curl -fsSL https://tailscale.com/install.sh | sh"
    else
      fatal "Unsupported platform for automatic Tailscale install: $(uname -s)"
    fi
  fi

  command -v tailscale >/dev/null 2>&1 || fatal "Tailscale install failed."

  local ip
  ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
  if [[ -n "$ip" ]]; then
    log "Tailscale IPv4: $ip"
    return 0
  fi

  warn "Tailscale is installed but not connected."
  if [[ "$AUTO_APPROVE" == "1" ]]; then
    warn "Waiting briefly for Tailscale connection..."
    ip="$(wait_for_tailscale_ip 60 || true)"
  else
    if is_macos; then
      warn "Open the Tailscale app and sign in, then continue."
      open -a Tailscale >/dev/null 2>&1 || true
    fi
    if is_linux && prompt_yes_no "Run 'tailscale up' now?" "y"; then
      tailscale up || true
    fi
    if prompt_yes_no "Retry Tailscale connection check now?" "y"; then
      ip="$(wait_for_tailscale_ip 120 || true)"
    fi
  fi

  [[ -n "$ip" ]] || fatal "Tailscale is not connected yet. Complete Tailscale sign-in and rerun (or use MAESTRO_FLEET_REQUIRE_TAILSCALE=0 for local testing)."
  log "Tailscale IPv4: $ip"
}

ensure_virtualenv() {
  mkdir -p "$(dirname "$VENV_DIR")" "$FLEET_HOME"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    log "Creating virtualenv: $VENV_DIR"
    if ! python3 -m venv "$VENV_DIR"; then
      if is_linux; then
        warn "python3-venv appears missing; attempting install."
        ensure_apt
        run_privileged apt-get install -y python3-venv
        python3 -m venv "$VENV_DIR" || fatal "Failed to create virtualenv after installing python3-venv."
      else
        fatal "Failed to create virtualenv at $VENV_DIR"
      fi
    fi
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
  local arg_count="$#"
  if [[ "$REQUIRE_TAILSCALE" == "1" ]]; then
    cmd+=("--require-tailscale")
  fi
  if [[ ! -t 0 ]]; then
    if [[ "$arg_count" -eq 0 ]]; then
      warn "Non-interactive stdin detected with no deploy flags; skipping auto deploy."
      log "Install complete. Run manually: $VENV_DIR/bin/maestro-fleet deploy"
      return 0
    fi
    cmd+=("--non-interactive")
  fi
  cmd+=("$@")
  log "Starting Fleet deploy workflow."
  exec "${cmd[@]}"
}

main() {
  export MAESTRO_OPENCLAW_PROFILE="${OPENCLAW_PROFILE_RAW}"
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
