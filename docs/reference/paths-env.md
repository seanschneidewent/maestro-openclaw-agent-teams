# Paths and Environment

## Key Paths

- OpenClaw config: `~/.openclaw/openclaw.json`
- Commander workspace: `~/.openclaw/workspace-maestro`
- Fleet store root: `<workspace>/knowledge_store` (or install-state override)
- Fleet registry: `<store_root>/.command_center/fleet_registry.json`

## Important Environment Variables

- `MAESTRO_STORE`
- `MAESTRO_AGENT_ROLE` (`company` or `project`)
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

## Store Resolution Order

1. CLI `--store`
2. install-state fleet store root
3. workspace `.env` `MAESTRO_STORE`
4. process env `MAESTRO_STORE`
5. fallback to workspace knowledge store
