#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT_DEFAULT="$HOME/.maestro"
FLEET_HOME_DEFAULT="$HOME/.maestro-fleet"
VENV_DIR_DEFAULT="$INSTALL_ROOT_DEFAULT/venv-maestro-fleet"
AUTO_APPROVE_DEFAULT="auto"
AUTO_TUI_DEFAULT="auto"

FLEET_HOME="${MAESTRO_FLEET_HOME:-$FLEET_HOME_DEFAULT}"
VENV_DIR="${MAESTRO_VENV_DIR:-$VENV_DIR_DEFAULT}"
PACKAGE_SPEC="${MAESTRO_FLEET_PACKAGE_SPEC:-}"
USE_LOCAL_REPO="${MAESTRO_USE_LOCAL_REPO:-0}"
AUTO_APPROVE_RAW="${MAESTRO_INSTALL_AUTO:-$AUTO_APPROVE_DEFAULT}"
REQUIRE_TAILSCALE_RAW="${MAESTRO_FLEET_REQUIRE_TAILSCALE:-0}"
AUTO_DEPLOY_RAW="${MAESTRO_FLEET_DEPLOY:-1}"
AUTO_TUI_RAW="${MAESTRO_FLEET_AUTO_TUI:-$AUTO_TUI_DEFAULT}"
OPENCLAW_PROFILE_RAW="${MAESTRO_OPENCLAW_PROFILE:-maestro-fleet}"
PYTHON_BIN=""
PYTHON_HOST_BIN=""
AUTO_APPROVE="0"
REQUIRE_TAILSCALE="0"
AUTO_DEPLOY="1"
AUTO_TUI="0"

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

resolve_desktop_dir() {
  local override="${MAESTRO_DESKTOP_DIR:-}"
  if [[ -n "$override" ]]; then
    printf '%s' "$override"
    return 0
  fi

  if is_linux && command -v xdg-user-dir >/dev/null 2>&1; then
    local xdg_desktop=""
    xdg_desktop="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    if [[ -n "$xdg_desktop" ]]; then
      printf '%s' "$xdg_desktop"
      return 0
    fi
  fi

  printf '%s' "$HOME/Desktop"
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
  persist_path_entry "$HOME/.npm-global/bin"
}

hydrate_existing_toolchain_paths() {
  local candidate=""

  if ! command -v node >/dev/null 2>&1; then
    for candidate in "$HOME/.maestro/toolchain"/node-v*/bin/node; do
      [[ -x "$candidate" ]] || continue
      export PATH="$(dirname "$candidate"):$PATH"
      break
    done
  fi

  if ! command -v openclaw >/dev/null 2>&1 && [[ -x "$HOME/.npm-global/bin/openclaw" ]]; then
    export PATH="$HOME/.npm-global/bin:$PATH"
  fi

  if ! command -v tailscale >/dev/null 2>&1; then
    if [[ -x "/usr/local/bin/tailscale" ]]; then
      export PATH="/usr/local/bin:$PATH"
    elif [[ -x "/opt/homebrew/bin/tailscale" ]]; then
      export PATH="/opt/homebrew/bin:$PATH"
    fi
  fi
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

resolve_auto_tui() {
  local clean
  clean="$(printf '%s' "$AUTO_TUI_RAW" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$clean" in
    1|true|yes|on)
      AUTO_TUI="1"
      ;;
    0|false|no|off)
      AUTO_TUI="0"
      ;;
    auto|"")
      if [[ -t 0 && -t 1 ]]; then
        AUTO_TUI="1"
      else
        AUTO_TUI="0"
      fi
      ;;
    *)
      fatal "Invalid MAESTRO_FLEET_AUTO_TUI='$AUTO_TUI_RAW' (expected auto, true/false, or 1/0)."
      ;;
  esac
}

