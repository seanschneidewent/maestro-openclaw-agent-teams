#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_SLUG="${REPO_SLUG:-seanschneidewent/maestro-openclaw-agent-teams}"
RAILWAY_SERVICE="${RAILWAY_SERVICE:-maestro-billing-service}"
RAILWAY_ENV="${RAILWAY_ENV:-production}"
BILLING_URL="${BILLING_URL:-https://maestro-billing-service-production.up.railway.app}"

usage() {
  cat <<'EOF'
Usage:
  scripts/release-maestro-solo.sh <version>

Example:
  scripts/release-maestro-solo.sh 0.1.3

Environment overrides:
  REPO_SLUG       (default: seanschneidewent/maestro-openclaw-agent-teams)
  RAILWAY_SERVICE (default: maestro-billing-service)
  RAILWAY_ENV     (default: production)
  BILLING_URL     (default: https://maestro-billing-service-production.up.railway.app)
EOF
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "[release] ERROR: missing command '$cmd'" >&2
    exit 1
  }
}

assert_version_synced() {
  local version="$1"
  grep -q "version = \"$version\"" "$ROOT_DIR/packages/maestro-engine/pyproject.toml" || {
    echo "[release] ERROR: maestro-engine pyproject version is not $version" >&2
    exit 1
  }
  grep -q "__version__ = \"$version\"" "$ROOT_DIR/packages/maestro-engine/src/maestro_engine/__init__.py" || {
    echo "[release] ERROR: maestro-engine __init__ version is not $version" >&2
    exit 1
  }
  grep -q "version = \"$version\"" "$ROOT_DIR/packages/maestro-solo/pyproject.toml" || {
    echo "[release] ERROR: maestro-solo pyproject version is not $version" >&2
    exit 1
  }
  grep -q "__version__ = \"$version\"" "$ROOT_DIR/packages/maestro-solo/src/maestro_solo/__init__.py" || {
    echo "[release] ERROR: maestro-solo __init__ version is not $version" >&2
    exit 1
  }
}

main() {
  local raw_version="${1:-}"
  if [[ -z "$raw_version" ]]; then
    usage
    exit 1
  fi

  local version="${raw_version#v}"
  local tag="v$version"
  local script_commit
  script_commit="$(git -C "$ROOT_DIR" rev-parse --short=7 HEAD)"

  require_cmd git
  require_cmd gh
  require_cmd npx
  require_cmd curl

  assert_version_synced "$version"

  echo "[release] Building wheels for $tag"
  bash "$ROOT_DIR/scripts/build-maestro-core-wheel.sh" "$ROOT_DIR/dist/core"

  local engine_wheel="maestro_engine-${version}-py3-none-any.whl"
  local solo_wheel="maestro_solo-${version}-py3-none-any.whl"
  local engine_path="$ROOT_DIR/dist/core/$engine_wheel"
  local solo_path="$ROOT_DIR/dist/core/$solo_wheel"
  [[ -f "$engine_path" ]] || { echo "[release] ERROR: missing $engine_path" >&2; exit 1; }
  [[ -f "$solo_path" ]] || { echo "[release] ERROR: missing $solo_path" >&2; exit 1; }

  echo "[release] Publishing GitHub release $tag"
  if gh release view "$tag" --repo "$REPO_SLUG" >/dev/null 2>&1; then
    gh release upload "$tag" "$engine_path" "$solo_path" --clobber --repo "$REPO_SLUG"
  else
    gh release create "$tag" "$engine_path" "$solo_path" --repo "$REPO_SLUG" --title "$tag" --notes "Automated release for $tag"
  fi

  local engine_url="https://github.com/$REPO_SLUG/releases/download/$tag/$engine_wheel"
  local solo_url="https://github.com/$REPO_SLUG/releases/download/$tag/$solo_wheel"
  local package_spec="$engine_url $solo_url"
  local script_base_url="https://raw.githubusercontent.com/$REPO_SLUG/$script_commit/scripts"

  echo "[release] Updating Railway installer vars"
  npx @railway/cli variable set \
    -s "$RAILWAY_SERVICE" \
    -e "$RAILWAY_ENV" \
    MAESTRO_INSTALLER_SCRIPT_BASE_URL="$script_base_url" \
    MAESTRO_INSTALLER_CORE_PACKAGE_SPEC="$package_spec" \
    MAESTRO_INSTALLER_PRO_PACKAGE_SPEC="$package_spec"

  echo "[release] Waiting for Railway deployment success"
  local deploy_line=""
  local done=0
  for _ in $(seq 1 80); do
    deploy_line="$(npx @railway/cli deployment list -s "$RAILWAY_SERVICE" -e "$RAILWAY_ENV" | sed -n '2p')"
    echo "[release] $deploy_line"
    if echo "$deploy_line" | grep -q "SUCCESS"; then
      done=1
      break
    fi
    sleep 3
  done
  [[ "$done" == "1" ]] || { echo "[release] ERROR: deployment did not reach SUCCESS in time" >&2; exit 1; }

  echo "[release] Running installer smoke checks"
  local free_script pro_script install_script
  free_script="$(curl -fsSL "$BILLING_URL/free")"
  pro_script="$(curl -fsSL "$BILLING_URL/pro")"
  install_script="$(curl -fsSL "$BILLING_URL/install")"

  echo "$free_script" | grep -F "$engine_url" >/dev/null || { echo "[release] ERROR: /free missing engine wheel URL" >&2; exit 1; }
  echo "$free_script" | grep -F "$solo_url" >/dev/null || { echo "[release] ERROR: /free missing solo wheel URL" >&2; exit 1; }
  echo "$free_script" | grep -F "$script_base_url/install-maestro-install-macos.sh" >/dev/null || {
    echo "[release] ERROR: /free missing pinned installer script URL" >&2
    exit 1
  }
  echo "$free_script" | grep -F "MAESTRO_INSTALL_INTENT='free'" >/dev/null || {
    echo "[release] ERROR: /free missing free intent export" >&2
    exit 1
  }

  echo "$pro_script" | grep -F "$engine_url" >/dev/null || { echo "[release] ERROR: /pro missing engine wheel URL" >&2; exit 1; }
  echo "$pro_script" | grep -F "$solo_url" >/dev/null || { echo "[release] ERROR: /pro missing solo wheel URL" >&2; exit 1; }
  echo "$pro_script" | grep -F "$script_base_url/install-maestro-install-macos.sh" >/dev/null || {
    echo "[release] ERROR: /pro missing pinned installer script URL" >&2
    exit 1
  }
  echo "$pro_script" | grep -F "MAESTRO_INSTALL_INTENT='pro'" >/dev/null || {
    echo "[release] ERROR: /pro missing pro intent export" >&2
    exit 1
  }

  echo "$install_script" | grep -F "$script_base_url/install-maestro-install-macos.sh" >/dev/null || {
    echo "[release] ERROR: /install missing pinned installer script URL" >&2
    exit 1
  }
  echo "$install_script" | grep -F "MAESTRO_INSTALL_INTENT='pro'" >/dev/null || {
    echo "[release] ERROR: /install missing default pro intent export" >&2
    exit 1
  }

  echo "[release] DONE"
  echo "[release] Free installer: curl -fsSL $BILLING_URL/free | bash"
  echo "[release] Pro installer:  curl -fsSL $BILLING_URL/pro | bash"
}

main "$@"
