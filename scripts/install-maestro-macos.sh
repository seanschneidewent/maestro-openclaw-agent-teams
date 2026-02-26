#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT_DEFAULT="$HOME/.maestro"
SOLO_HOME_DEFAULT="$HOME/.maestro-solo"
VENV_DIR_DEFAULT="$INSTALL_ROOT_DEFAULT/venv-maestro-solo"
INSTALL_CHANNEL_DEFAULT="auto"
INSTALL_FLOW_DEFAULT="free"
INSTALL_INTENT_DEFAULT=""
PRO_PLAN_DEFAULT="solo_monthly"
CORE_PACKAGE_SPEC_DEFAULT=""
PRO_PACKAGE_SPEC_DEFAULT=""
AUTO_APPROVE_DEFAULT="auto"
OPENCLAW_PROFILE_DEFAULT="maestro-solo"
ALLOW_SHARED_OPENCLAW_DEFAULT="0"

# Avoid BASH_SOURCE array access to keep curl|bash + nounset behavior stable.
SCRIPT_SOURCE="${0:-}"
if [[ -n "$SCRIPT_SOURCE" && "$SCRIPT_SOURCE" != "bash" && "$SCRIPT_SOURCE" != "-bash" && -f "$SCRIPT_SOURCE" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  SCRIPT_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  # When executed via stdin (e.g. curl | bash), BASH_SOURCE can be unset.
  SCRIPT_DIR="$(pwd)"
  SCRIPT_REPO_ROOT="$SCRIPT_DIR"
fi

SOLO_HOME="${MAESTRO_SOLO_HOME:-$SOLO_HOME_DEFAULT}"
VENV_DIR="${MAESTRO_VENV_DIR:-$VENV_DIR_DEFAULT}"
INSTALL_CHANNEL_RAW="${MAESTRO_INSTALL_CHANNEL:-$INSTALL_CHANNEL_DEFAULT}"
INSTALL_FLOW_RAW="${MAESTRO_INSTALL_FLOW:-$INSTALL_FLOW_DEFAULT}"
INSTALL_INTENT_RAW="${MAESTRO_INSTALL_INTENT:-$INSTALL_INTENT_DEFAULT}"
CORE_PACKAGE_SPEC="${MAESTRO_CORE_PACKAGE_SPEC:-$CORE_PACKAGE_SPEC_DEFAULT}"
PRO_PACKAGE_SPEC="${MAESTRO_PRO_PACKAGE_SPEC:-$PRO_PACKAGE_SPEC_DEFAULT}"
PRO_PLAN_ID="${MAESTRO_PRO_PLAN_ID:-$PRO_PLAN_DEFAULT}"
PURCHASE_EMAIL="${MAESTRO_PURCHASE_EMAIL:-}"
USE_LOCAL_REPO="${MAESTRO_USE_LOCAL_REPO:-0}"
FORCE_PRO_PURCHASE="${MAESTRO_FORCE_PRO_PURCHASE:-0}"
AUTO_APPROVE_RAW="${MAESTRO_INSTALL_AUTO:-$AUTO_APPROVE_DEFAULT}"
OPENCLAW_PROFILE_RAW="${MAESTRO_OPENCLAW_PROFILE:-$OPENCLAW_PROFILE_DEFAULT}"
ALLOW_SHARED_OPENCLAW_RAW="${MAESTRO_ALLOW_SHARED_OPENCLAW:-$ALLOW_SHARED_OPENCLAW_DEFAULT}"
INSTALL_CHANNEL=""
INSTALL_FLOW=""
INSTALL_INTENT=""
OPENCLAW_PROFILE=""
PYTHON_BIN=""
AUTO_APPROVE="0"
ALLOW_SHARED_OPENCLAW="0"

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

  local reply_lower
  reply_lower="$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')"

  case "$reply_lower" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

is_truthy() {
  local value
  value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$value" in
    1|true|yes|on) return 0 ;;
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
    free|pro|install) INSTALL_FLOW="$clean" ;;
    *)
      fatal "Invalid MAESTRO_INSTALL_FLOW='$INSTALL_FLOW_RAW' (expected free, pro, or install)."
      ;;
  esac
}

normalize_intent() {
  local clean
  clean="$(printf '%s' "$INSTALL_INTENT_RAW" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [[ "$clean" == "core" ]]; then
    clean="free"
  fi
  case "$clean" in
    free|pro) INSTALL_INTENT="$clean" ;;
    "") INSTALL_INTENT="" ;;
    *)
      fatal "Invalid MAESTRO_INSTALL_INTENT='$INSTALL_INTENT_RAW' (expected empty, free, or pro)."
      ;;
  esac
}

normalize_openclaw_profile() {
  local clean
  clean="$(printf '%s' "$OPENCLAW_PROFILE_RAW" | xargs)"
  case "$(printf '%s' "$clean" | tr '[:upper:]' '[:lower:]')" in
    ""|default|none|off|shared)
      if [[ "$ALLOW_SHARED_OPENCLAW" == "1" ]]; then
        OPENCLAW_PROFILE=""
      else
        fatal "Shared OpenClaw profile is disabled. Use MAESTRO_OPENCLAW_PROFILE=maestro-solo (default) or set MAESTRO_ALLOW_SHARED_OPENCLAW=1 to override."
      fi
      ;;
    *)
      if [[ "$clean" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
        OPENCLAW_PROFILE="$clean"
      else
        fatal "Invalid MAESTRO_OPENCLAW_PROFILE='$OPENCLAW_PROFILE_RAW' (letters/numbers/._- only)."
      fi
      ;;
  esac
}

resolve_shared_openclaw_flag() {
  local clean
  clean="$(printf '%s' "$ALLOW_SHARED_OPENCLAW_RAW" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$clean" in
    1|true|yes|on)
      ALLOW_SHARED_OPENCLAW="1"
      warn "Unsafe mode enabled: installer may modify shared ~/.openclaw state."
      ;;
    0|false|no|off|"")
      ALLOW_SHARED_OPENCLAW="0"
      ;;
    *)
      fatal "Invalid MAESTRO_ALLOW_SHARED_OPENCLAW='$ALLOW_SHARED_OPENCLAW_RAW' (expected true/false or 1/0)."
      ;;
  esac
}