persist_path_entry() {
  local bin_dir="${1:-}"
  if [[ -z "$bin_dir" ]]; then
    return 0
  fi
  local line="export PATH=\"$bin_dir:\$PATH\""
  local rc_file=""
  local -a rc_files=("$HOME/.zprofile" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.profile")
  for rc_file in "${rc_files[@]}"; do
    mkdir -p "$(dirname "$rc_file")"
    touch "$rc_file"
    if ! grep -Fqs "$line" "$rc_file"; then
      printf '\n%s\n' "$line" >>"$rc_file"
    fi
  done
}

ensure_git_github_https() {
  command -v git >/dev/null 2>&1 || return 0
  local values
  values="$(git config --global --get-all url.\"https://github.com/\".insteadOf 2>/dev/null || true)"
  if ! grep -Fq "git@github.com:" <<<"$values"; then
    git config --global --add url."https://github.com/".insteadOf "git@github.com:" || true
  fi
  if ! grep -Fq "ssh://git@github.com/" <<<"$values"; then
    git config --global --add url."https://github.com/".insteadOf "ssh://git@github.com/" || true
  fi
}

python_bin_version_ok() {
  local candidate="${1:-}"
  [[ -n "$candidate" ]] || return 1
  if [[ "$candidate" == */* ]]; then
    [[ -x "$candidate" ]] || return 1
  else
    command -v "$candidate" >/dev/null 2>&1 || return 1
  fi
  local status
  status="$("$candidate" - <<'PY'
import sys
print("ok" if sys.version_info >= (3, 11) else "bad")
PY
)" || return 1
  [[ "$status" == "ok" ]]
}

select_python_bin() {
  local env_candidate="${MAESTRO_PYTHON_BIN:-}"
  local candidate=""
  local -a candidates=(
    "$env_candidate"
    "python3"
    "/usr/local/bin/python3"
    "/opt/homebrew/bin/python3"
    "python3.12"
    "python3.11"
    "/usr/local/bin/python3.12"
    "/usr/local/bin/python3.11"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
  )
  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    if python_bin_version_ok "$candidate"; then
      if [[ "$candidate" == */* ]]; then
        printf '%s' "$candidate"
      else
        command -v "$candidate"
      fi
      return 0
    fi
  done
  return 1
}

ensure_python() {
  refresh_path_for_brew
  local selected
  selected="$(select_python_bin || true)"
  if [[ -z "$selected" ]]; then
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
    refresh_path_for_brew
    selected="$(select_python_bin || true)"
  fi

  [[ -n "$selected" ]] || fatal "Python 3.11+ is still unavailable after install attempt."
  PYTHON_HOST_BIN="$selected"
  log "Python: $("$PYTHON_HOST_BIN" --version 2>&1)"
}

install_node_tarball_macos() {
  local node_version="${MAESTRO_NODE_VERSION:-v24.12.0}"
  local arch_raw
  arch_raw="$(uname -m)"
  local arch=""
  case "$arch_raw" in
    arm64|aarch64) arch="arm64" ;;
    x86_64) arch="x64" ;;
    *) return 1 ;;
  esac

  local tool_root="$HOME/.maestro/toolchain"
  local node_dir="$tool_root/node-${node_version}-darwin-${arch}"
  local node_bin="$node_dir/bin"
  if [[ ! -x "$node_bin/node" || ! -x "$node_bin/npm" ]]; then
    local tgz="node-${node_version}-darwin-${arch}.tar.gz"
    local url="https://nodejs.org/dist/${node_version}/${tgz}"
    local tmp_tgz
    tmp_tgz="$(mktemp "${TMPDIR:-/tmp}/node-dist.XXXXXX.tgz")" || return 1
    if ! curl -fsSL "$url" -o "$tmp_tgz"; then
      rm -f "$tmp_tgz"
      return 1
    fi
    mkdir -p "$tool_root"
    rm -rf "$node_dir"
    if ! env LC_ALL=C LANG=C tar -xzf "$tmp_tgz" -C "$tool_root"; then
      rm -f "$tmp_tgz"
      return 1
    fi
    rm -f "$tmp_tgz"
  fi
  [[ -x "$node_bin/node" && -x "$node_bin/npm" ]] || return 1
  export PATH="$node_bin:$PATH"
  persist_path_entry "$node_bin"
  log "Node toolchain: $node_dir"
  return 0
}

install_tailscale_pkg_macos() {
  local pkg_url="${MAESTRO_TAILSCALE_PKG_URL:-https://pkgs.tailscale.com/stable/Tailscale-latest-macos.pkg}"
  local tmp_pkg
  tmp_pkg="$(mktemp "${TMPDIR:-/tmp}/tailscale.XXXXXX.pkg")" || return 1
  if ! curl -fsSL "$pkg_url" -o "$tmp_pkg"; then
    rm -f "$tmp_pkg"
    return 1
  fi
  if ! run_privileged installer -pkg "$tmp_pkg" -target /; then
    rm -f "$tmp_pkg"
    return 1
  fi
  rm -f "$tmp_pkg"
  open -a Tailscale >/dev/null 2>&1 || true
  return 0
}

