# Fleet Release + Launcher Runbook

This runbook covers how to publish Fleet artifacts and keep the `/fleet` installer launcher working in production.

## Purpose

- Publish Fleet wheels for customer installs.
- Pin installer scripts and wheel URLs in Railway billing vars.
- Verify `GET /fleet` returns a valid one-liner script.

## Prerequisites

- `gh` authenticated to `github.com`.
- `railway` CLI access through `npx @railway/cli`.
- Railway project/service access to `maestro-solo-services` / `maestro-billing-service`.
- Fleet installer scripts available in the target git ref:
  - `scripts/install-maestro-fleet.sh`
  - `scripts/install-maestro-fleet-linux.sh`
  - `scripts/install-maestro-fleet-macos.sh`

## Standard Release Flow

Run from repo root:

```bash
bash scripts/release-maestro-fleet.sh <version>
```

Example:

```bash
bash scripts/release-maestro-fleet.sh 0.1.0
```

What the script does:

1. Validates Fleet version markers in source.
2. Builds Fleet wheels (`maestro_conagent_teams`, `maestro_fleet`).
3. Publishes/updates GitHub release tag `fleet-v<version>`.
4. Updates Railway vars:
   - `MAESTRO_INSTALLER_SCRIPT_BASE_URL`
   - `MAESTRO_INSTALLER_FLEET_PACKAGE_SPEC`
5. Waits for Railway deployment success.
6. Smoke-checks `https://<billing-domain>/fleet`.

## Environment Overrides

- `REPO_SLUG`
- `RAILWAY_SERVICE`
- `RAILWAY_ENV`
- `BILLING_URL`
- `POLL_ATTEMPTS`
- `POLL_INTERVAL_SECONDS`

## Production Verification

```bash
bash scripts/verify-prod-installers.sh \
  --billing-url https://maestro-billing-service-production.up.railway.app \
  --check-fleet
```

Expected:

- `/install`, `/free`, `/pro`, and `/fleet` checks pass.
- `/fleet` includes:
  - `MAESTRO_FLEET_PACKAGE_SPEC`
  - `MAESTRO_INSTALL_BASE_URL`
  - `install-maestro-fleet-linux.sh`

## Promote Branch URLs to Main URLs

If `/fleet` was temporarily pointed at a branch ref, repoint to main with:

```bash
npx @railway/cli variable set \
  -s maestro-billing-service \
  -e production \
  MAESTRO_INSTALLER_FLEET_BASE_SCRIPT_URL="https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts/install-maestro-fleet.sh" \
  MAESTRO_INSTALLER_FLEET_SCRIPT_URL="https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts/install-maestro-fleet-linux.sh"
```

Then re-verify:

```bash
curl -fsSL https://maestro-billing-service-production.up.railway.app/fleet
```

## Customer Command

```bash
curl -fsSL https://maestro-billing-service-production.up.railway.app/fleet | bash
```
