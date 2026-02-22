# Runtime Data Flow

## Ingestion to UI Pipeline

1. `maestro ingest` writes/updates project store artifacts.
2. `maestro/command_center.py` builds normalized snapshots.
3. `maestro/control_plane_core.py` syncs registry and awareness contracts.
4. `maestro/server.py` serves APIs and websocket updates.
5. `command_center_frontend` renders fleet state and node modals.

## Conversation Pipeline

1. Node modal reads `GET /api/command-center/nodes/{slug}/conversation`.
2. Backend parses OpenClaw session logs from `~/.openclaw/agents/{agent}/sessions`.
3. Manual sends call `POST /api/command-center/nodes/{slug}/conversation/send`.
4. Backend invokes `openclaw agent` with persistent session id.
5. Updated timeline is returned and websocket state refresh broadcasts.

## Heartbeat Overlay

1. Optional file: `<project_store>/.command_center/heartbeat.json`
2. If fresh (`<=120s`), heartbeat summary/risk/actions drive status report.
3. If stale/missing, computed snapshot remains source of truth.
