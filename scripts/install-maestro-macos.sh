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

# Prefer BASH_SOURCE when available, but avoid array indexing for bash 3 + nounset compatibility.
SCRIPT_SOURCE="${BASH_SOURCE:-${0:-}}"
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
CORE_PACKAGE_SPEC="${MAESTRO_CORE_PACKAGE_SPEC:-$CORE_PACKAGE_SPEC_DEFAULT}"
PRO_PACKAGE_SPEC="${MAESTRO_PRO_PACKAGE_SPEC:-$PRO_PACKAGE_SPEC_DEFAULT}"
PRO_PLAN_ID="${MAESTRO_PRO_PLAN_ID:-$PRO_PLAN_DEFAULT}"
PURCHASE_EMAIL="${MAESTRO_PURCHASE_EMAIL:-}"
USE_LOCAL_REPO="${MAESTRO_USE_LOCAL_REPO:-0}"
FORCE_PRO_PURCHASE="${MAESTRO_FORCE_PRO_PURCHASE:-0}"
INSTALL_CHANNEL=""
INSTALL_FLOW=""
PYTHON_BIN=""
PRO_PURCHASE_SKIPPED="0"
STAGE_STEP="0"
STAGE_TOTAL="4"

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

stage() {
  local title="$1"
  STAGE_STEP="$((STAGE_STEP + 1))"
  printf '\n[maestro-install] ===== Step %s/%s: %s =====\n' "$STAGE_STEP" "$STAGE_TOTAL" "$title"
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
    free|pro) INSTALL_FLOW="$clean" ;;
    *)
      fatal "Invalid MAESTRO_INSTALL_FLOW='$INSTALL_FLOW_RAW' (expected free or pro)."
      ;;
  esac
}

resolve_auto_channel() {
  if [[ "$INSTALL_CHANNEL" != "auto" ]]; then
    return 0
  fi
  if [[ "$INSTALL_FLOW" == "pro" ]]; then
    INSTALL_CHANNEL="pro"
  else
    INSTALL_CHANNEL="core"
  fi
  log "Auto install channel resolved to '$INSTALL_CHANNEL' for flow '$INSTALL_FLOW'."
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
  local mode="${1:-fresh}"
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  local -a setup_args=(setup --quick)
  if [[ "$mode" == "replay" ]]; then
    setup_args+=(--replay)
    log "Replaying quick setup journey with saved configuration..."
  else
    log "Starting quick setup..."
  fi
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" "$PYTHON_BIN" -m maestro_solo.cli "${setup_args[@]}"
}

has_existing_setup() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  local status="no"
  status="$(
    MAESTRO_SOLO_HOME="$SOLO_HOME" "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

raw_home = str(os.environ.get("MAESTRO_SOLO_HOME", "")).strip()
solo_home = Path(raw_home).expanduser().resolve() if raw_home else (Path.home() / ".maestro-solo").resolve()
install_state = solo_home / "install.json"
openclaw_config = Path.home() / ".openclaw" / "openclaw.json"

def _load_json(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}

state = _load_json(install_state) if install_state.exists() else {}
if not bool(state.get("setup_completed")):
    print("no")
    raise SystemExit(0)

config = _load_json(openclaw_config) if openclaw_config.exists() else {}
env = config.get("env") if isinstance(config.get("env"), dict) else {}
agents = config.get("agents") if isinstance(config.get("agents"), dict) else {}
agent_list = agents.get("list") if isinstance(agents.get("list"), list) else []

gemini = env.get("GEMINI_API_KEY")
has_gemini = isinstance(gemini, str) and bool(gemini.strip())
has_personal_agent = any(
    isinstance(item, dict) and str(item.get("id", "")).strip() == "maestro-solo-personal"
    for item in agent_list
)

print("yes" if (has_gemini and has_personal_agent) else "no")
PY
  )"
  [[ "$status" == "yes" ]]
}

run_preflight_checks() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  log "Running preflight checks (doctor --fix)..."
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" \
    "$PYTHON_BIN" -m maestro_solo.cli doctor --fix --no-restart
}

run_setup_or_preflight() {
  if has_existing_setup; then
    log "Existing Maestro setup detected. Replaying guided setup checks."
    if run_quick_setup replay; then
      log "Setup replay passed."
      return 0
    fi
    warn "Setup replay failed. Falling back to preflight checks."
    if run_preflight_checks; then
      log "Preflight checks passed."
      return 0
    fi
    fatal "Setup replay and preflight checks both failed. Run 'maestro-solo setup --quick' to repair."
  fi
  run_quick_setup fresh
}