ensure_node_npm() {
  refresh_path_for_brew
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    warn "Node.js/npm are required."
    if ! prompt_yes_no "Install Node.js and npm now?" "y"; then
      fatal "Node.js and npm are required."
    fi

    if is_macos; then
      if ! install_node_tarball_macos; then
        warn "Node tarball install failed; falling back to Homebrew."
        ensure_homebrew
        brew install node
      fi
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

tailscale_ipv4() {
  local python_cmd="${PYTHON_HOST_BIN:-python3}"
  if [[ "$python_cmd" != */* ]] && ! command -v "$python_cmd" >/dev/null 2>&1; then
    python_cmd="python3"
  fi
  "$python_cmd" - <<'PY' 2>/dev/null
import subprocess

try:
    result = subprocess.run(
        ["tailscale", "ip", "-4"],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
except Exception:
    raise SystemExit(0)

lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
if lines:
    print(lines[0])
PY
}

ensure_openclaw() {
  if ! command -v openclaw >/dev/null 2>&1; then
    warn "OpenClaw CLI is required."
    if ! prompt_yes_no "Install OpenClaw now (npm install -g openclaw)?" "y"; then
      fatal "OpenClaw CLI is required."
    fi
    ensure_git_github_https
    install_npm_global_user
    log "Installing OpenClaw (this can take several minutes on fresh machines)..."
    if ! npm install -g openclaw --no-audit --no-fund; then
      warn "OpenClaw install failed on first attempt; retrying with IPv4-first DNS."
      local retry_node_options="--dns-result-order=ipv4first"
      if [[ -n "${NODE_OPTIONS:-}" ]]; then
        retry_node_options="$retry_node_options ${NODE_OPTIONS}"
      fi
      if ! NODE_OPTIONS="$retry_node_options" npm install -g openclaw --no-audit --no-fund; then
        fatal "OpenClaw install failed."
      fi
    fi
    hash -r
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
    ip="$(tailscale_ipv4 || true)"
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
      if [[ "$AUTO_APPROVE" == "1" ]]; then
        fatal "Tailscale is missing. Install the Tailscale app from https://tailscale.com/download/mac and rerun."
      fi
      install_tailscale_pkg_macos || fatal "Tailscale install failed."
    elif is_linux; then
      run_privileged sh -c "curl -fsSL https://tailscale.com/install.sh | sh"
    else
      fatal "Unsupported platform for automatic Tailscale install: $(uname -s)"
    fi
  fi

  command -v tailscale >/dev/null 2>&1 || fatal "Tailscale install failed."

  local ip
  ip="$(tailscale_ipv4 || true)"
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
    if ! "$PYTHON_HOST_BIN" -m venv "$VENV_DIR"; then
      if is_linux; then
        warn "python3-venv appears missing; attempting install."
        ensure_apt
        run_privileged apt-get install -y python3-venv
        "$PYTHON_HOST_BIN" -m venv "$VENV_DIR" || fatal "Failed to create virtualenv after installing python3-venv."
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

install_customer_help_folder() {
  local desktop_dir=""
  local help_dir=""

  desktop_dir="$(resolve_desktop_dir)"
  if [[ -z "$desktop_dir" ]]; then
    warn "Could not resolve desktop directory; skipping customer help folder install."
    return 0
  fi

  if ! mkdir -p "$desktop_dir"; then
    warn "Could not create desktop directory at $desktop_dir; skipping customer help folder install."
    return 0
  fi

  help_dir="$desktop_dir/Maestro Fleet Help"
  if ! "$PYTHON_BIN" -m maestro.help_pack install-fleet --target-dir "$help_dir" >/dev/null; then
    warn "Failed to install customer help folder at $help_dir"
    return 0
  fi

  log "Installed customer help folder: $help_dir"
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
  if ! "${cmd[@]}"; then
    return 1
  fi
  install_customer_help_folder
  if [[ "$AUTO_TUI" == "1" && "$arg_count" -eq 0 ]]; then
    log "Starting Fleet runtime TUI."
    exec "$VENV_DIR/bin/maestro-fleet" up --tui
  fi
  return 0
}

main() {
  export MAESTRO_OPENCLAW_PROFILE="${OPENCLAW_PROFILE_RAW}"
  resolve_flag "$AUTO_APPROVE_RAW" AUTO_APPROVE 0
  resolve_flag "$REQUIRE_TAILSCALE_RAW" REQUIRE_TAILSCALE 0
  resolve_flag "$AUTO_DEPLOY_RAW" AUTO_DEPLOY 1
  resolve_auto_tui
  hydrate_existing_toolchain_paths

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