resolve_auto_approve() {
  local clean
  clean="$(printf '%s' "$AUTO_APPROVE_RAW" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$clean" in
    1|true|yes|on)
      AUTO_APPROVE="1"
      ;;
    0|false|no|off)
      AUTO_APPROVE="0"
      ;;
    auto|"")
      if [[ ! -t 0 || ! -t 1 ]]; then
        AUTO_APPROVE="1"
      else
        AUTO_APPROVE="0"
      fi
      ;;
    *)
      fatal "Invalid MAESTRO_INSTALL_AUTO='$AUTO_APPROVE_RAW' (expected auto, true/false, or 1/0)."
      ;;
  esac
  if [[ "$AUTO_APPROVE" == "1" ]]; then
    log "Auto-approve mode enabled for prerequisite installation."
  fi
}

resolve_auto_channel() {
  if [[ "$INSTALL_CHANNEL" != "auto" ]]; then
    return 0
  fi
  if [[ "$INSTALL_FLOW" == "pro" ]]; then
    INSTALL_CHANNEL="pro"
  elif [[ "$INSTALL_FLOW" == "install" && "$INSTALL_INTENT" == "pro" ]]; then
    INSTALL_CHANNEL="pro"
  else
    INSTALL_CHANNEL="core"
  fi
  if [[ -n "$INSTALL_INTENT" ]]; then
    log "Auto install channel resolved to '$INSTALL_CHANNEL' for flow '$INSTALL_FLOW' (intent '$INSTALL_INTENT')."
  else
    log "Auto install channel resolved to '$INSTALL_CHANNEL' for flow '$INSTALL_FLOW'."
  fi
}

refresh_path_for_brew() {
  if [[ -x "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x "/usr/local/bin/brew" ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

prime_sudo_for_noninteractive_homebrew() {
  if [[ "${EUID:-$(id -u)}" == "0" ]]; then
    return 0
  fi
  if [[ ! -x "/usr/bin/sudo" ]]; then
    fatal "sudo is required for Homebrew installation on macOS."
  fi
  if /usr/bin/sudo -n -v >/dev/null 2>&1; then
    return 0
  fi
  log "Homebrew installation requires administrator privileges."
  if [[ ! -r "/dev/tty" ]]; then
    fatal "Cannot request sudo credentials because no terminal is attached."
  fi
  /usr/bin/sudo -v </dev/tty || fatal "Failed to obtain sudo credentials for Homebrew installation."
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

  if [[ "$AUTO_APPROVE" == "1" ]]; then
    prime_sudo_for_noninteractive_homebrew
    env NONINTERACTIVE=1 CI=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  else
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
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

attach_stdin_to_tty_if_available() {
  if [[ -t 0 ]]; then
    return 0
  fi
  if [[ -r "/dev/tty" ]]; then
    exec </dev/tty
    log "Attached interactive prompts to /dev/tty."
    return 0
  fi
  fatal "Interactive setup requires a terminal. Re-run this installer from an interactive shell."
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

run_install_journey() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"

  local -a journey_args=(journey --flow "$INSTALL_FLOW" --channel "$INSTALL_CHANNEL" --plan "$PRO_PLAN_ID")
  if [[ -n "$INSTALL_INTENT" ]]; then
    journey_args+=(--intent "$INSTALL_INTENT")
  fi

  local billing_url="${MAESTRO_BILLING_URL:-}"
  if [[ -n "$billing_url" ]]; then
    journey_args+=(--billing-url "$billing_url")
  fi

  local purchase_email
  purchase_email="$(printf '%s' "$PURCHASE_EMAIL" | xargs)"
  if [[ -n "$purchase_email" ]]; then
    journey_args+=(--email "$purchase_email")
  fi

  if is_truthy "$FORCE_PRO_PURCHASE"; then
    journey_args+=(--force-pro-purchase)
  fi

  if ! is_truthy "${MAESTRO_SETUP_REPLAY:-1}"; then
    journey_args+=(--no-replay-setup)
  fi

  exec env \
    MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" \
    MAESTRO_SOLO_HOME="$SOLO_HOME" \
    MAESTRO_OPENCLAW_PROFILE="$OPENCLAW_PROFILE" \
    MAESTRO_ALLOW_SHARED_OPENCLAW="$ALLOW_SHARED_OPENCLAW" \
    "$PYTHON_BIN" -m maestro_solo.cli "${journey_args[@]}"
}

main() {
  normalize_channel
  normalize_flow
  normalize_intent
  resolve_shared_openclaw_flag
  normalize_openclaw_profile
  resolve_auto_approve
  resolve_auto_channel
  ensure_macos
  ensure_homebrew
  ensure_python
  ensure_node_npm
  ensure_openclaw
  ensure_virtualenv
  install_maestro_packages
  persist_install_channel
  attach_stdin_to_tty_if_available
  run_install_journey
}

main "$@"
