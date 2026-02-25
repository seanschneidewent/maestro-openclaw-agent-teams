#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/seanschneidewent/maestro-openclaw-agent-teams.git"
INSTALL_ROOT_DEFAULT="$HOME/.maestro"
REPO_DIR_DEFAULT="$INSTALL_ROOT_DEFAULT/maestro-openclaw-agent-teams"
VENV_DIR_DEFAULT="$INSTALL_ROOT_DEFAULT/venv-maestro-solo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REPO_URL="${MAESTRO_REPO_URL:-$REPO_URL_DEFAULT}"
REPO_DIR="${MAESTRO_REPO_DIR:-$REPO_DIR_DEFAULT}"
VENV_DIR="${MAESTRO_VENV_DIR:-$VENV_DIR_DEFAULT}"
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

  case "${reply,,}" in
    y|yes) return 0 ;;
    *) return 1 ;;
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

clone_or_update_repo() {
  if [[ -d "$SCRIPT_REPO_ROOT/.git" && "${MAESTRO_USE_LOCAL_REPO:-auto}" != "0" ]]; then
    REPO_DIR="$SCRIPT_REPO_ROOT"
    log "Using local checkout: $REPO_DIR"
    return 0
  fi

  mkdir -p "$(dirname "$REPO_DIR")"

  if [[ -d "$REPO_DIR/.git" ]]; then
    log "Updating existing repo: $REPO_DIR"
    git -C "$REPO_DIR" fetch --all --prune
    git -C "$REPO_DIR" pull --ff-only || warn "git pull failed. Continuing with existing checkout."
    return 0
  fi

  if [[ -d "$REPO_DIR" ]]; then
    fatal "Target directory exists but is not a git repo: $REPO_DIR"
  fi

  log "Cloning repo: $REPO_URL"
  git clone "$REPO_URL" "$REPO_DIR"
}

install_maestro_packages() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  log "Installing Maestro packages (editable)..."
  "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
  "$PYTHON_BIN" -m pip install -e "$REPO_DIR/packages/maestro-engine" -e "$REPO_DIR/packages/maestro-solo"
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

run_quick_setup() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  log "Starting quick setup..."
  "$PYTHON_BIN" -m maestro_solo.cli setup --quick
}

start_runtime() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  log "Starting Maestro runtime..."
  exec "$PYTHON_BIN" -m maestro_solo.cli up --tui
}

main() {
  ensure_macos
  ensure_homebrew
  ensure_python
  ensure_node_npm
  ensure_openclaw
  clone_or_update_repo
  ensure_virtualenv
  install_maestro_packages
  run_quick_setup
  start_runtime
}

main "$@"
