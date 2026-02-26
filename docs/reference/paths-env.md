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
- `MAESTRO_PURCHASE_EMAIL` (optional installer email preset for Pro flow)
- `MAESTRO_PRO_PLAN_ID` (optional installer plan override, default `solo_monthly`)
- `MAESTRO_TIER` (runtime gate; `pro` enables workspace routes)
- `MAESTRO_ALLOW_PRO_ON_CORE_CHANNEL` (default `1`, allows paid Pro upgrade even on core distribution channel)
- `MAESTRO_BILLING_URL`
- `MAESTRO_LICENSE_URL`
- `MAESTRO_INTERNAL_TOKEN` (service-to-service auth for local billing/license test flow)
- `MAESTRO_DATABASE_URL` (shared persistent state DB for billing/license services)
- `MAESTRO_STRIPE_BILLING_PORTAL_RETURN_URL` (optional Stripe Customer Portal return URL)
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

## Store Resolution Order

1. CLI `--store`
2. Solo install-state `store_root`
3. workspace `.env` `MAESTRO_STORE`
4. process env `MAESTRO_STORE`
5. fallback workspace `knowledge_store`
