#!/usr/bin/env bash
set -euo pipefail

BILLING_URL_DEFAULT="https://maestro-billing-service-production.up.railway.app"

usage() {
  cat <<'EOF'
Verify production installer launcher endpoints.

Usage:
  scripts/verify-prod-installers.sh [--billing-url URL] [--expect-version X.Y.Z]

Checks:
  - /install, /free, /pro endpoints are reachable
  - MAESTRO_INSTALL_AUTO is enabled
  - MAESTRO_OPENCLAW_PROFILE is maestro-solo
  - /free intent=free; /install and /pro intent=pro
  - Optional release version pin check against wheel URLs
EOF
}

fail() {
  echo "[verify-installers] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

fetch_script() {
  local url="$1"
  curl -fsSL "$url"
}

extract_var() {
  local var_name="$1"
  local script="$2"
  echo "$script" | sed -n "s/^export ${var_name}='\\(.*\\)'$/\\1/p" | head -n1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local label="$3"
  if ! echo "$haystack" | grep -F "$needle" >/dev/null 2>&1; then
    fail "$label missing: $needle"
  fi
}

main() {
  require_cmd curl
  require_cmd grep
  require_cmd sed

  local billing_url="$BILLING_URL_DEFAULT"
  local expect_version=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --billing-url)
        billing_url="${2:-}"
        shift 2
        ;;
      --expect-version)
        expect_version="${2:-}"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
  done

  [[ -n "$billing_url" ]] || fail "--billing-url cannot be empty"

  local install_script
  local free_script
  local pro_script
  install_script="$(fetch_script "$billing_url/install")"
  free_script="$(fetch_script "$billing_url/free")"
  pro_script="$(fetch_script "$billing_url/pro")"

  echo "[verify-installers] fetched /install /free /pro from $billing_url"

  for name in install free pro; do
    local payload=""
    case "$name" in
      install) payload="$install_script" ;;
      free) payload="$free_script" ;;
      pro) payload="$pro_script" ;;
    esac

    assert_contains "$payload" "export MAESTRO_INSTALL_AUTO='1'" "$name"
    assert_contains "$payload" "export MAESTRO_OPENCLAW_PROFILE='maestro-solo'" "$name"
    assert_contains "$payload" "install-maestro-install-macos.sh" "$name"

    local intent
    intent="$(extract_var "MAESTRO_INSTALL_INTENT" "$payload")"
    case "$name" in
      free)
        [[ "$intent" == "free" ]] || fail "/free intent expected 'free', got '$intent'"
        ;;
      install|pro)
        [[ "$intent" == "pro" ]] || fail "/$name intent expected 'pro', got '$intent'"
        ;;
    esac

    local flow
    flow="$(extract_var "MAESTRO_INSTALL_FLOW" "$payload")"
    [[ "$flow" == "install" ]] || fail "/$name flow expected 'install', got '$flow'"
  done

  if [[ -n "$expect_version" ]]; then
    local tag="v${expect_version#v}"
    local expected_marker="/releases/download/$tag/"
    assert_contains "$install_script" "$expected_marker" "install"
    assert_contains "$free_script" "$expected_marker" "free"
    assert_contains "$pro_script" "$expected_marker" "pro"
    echo "[verify-installers] release marker check passed for $tag"
  fi

  local install_sha free_sha pro_sha
  install_sha="$(echo "$install_script" | shasum -a 256 | awk '{print $1}')"
  free_sha="$(echo "$free_script" | shasum -a 256 | awk '{print $1}')"
  pro_sha="$(echo "$pro_script" | shasum -a 256 | awk '{print $1}')"

  echo "[verify-installers] /install sha256: $install_sha"
  echo "[verify-installers] /free    sha256: $free_sha"
  echo "[verify-installers] /pro     sha256: $pro_sha"
  echo "[verify-installers] PASS"
}

main "$@"
