#!/usr/bin/env bash
set -euo pipefail

BASE_INSTALL_URL="${MAESTRO_INSTALL_BASE_URL:-https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts/install-maestro-fleet.sh}"

curl -fsSL "$BASE_INSTALL_URL" | \
  MAESTRO_INSTALL_AUTO="${MAESTRO_INSTALL_AUTO:-1}" \
  MAESTRO_FLEET_REQUIRE_TAILSCALE="${MAESTRO_FLEET_REQUIRE_TAILSCALE:-1}" \
  MAESTRO_FLEET_DEPLOY="${MAESTRO_FLEET_DEPLOY:-1}" \
  bash -s -- "$@"
