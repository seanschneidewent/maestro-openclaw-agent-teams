#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT_DEFAULT="$HOME/.maestro"
SOLO_HOME_DEFAULT="$HOME/.maestro-solo"
VENV_DIR_DEFAULT="$INSTALL_ROOT_DEFAULT/venv-maestro-solo"
INSTALL_CHANNEL_DEFAULT="auto"
INSTALL_FLOW_DEFAULT="free"
PRO_PLAN_DEFAULT="solo_monthly"
CORE_PACKAGE_SPEC_DEFAULT=""
PRO_PACKAGE_SPEC_DEFAULT=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SOLO_HOME="${MAESTRO_SOLO_HOME:-$SOLO_HOME_DEFAULT}"
VENV_DIR="${MAESTRO_VENV_DIR:-$VENV_DIR_DEFAULT}"
INSTALL_CHANNEL_RAW="${MAESTRO_INSTALL_CHANNEL:-$INSTALL_CHANNEL_DEFAULT}"
INSTALL_FLOW_RAW="${MAESTRO_INSTALL_FLOW:-$INSTALL_FLOW_DEFAULT}"
CORE_PACKAGE_SPEC="${MAESTRO_CORE_PACKAGE_SPEC:-$CORE_PACKAGE_SPEC_DEFAULT}"
PRO_PACKAGE_SPEC="${MAESTRO_PRO_PACKAGE_SPEC:-$PRO_PACKAGE_SPEC_DEFAULT}"
PRO_PLAN_ID="${MAESTRO_PRO_PLAN_ID:-$PRO_PLAN_DEFAULT}"
PURCHASE_EMAIL="${MAESTRO_PURCHASE_EMAIL:-}"
USE_LOCAL_REPO="${MAESTRO_USE_LOCAL_REPO:-0}"
INSTALL_CHANNEL=""
INSTALL_FLOW=""
PYTHON_BIN=""

log() {
  printf '[maestro-install] %s\n' "$*"
}

warn() {
  printf '[maestro-install] WARN: %s\n' "$*" >&2
}

fatal() {
  printf '[maestro-install] ERROR: %s\n' "$*" >&2
  exit 1
}

prompt_yes_no() {
  local prompt="$1"
  local default="${2:-y}"
  local reply

  if [[ "$default" == "y" ]]; then
    read -r -p "$prompt [Y/n] " reply || true
    reply="${reply:-y}"
  else
    read -r -p "$prompt [y/N] " reply || true
    reply="${reply:-n}"
  fi

  local reply_lower
  reply_lower="$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')"

  case "$reply_lower" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

normalize_channel() {
  local clean
  clean="$(printf '%s' "$INSTALL_CHANNEL_RAW" | tr '[:upper:]' '[:lower:]')"
  case "$clean" in
    core|pro|auto) INSTALL_CHANNEL="$clean" ;;
    *)
      fatal "Invalid MAESTRO_INSTALL_CHANNEL='$INSTALL_CHANNEL_RAW' (expected auto, core, or pro)."
      ;;
  esac
}

normalize_flow() {
  local clean
  clean="$(printf '%s' "$INSTALL_FLOW_RAW" | tr '[:upper:]' '[:lower:]')"
  case "$clean" in
    free|pro) INSTALL_FLOW="$clean" ;;
    *)
      fatal "Invalid MAESTRO_INSTALL_FLOW='$INSTALL_FLOW_RAW' (expected free or pro)."
      ;;
  esac
}

refresh_path_for_brew() {
  if [[ -x "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x "/usr/local/bin/brew" ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

ensure_macos() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    fatal "This installer currently supports macOS only."
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
    fatal "Homebrew is required for automatic prerequisite installation."
  fi

  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  refresh_path_for_brew

  command -v brew >/dev/null 2>&1 || fatal "Homebrew install succeeded but brew is not on PATH. Open a new terminal and rerun."
  log "Homebrew: installed"
}

python_version_ok() {
  if ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi

  local status
  status="$(python3 - <<'PY'
import sys
print('ok' if sys.version_info >= (3, 11) else 'bad')
PY
)"
  [[ "$status" == "ok" ]]
}

ensure_python() {
  if python_version_ok; then
    log "Python: $(python3 --version 2>&1)"
    return 0
  fi

  warn "Python 3.11+ is missing."
  if ! prompt_yes_no "Install Python now (brew install python)?" "y"; then
    fatal "Python 3.11+ is required."
  fi

  brew install python
  python_version_ok || fatal "Python install failed or version is still below 3.11"
  log "Python: $(python3 --version 2>&1)"
}

ensure_node_npm() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    log "Node: $(node --version 2>&1)"
    log "npm: $(npm --version 2>&1)"
    return 0
  fi

  warn "Node.js/npm are missing."
  if ! prompt_yes_no "Install Node.js now (brew install node)?" "y"; then
    fatal "Node.js/npm are required."
  fi

  brew install node
  command -v node >/dev/null 2>&1 || fatal "Node.js install failed"
  command -v npm >/dev/null 2>&1 || fatal "npm install failed"
  log "Node: $(node --version 2>&1)"
  log "npm: $(npm --version 2>&1)"
}

