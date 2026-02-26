#!/usr/bin/env bash
set -euo pipefail

BASE_INSTALL_URL="${MAESTRO_INSTALL_BASE_URL:-https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/main/scripts/install-maestro-macos.sh}"

curl -fsSL "$BASE_INSTALL_URL" | MAESTRO_INSTALL_FLOW=pro MAESTRO_INSTALL_CHANNEL="${MAESTRO_INSTALL_CHANNEL:-auto}" bash
