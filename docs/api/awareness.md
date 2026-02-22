# Awareness API

`GET /api/system/awareness`

## Key Sections

1. `posture`, `degraded_reasons`
2. `network` (`localhost_url`, `tailnet_url`, `recommended_url`)
3. `paths` (`store_root`, `registry_path`, `workspace_root`)
4. `services` (tailscale/openclaw/telegram/company_agent)
5. `commander` (`display_name`, `agent_id`, `chat_transport`)
6. `fleet` (project count, stale projects, registry, directives summary)
7. `available_actions`

## Conversation Capability Flags

`available_actions` includes:

- `conversation_read`
- `conversation_send`

Use these flags in UI to gate interaction affordances.
