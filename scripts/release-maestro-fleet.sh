#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_SLUG="${REPO_SLUG:-seanschneidewent/maestro-openclaw-agent-teams}"
RAILWAY_SERVICE="${RAILWAY_SERVICE:-maestro-billing-service}"
RAILWAY_ENV="${RAILWAY_ENV:-production}"
BILLING_URL="${BILLING_URL:-https://maestro-billing-service-production.up.railway.app}"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-80}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-3}"

usage() {
  cat <<'EOF'
Usage:
  scripts/release-maestro-fleet.sh <version>

Example:
  scripts/release-maestro-fleet.sh 0.1.0

Environment overrides:
  REPO_SLUG       (default: seanschneidewent/maestro-openclaw-agent-teams)
  RAILWAY_SERVICE (default: maestro-billing-service)
  RAILWAY_ENV     (default: production)
  BILLING_URL     (default: https://maestro-billing-service-production.up.railway.app)
  POLL_ATTEMPTS   (default: 80)
  POLL_INTERVAL_SECONDS (default: 3)
EOF
}

fail() {
  echo "[fleet-release] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "missing command '$cmd'"
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local label="$3"
  echo "$haystack" | grep -F "$needle" >/dev/null || fail "$label missing: $needle"
}

assert_file_exists() {
  local path="$1"
  [[ -f "$path" ]] || fail "missing $path"
}

wait_for_railway_success() {
  local deploy_line=""
  local done=0
  for _ in $(seq 1 "$POLL_ATTEMPTS"); do
    deploy_line="$(npx @railway/cli deployment list -s "$RAILWAY_SERVICE" -e "$RAILWAY_ENV" | sed -n '2p')"
    echo "[fleet-release] $deploy_line"
    if echo "$deploy_line" | grep -q "SUCCESS"; then
      done=1
      break
    fi
    sleep "$POLL_INTERVAL_SECONDS"
  done
  [[ "$done" == "1" ]] || fail "deployment did not reach SUCCESS in time"
}

assert_version_synced() {
  local version="$1"
  grep -q "version = \"$version\"" "$ROOT_DIR/pyproject.toml" || {
    fail "root pyproject version is not $version"
  }
  grep -q "__version__ = \"$version\"" "$ROOT_DIR/maestro/__init__.py" || {
    fail "maestro/__init__.py version is not $version"
  }
  grep -q "version = \"$version\"" "$ROOT_DIR/packages/maestro-fleet/pyproject.toml" || {
    fail "maestro-fleet pyproject version is not $version"
  }
  grep -q "__version__ = \"$version\"" "$ROOT_DIR/packages/maestro-fleet/src/maestro_fleet/__init__.py" || {
    fail "maestro_fleet/__init__.py version is not $version"
  }
  grep -q "version = \"$version\"" "$ROOT_DIR/packages/maestro-engine/pyproject.toml" || {
    fail "maestro-engine pyproject version is not $version"
  }
  grep -q "__version__ = \"$version\"" "$ROOT_DIR/packages/maestro-engine/src/maestro_engine/__init__.py" || {
    fail "maestro_engine/__init__.py version is not $version"
  }
}

wheel_basename_for() {
  basename "$1"
}

main() {
  local raw_version="${1:-}"
  if [[ -z "$raw_version" ]]; then
    usage
    exit 1
  fi

  local version="${raw_version#v}"
  local tag="fleet-v$version"
  local script_commit
  script_commit="$(git -C "$ROOT_DIR" rev-parse HEAD)"

  require_cmd git
  require_cmd gh
  require_cmd npx
  require_cmd curl

  assert_version_synced "$version"

  echo "[fleet-release] Building fleet wheels for $tag"
  MAESTRO_FLEET_BUILD_FRONTENDS=always \
    bash "$ROOT_DIR/scripts/build-maestro-fleet-package.sh" "$ROOT_DIR/dist/fleet-release"

  local wheel_dir="$ROOT_DIR/dist/fleet-release/wheels"
  local engine_wheel_path="$wheel_dir/maestro_engine-${version}-py3-none-any.whl"
  local root_wheel_path="$wheel_dir/maestro_conagent_teams-${version}-py3-none-any.whl"
  local fleet_wheel_path="$wheel_dir/maestro_fleet-${version}-py3-none-any.whl"

  assert_file_exists "$engine_wheel_path"
  assert_file_exists "$root_wheel_path"
  assert_file_exists "$fleet_wheel_path"

  local engine_wheel root_wheel fleet_wheel
  engine_wheel="$(wheel_basename_for "$engine_wheel_path")"
  root_wheel="$(wheel_basename_for "$root_wheel_path")"
  fleet_wheel="$(wheel_basename_for "$fleet_wheel_path")"

  echo "[fleet-release] Publishing GitHub release $tag"
  if gh release view "$tag" --repo "$REPO_SLUG" >/dev/null 2>&1; then
    gh release upload "$tag" "$engine_wheel_path" "$root_wheel_path" "$fleet_wheel_path" --clobber --repo "$REPO_SLUG"
  else
    gh release create "$tag" "$engine_wheel_path" "$root_wheel_path" "$fleet_wheel_path" --repo "$REPO_SLUG" --title "$tag" --notes "Automated Fleet release for $tag"
  fi

  local engine_wheel_url="https://github.com/$REPO_SLUG/releases/download/$tag/$engine_wheel"
  local root_wheel_url="https://github.com/$REPO_SLUG/releases/download/$tag/$root_wheel"
  local fleet_wheel_url="https://github.com/$REPO_SLUG/releases/download/$tag/$fleet_wheel"
  local package_spec="$engine_wheel_url $root_wheel_url $fleet_wheel_url"
  local script_base_url="https://raw.githubusercontent.com/$REPO_SLUG/$script_commit/scripts"
  local installer_url_macos="$script_base_url/install-maestro-fleet-macos.sh"
  local installer_url_linux="$script_base_url/install-maestro-fleet-linux.sh"
  local base_install_url="$script_base_url/install-maestro-fleet.sh"

  local payload
  payload="$(curl -fsSL "$installer_url_macos")"
  assert_contains "$payload" "install-maestro-fleet.sh" "macOS installer payload"
  payload="$(curl -fsSL "$installer_url_linux")"
  assert_contains "$payload" "install-maestro-fleet.sh" "linux installer payload"

  echo "[fleet-release] Updating Railway installer vars"
  npx @railway/cli variable set \
    -s "$RAILWAY_SERVICE" \
    -e "$RAILWAY_ENV" \
    MAESTRO_INSTALLER_SCRIPT_BASE_URL="$script_base_url" \
    MAESTRO_INSTALLER_FLEET_PACKAGE_SPEC="$package_spec"

  echo "[fleet-release] Waiting for Railway deployment success"
  wait_for_railway_success

  echo "[fleet-release] Running /fleet launcher smoke check"
  local fleet_script
  fleet_script="$(curl -fsSL "$BILLING_URL/fleet")"
  assert_contains "$fleet_script" "$engine_wheel_url" "/fleet script"
  assert_contains "$fleet_script" "$root_wheel_url" "/fleet script"
  assert_contains "$fleet_script" "$fleet_wheel_url" "/fleet script"
  assert_contains "$fleet_script" "install-maestro-fleet.sh" "/fleet script"
  assert_contains "$fleet_script" "install-maestro-fleet-linux.sh" "/fleet script"
  assert_contains "$fleet_script" "MAESTRO_FLEET_PACKAGE_SPEC='" "/fleet script"

  echo "[fleet-release] DONE"
  echo "[fleet-release] Engine wheel: $engine_wheel_url"
  echo "[fleet-release] Root wheel:  $root_wheel_url"
  echo "[fleet-release] Fleet wheel: $fleet_wheel_url"
  echo
  echo "[fleet-release] Fleet launcher endpoint:"
  echo "curl -fsSL $BILLING_URL/fleet | bash"
  echo
  echo "[fleet-release] Remote install one-liner (Linux over SSH):"
  echo "MAESTRO_FLEET_PACKAGE_SPEC=\"$package_spec\" \\"
  echo "MAESTRO_INSTALL_BASE_URL=\"$base_install_url\" \\"
  echo "curl -fsSL \"$installer_url_linux\" | bash"
  echo
  echo "[fleet-release] Remote install one-liner (macOS):"
  echo "MAESTRO_FLEET_PACKAGE_SPEC=\"$package_spec\" \\"
  echo "MAESTRO_INSTALL_BASE_URL=\"$base_install_url\" \\"
  echo "curl -fsSL \"$installer_url_macos\" | bash"
}

main "$@"
