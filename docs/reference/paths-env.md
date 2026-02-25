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

- Solo workspace: `/workspace`
- Solo WebSocket: `/workspace/ws`
- Fleet command center: `/command-center` (only when Fleet enabled)

## Important Environment Variables

- `MAESTRO_STORE`
- `MAESTRO_AGENT_ROLE` (`project` in Solo, `company` in Fleet commander workspace)
- `MAESTRO_SOLO_HOME`
- `MAESTRO_BILLING_URL`
- `MAESTRO_LICENSE_URL`
- `MAESTRO_INTERNAL_TOKEN` (service-to-service auth for local billing/license test flow)
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

## Store Resolution Order

1. CLI `--store`
2. Solo install-state `store_root`
3. workspace `.env` `MAESTRO_STORE`
4. process env `MAESTRO_STORE`
5. fallback workspace `knowledge_store`
