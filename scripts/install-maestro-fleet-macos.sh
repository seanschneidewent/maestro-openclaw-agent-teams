#!/usr/bin/env bash
set -euo pipefail

BASE_INSTALL_URL="${MAESTRO_INSTALL_BASE_URL:-https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts/install-maestro-fleet.sh}"
TMP_SCRIPT=""

cleanup() {
  if [[ -n "$TMP_SCRIPT" && -f "$TMP_SCRIPT" ]]; then
    rm -f "$TMP_SCRIPT"
  fi
}

maybe_attach_tty() {
  if [[ -t 0 ]]; then
    return 0
  fi
  if [[ -r /dev/tty ]]; then
    if { exec </dev/tty; } 2>/dev/null; then
      return 0
    fi
  fi
  return 0
}

TMP_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/maestro-fleet-install.XXXXXX.sh")"
trap cleanup EXIT
curl -fsSL "$BASE_INSTALL_URL" -o "$TMP_SCRIPT"
maybe_attach_tty

MAESTRO_INSTALL_AUTO="${MAESTRO_INSTALL_AUTO:-1}" \
  MAESTRO_FLEET_REQUIRE_TAILSCALE="${MAESTRO_FLEET_REQUIRE_TAILSCALE:-1}" \
  MAESTRO_FLEET_DEPLOY="${MAESTRO_FLEET_DEPLOY:-1}" \
  bash "$TMP_SCRIPT" "$@"
