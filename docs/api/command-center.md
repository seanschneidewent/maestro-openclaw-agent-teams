# Command Center APIs

## State and Registry

1. `GET /api/command-center/state`
2. `GET /api/command-center/fleet-registry`
3. `GET /api/command-center/projects/{slug}` (compat detail endpoint)

## Node APIs

1. `GET /api/command-center/nodes/{slug}/status`
2. `GET /api/command-center/nodes/{slug}/conversation?limit=100&before=<id>`
3. `POST /api/command-center/nodes/{slug}/conversation/send`

Send body:

```json
{
  "message": "string",
  "source": "command_center_ui"
}
```

## Action API

`POST /api/command-center/actions`

Supported actions:

- `sync_registry`
- `list_system_directives`
- `upsert_system_directive`
- `archive_system_directive`
- `doctor_fix`
- `create_project_node`
- `onboard_project_store`
- `ingest_command`
- `preflight_ingest`
- `index_command`
- `move_project_store`
- `register_project_agent`

## WebSocket

`WS /ws/command-center`

Events:

1. `command_center_init`
2. `command_center_updated`