run_pro_auth() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  if [[ "$INSTALL_FLOW" != "pro" ]]; then
    log "Free flow selected. Billing auth check is skipped."
    return 0
  fi

  local billing_url="${MAESTRO_BILLING_URL:-}"
  local -a auth_args=()
  if [[ -n "$billing_url" ]]; then
    auth_args+=(--billing-url "$billing_url")
  fi

  log "Checking billing auth session..."
  if MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" \
    "$PYTHON_BIN" -m maestro_solo.cli auth status "${auth_args[@]}"; then
    log "Billing auth already active."
    return 0
  fi

  log "No active billing auth session. Starting Google sign-in..."
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" \
    "$PYTHON_BIN" -m maestro_solo.cli auth login "${auth_args[@]}" \
    || fatal "Authentication failed. Re-run installer or run 'maestro-solo auth login' manually."
}

should_skip_pro_purchase() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  if is_truthy "$FORCE_PRO_PURCHASE"; then
    return 1
  fi

  local entitlement_check=""
  entitlement_check="$(
    MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" "$PYTHON_BIN" - <<'PY'
from maestro_solo.entitlements import normalize_tier, resolve_effective_entitlement

state = resolve_effective_entitlement()
tier = normalize_tier(str(state.get("tier", "core")))
source = str(state.get("source", "")).strip()
expires_at = str(state.get("expires_at", "")).strip()
stale = bool(state.get("stale"))

if tier == "pro" and not stale:
    print(f"yes|{source}|{expires_at}")
else:
    print(f"no|{source}|{expires_at}")
PY
  )"

  if [[ "$entitlement_check" == yes\|* ]]; then
    local details
    details="${entitlement_check#yes|}"
    local source="${details%%|*}"
    local expires_at="${details#*|}"
    if [[ -n "$expires_at" ]]; then
      log "Active Pro entitlement detected (source=$source expires_at=$expires_at). Skipping purchase."
    else
      log "Active Pro entitlement detected (source=$source). Skipping purchase."
    fi
    PRO_PURCHASE_SKIPPED="1"
    return 0
  fi
  return 1
}

run_pro_purchase() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  if [[ "$INSTALL_FLOW" != "pro" ]]; then
    log "Free flow selected. Purchase stage is skipped."
    return 0
  fi

  log "Checking entitlement status before purchase..."
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" \
    "$PYTHON_BIN" -m maestro_solo.cli entitlements status || true

  if should_skip_pro_purchase; then
    log "Purchase stage complete: active Pro entitlement already exists."
    return 0
  fi

  local billing_url="${MAESTRO_BILLING_URL:-}"
  local -a purchase_args=()
  if [[ -n "$billing_url" ]]; then
    purchase_args+=(--billing-url "$billing_url")
  fi

  log "Pro flow selected: purchase is required before launch."
  prompt_email
  log "Starting secure checkout for $PURCHASE_EMAIL"
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" \
    "$PYTHON_BIN" -m maestro_solo.cli purchase \
      --email "$PURCHASE_EMAIL" \
      --plan "$PRO_PLAN_ID" \
      --mode live \
      "${purchase_args[@]}" \
    || fatal "Pro purchase failed. Re-run installer or run 'maestro-solo purchase --email $PURCHASE_EMAIL' manually."
}

start_runtime() {
  [[ -n "$PYTHON_BIN" ]] || fatal "Internal error: virtualenv python is not configured"
  if [[ "$INSTALL_FLOW" == "pro" ]]; then
    if [[ "$PRO_PURCHASE_SKIPPED" == "1" ]]; then
      log "Pro already active. Starting Maestro Pro runtime..."
    else
      log "Purchase complete. Starting Maestro Pro runtime..."
    fi
  else
    log "Starting Maestro Free runtime..."
  fi
  MAESTRO_INSTALL_CHANNEL="$INSTALL_CHANNEL" MAESTRO_SOLO_HOME="$SOLO_HOME" exec "$PYTHON_BIN" -m maestro_solo.cli up --tui
}

main() {
  normalize_channel
  normalize_flow
  resolve_auto_channel
  stage "Setup"
  ensure_macos
  ensure_homebrew
  ensure_python
  ensure_node_npm
  ensure_openclaw
  ensure_virtualenv
  install_maestro_packages
  persist_install_channel
  run_setup_or_preflight
  stage "Auth"
  run_pro_auth
  stage "Purchase"
  run_pro_purchase
  stage "Up"
  start_runtime
}

main "$@"
