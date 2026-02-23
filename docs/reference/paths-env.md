# Paths and Environment

## Install State

Path: `~/.maestro/install.json`

Current schema:

```json
{
  "version": 2,
  "profile": "solo|fleet",
  "fleet_enabled": false,
  "workspace_root": "...",
  "store_root": "...",
  "active_project_slug": "",
  "active_project_name": "",
  "updated_at": "..."
}
```

## Key Paths

- OpenClaw config: `~/.openclaw/openclaw.json`
- Solo/Fleet workspace root: usually `~/.openclaw/workspace-maestro`
- Store root: `<workspace>/knowledge_store` unless overridden
- Fleet registry: `<store_root>/.command_center/fleet_registry.json`

## Canonical UI Routes

- Solo workspace: `/workspace`
- Solo WebSocket: `/workspace/ws`
- Fleet command center: `/command-center` (only when Fleet enabled)

## Important Environment Variables

- `MAESTRO_STORE`
- `MAESTRO_AGENT_ROLE` (`project` in Solo, `company` in Fleet commander workspace)
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

## Store Resolution Order

1. CLI `--store`
2. install-state `store_root` (or legacy `fleet_store_root`)
3. workspace `.env` `MAESTRO_STORE`
4. process env `MAESTRO_STORE`
5. fallback workspace `knowledge_store`