ensure_openclaw() {
  if command -v openclaw >/dev/null 2>&1; then
    log "OpenClaw: $(openclaw --version 2>&1 || echo 'available')"
    return 0
  fi

  warn "OpenClaw is missing."
  if ! prompt_yes_no "Install OpenClaw now (npm install -g openclaw)?" "y"; then
    fatal "OpenClaw is required."
  fi

  npm install -g openclaw
  command -v openclaw >/dev/null 2>&1 || fatal "OpenClaw install failed"
  log "OpenClaw: $(openclaw --version 2>&1 || echo 'installed')"
}

ensure_virtualenv() {
  mkdir -p "$(dirname "$VENV_DIR")"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    log "Creating virtualenv: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  PYTHON_BIN="$VENV_DIR/bin/python"
  [[ -x "$PYTHON_BIN" ]] || fatal "Virtualenv python not found at $PYTHON_BIN"
  log "Virtualenv: $VENV_DIR"
}

persist_install_channel() {
  mkdir -p "$SOLO_HOME"
  printf '%s\n' "$INSTALL_CHANNEL" >"$SOLO_HOME/install-channel.txt"
  log "Install channel persisted: $INSTALL_CHANNEL"
}

install_maestro_packages() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel

  if [[ "$USE_LOCAL_REPO" == "1" ]]; then
    if [[ ! -d "$SCRIPT_REPO_ROOT/packages/maestro-solo" || ! -d "$SCRIPT_REPO_ROOT/packages/maestro-engine" ]]; then
      fatal "MAESTRO_USE_LOCAL_REPO=1 requires this script to run from a repo checkout with packages/maestro-solo and packages/maestro-engine."
    fi
    log "Installing from local repository checkout (development mode)"
    "$PYTHON_BIN" -m pip install -e "$SCRIPT_REPO_ROOT/packages/maestro-engine" -e "$SCRIPT_REPO_ROOT/packages/maestro-solo"
    return 0
  fi

  local package_spec="$CORE_PACKAGE_SPEC"
  if [[ "$INSTALL_CHANNEL" == "pro" ]]; then
    package_spec="$PRO_PACKAGE_SPEC"
    if [[ -z "$package_spec" ]]; then
      warn "MAESTRO_PRO_PACKAGE_SPEC is empty; falling back to MAESTRO_CORE_PACKAGE_SPEC."
      package_spec="$CORE_PACKAGE_SPEC"
    fi
  fi
  [[ -n "$package_spec" ]] || fatal "Package spec is empty. Set MAESTRO_CORE_PACKAGE_SPEC / MAESTRO_PRO_PACKAGE_SPEC to private wheel spec(s), or set MAESTRO_USE_LOCAL_REPO=1 for local development."

  local spec_normalized="${package_spec//,/ }"
  local -a pip_args=()
  read -r -a pip_args <<<"$spec_normalized"
  [[ "${#pip_args[@]}" -gt 0 ]] || fatal "No install arguments parsed from package spec: '$package_spec'"

  log "Installing package spec for channel '$INSTALL_CHANNEL' (${#pip_args[@]} pip arg(s))"
  "$PYTHON_BIN" -m pip install "${pip_args[@]}"
}

prompt_email() {
  local entered="$PURCHASE_EMAIL"
  entered="$(printf '%s' "$entered" | xargs)"
  while [[ -z "$entered" || "$entered" != *"@"* ]]; do
    read -r -p "Enter your billing email: " entered || true
    entered="$(printf '%s' "$entered" | xargs)"
    if [[ -z "$entered" || "$entered" != *"@"* ]]; then
      warn "Please enter a valid email address."
    fi
  done
  PURCHASE_EMAIL="$entered"
}

run_quick_setup() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  log "Starting quick setup..."
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" "$PYTHON_BIN" -m maestro_solo.cli setup --quick
}

run_pro_purchase() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  if [[ "$INSTALL_FLOW" != "pro" ]]; then
    return 0
  fi

  log "Pro flow selected: purchase is required before launch."
  prompt_email
  log "Starting secure checkout for $PURCHASE_EMAIL"
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" \
    "$PYTHON_BIN" -m maestro_solo.cli purchase \
      --email "$PURCHASE_EMAIL" \
      --plan "$PRO_PLAN_ID" \
      --mode live \
    || fatal "Pro purchase failed. Re-run installer or run 'maestro-solo purchase --email $PURCHASE_EMAIL' manually."
}

start_runtime() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  if [[ "$INSTALL_FLOW" == "pro" ]]; then
    log "Purchase complete. Starting Maestro Pro runtime..."
  else
    log "Starting Maestro Free runtime..."
  fi
  exec MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" "$PYTHON_BIN" -m maestro_solo.cli up --tui
}

main() {
  normalize_channel
  normalize_flow
  ensure_macos
  ensure_homebrew
  ensure_python
  ensure_node_npm
  ensure_openclaw
  ensure_virtualenv
  install_maestro_packages
  persist_install_channel
  run_quick_setup
  run_pro_purchase
  start_runtime
}

main "$@"
