# API Contracts

## Awareness

`GET /api/system/awareness`

Key sections:
- `network`: localhost/tailnet/recommended URLs
- `paths`: store root, registry path, workspace root
- `services`: tailscale/openclaw/telegram/company-agent health
- `fleet`: project count + stale project report + registry
- `commands`: operational CLI commands
- `available_actions`: supported command-center actions

## Command Center State

`GET /api/command-center/state`

Returns:
- commander node metadata
- orchestrator status/action
- directives feed
- project snapshots list

## Project Detail

`GET /api/command-center/projects/{slug}`

Returns:
- `snapshot`
- drawer payloads (operational, critical path, RFI/submittal, exposure, scope)

## Actions

`POST /api/command-center/actions`

Supported `action` values:
- `sync_registry`
- `doctor_fix`
- `create_project_node`
- `onboard_project_store`
- `ingest_command`
- `preflight_ingest`
- `index_command`
- `move_project_store`
- `register_project_agent`

Errors are returned as JSON payloads with HTTP 4xx/5xx.
