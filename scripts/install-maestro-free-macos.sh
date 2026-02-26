#!/usr/bin/env bash
set -euo pipefail

BASE_INSTALL_URL="${MAESTRO_INSTALL_BASE_URL:-https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts/install-maestro-macos.sh}"

curl -fsSL "$BASE_INSTALL_URL" | \
  MAESTRO_INSTALL_AUTO="${MAESTRO_INSTALL_AUTO:-1}" \
  MAESTRO_INSTALL_FLOW=free \
  MAESTRO_INSTALL_INTENT=free \
  MAESTRO_INSTALL_CHANNEL="${MAESTRO_INSTALL_CHANNEL:-core}" \
  MAESTRO_OPENCLAW_PROFILE="${MAESTRO_OPENCLAW_PROFILE:-maestro-solo}" \
  bash
