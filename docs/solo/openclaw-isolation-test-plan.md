# OpenClaw Isolation Test Plan

Use this runbook to verify Maestro Solo installs never mutate shared `~/.openclaw` unless explicitly opted in.

## Preconditions

- OpenClaw already installed and configured in shared profile (`~/.openclaw/openclaw.json` exists).
- Run from a machine where you can safely install/uninstall Maestro Solo.

## 1) Baseline Snapshot

```bash
set -euo pipefail
mkdir -p ~/.openclaw/isolation-audit
cp ~/.openclaw/openclaw.json ~/.openclaw/isolation-audit/openclaw.json.before
shasum -a 256 ~/.openclaw/openclaw.json | tee ~/.openclaw/isolation-audit/shared.sha.before.txt
```

## 2) Local Dev Install Validation (repo checkout)

```bash
set -euo pipefail
cd /absolute/path/to/maestro-openclaw-agent-teams

MAESTRO_USE_LOCAL_REPO=1 \
MAESTRO_INSTALL_AUTO=1 \
MAESTRO_INSTALL_FLOW=free \
MAESTRO_INSTALL_CHANNEL=core \
MAESTRO_OPENCLAW_PROFILE=maestro-solo \
bash scripts/install-maestro-macos.sh
```

Validate shared config unchanged + isolated profile created:

```bash
shasum -a 256 ~/.openclaw/openclaw.json | tee ~/.openclaw/isolation-audit/shared.sha.after.local.txt
cmp ~/.openclaw/isolation-audit/openclaw.json.before ~/.openclaw/openclaw.json
test -f ~/.openclaw-maestro-solo/openclaw.json
```

## 3) Negative Test (blocked shared profile)

Installer should fail when targeting shared profile without explicit unsafe override:

```bash
set +e
MAESTRO_OPENCLAW_PROFILE=shared MAESTRO_INSTALL_AUTO=1 bash scripts/install-maestro-macos.sh
rc=$?
set -e
test "$rc" -ne 0
```

## 4) Explicit Unsafe Opt-in Test

Only for controlled verification:

```bash
MAESTRO_ALLOW_SHARED_OPENCLAW=1 \
MAESTRO_OPENCLAW_PROFILE=shared \
MAESTRO_INSTALL_AUTO=1 \
bash scripts/install-maestro-macos.sh
```

## 5) Production Endpoint Validation

Run both production one-liners and verify shared config checksum remains unchanged.
Use your live billing domain. If your vanity domain (`get.maestro.run`) is not configured yet, use Railway directly.

```bash
set -euo pipefail
cp ~/.openclaw/openclaw.json ~/.openclaw/isolation-audit/openclaw.json.before.prod
shasum -a 256 ~/.openclaw/openclaw.json | tee ~/.openclaw/isolation-audit/shared.sha.before.prod.txt

curl -fsSL https://maestro-billing-service-production.up.railway.app/free | bash
curl -fsSL https://maestro-billing-service-production.up.railway.app/pro | bash

shasum -a 256 ~/.openclaw/openclaw.json | tee ~/.openclaw/isolation-audit/shared.sha.after.prod.txt
cmp ~/.openclaw/isolation-audit/openclaw.json.before.prod ~/.openclaw/openclaw.json
test -f ~/.openclaw-maestro-solo/openclaw.json
```

## 6) Required Assertions

- Shared config hash is identical before/after (`cmp` exits 0).
- Isolated config exists at `~/.openclaw-maestro-solo/openclaw.json`.
- Active Maestro agent config/workspace lives under `~/.openclaw-maestro-solo`.
- Shared-profile install is blocked unless `MAESTRO_ALLOW_SHARED_OPENCLAW=1`.
