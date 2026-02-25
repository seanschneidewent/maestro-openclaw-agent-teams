# Command Center

Current implementation reference for **The Commander** control-plane UI.

## Implemented Now

- Tactical topology React UI at `/command-center`
- Top commander node + project node cards
- Expanded node modal with live conversation (manual send for project nodes)
- Per-node status report (heartbeat overlay + computed fallback) in modal
- Compact System Doctor and System Directives panels
- Fleet provisioning helper (`maestro-purchase`) still available in UI

## Core APIs

- `GET /api/command-center/state`
- `GET /api/command-center/projects/{slug}` (legacy modal contract kept)
- `GET /api/command-center/nodes/{slug}/status`
- `GET /api/command-center/nodes/{slug}/conversation`
- `POST /api/command-center/nodes/{slug}/conversation/send`
- `GET /api/system/awareness`
- `GET /api/command-center/fleet-registry`
- `POST /api/command-center/actions`
- `WS /ws/command-center`

## Chain-of-Command Guards

- Commander send endpoint only targets `maestro-project-*` agents.
- Archived/unregistered nodes are rejected.
- Manual UI source guard is enforced (`source=command_center_ui`).
- Commander remains read-only against raw project plan files.

## Data Notes

- Heartbeat file path per project:
  - `<project_store>/.command_center/heartbeat.json`
- Registry path:
  - `<fleet_store_root>/.command_center/fleet_registry.json`
- Directive store path:
  - `<fleet_store_root>/.command_center/system_directives.json`

Fixture path used during testing:
- `/Users/seanschneidewent/Desktop/knowledge_store_data`

## Operations

- Preferred startup: `maestro up`
- Repairs: `maestro doctor --fix`
- Upgrade migration: `maestro update`
