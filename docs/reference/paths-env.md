# Paths and Environment

## Install State

Path: `~/.maestro-solo/install.json`

Current schema:

```json
{
  "version": 1,
  "product": "maestro-solo",
  "workspace_root": "...",
  "store_root": "...",
  "active_project_slug": "",
  "active_project_name": "",
  "updated_at": "..."
}
```

Fleet transition state path: `~/.maestro/install.json`

## Key Paths

- OpenClaw config: `~/.openclaw/openclaw.json`
- Solo workspace root: usually `~/.openclaw/workspace-maestro-solo`
- Store root: `<workspace>/knowledge_store` unless overridden
- Fleet registry: `<store_root>/.command_center/fleet_registry.json`

## Frontend Artifact Paths

- Solo workspace UI build: `workspace_frontend/dist`
- Fleet command center UI build: `command_center_frontend/dist`
- Both paths are generated artifacts; `maestro update` rebuilds missing artifacts for the active profile.

## Canonical UI Routes

- Solo core runtime: `/` (text-only status + upgrade guidance)
- Solo workspace (Pro): `/workspace`
- Solo WebSocket (Pro): `/workspace/ws`
- Fleet command center: `/command-center` (only when Fleet enabled)

## Important Environment Variables

- `MAESTRO_STORE`
- `MAESTRO_AGENT_ROLE` (`project` in Solo, `company` in Fleet commander workspace)
- `MAESTRO_SOLO_HOME`
- `MAESTRO_INSTALL_FLOW` (`free` or `pro`, installer orchestration)
- `MAESTRO_INSTALL_CHANNEL` (`auto`, `core`, `pro`)
- `MAESTRO_SETUP_REPLAY` (`1` default; set `0` to disable setup replay in installer journey)
- `MAESTRO_PURCHASE_EMAIL` (optional installer email preset for Pro flow)
- `MAESTRO_PRO_PLAN_ID` (optional installer plan override, default `solo_monthly`)
- `MAESTRO_FORCE_PRO_PURCHASE` (set `1` to force checkout even when Pro entitlement is already active)
- `MAESTRO_TIER` (runtime gate; `pro` enables workspace routes)
- `MAESTRO_ALLOW_PRO_ON_CORE_CHANNEL` (default `1`, allows paid Pro upgrade even on core distribution channel)
- `MAESTRO_BILLING_URL`
- `MAESTRO_LICENSE_URL`
- `MAESTRO_INTERNAL_TOKEN` (service-to-service auth for local billing/license test flow)
- `MAESTRO_DATABASE_URL` (shared persistent state DB for billing/license services)
- `MAESTRO_BILLING_REQUIRE_AUTH` (default `1`, require user auth for billing endpoints)
- `MAESTRO_AUTH_JWT_SECRET` (required signing key for auth sessions)
- `MAESTRO_GOOGLE_CLIENT_ID`
- `MAESTRO_GOOGLE_CLIENT_SECRET`
- `MAESTRO_GOOGLE_REDIRECT_URI`
- `MAESTRO_AUTH_ALLOWED_DOMAINS` (optional domain allow-list)
- `MAESTRO_ENABLE_DEV_ENDPOINTS` (default `0`; keep disabled in production)
- `MAESTRO_STRIPE_BILLING_PORTAL_RETURN_URL` (optional Stripe Customer Portal return URL)
- `MAESTRO_INSTALLER_CORE_PACKAGE_SPEC` (billing launcher package spec for `/free`)
- `MAESTRO_INSTALLER_PRO_PACKAGE_SPEC` (billing launcher package spec for `/pro`)
- `MAESTRO_INSTALLER_SCRIPT_BASE_URL` (optional script source override for launcher endpoints)
- `MAESTRO_INSTALLER_FREE_SCRIPT_URL`
- `MAESTRO_INSTALLER_PRO_SCRIPT_URL`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

## Store Resolution Order

1. CLI `--store`
2. Solo install-state `store_root`
3. workspace `.env` `MAESTRO_STORE`
4. process env `MAESTRO_STORE`
5. fallback workspace `knowledge_store`
