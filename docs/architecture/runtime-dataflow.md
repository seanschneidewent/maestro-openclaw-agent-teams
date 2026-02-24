# Runtime Data Flow

## Solo Pipeline (Primary)

1. `maestro-solo ingest` writes/updates project store artifacts.
2. `packages/maestro-engine/src/maestro_engine/index.py` builds pointer/search index data.
3. `packages/maestro-solo/src/maestro_solo/server.py` serves workspace APIs and websocket updates.
4. `workspace_frontend` renders Solo workspace state.

## Fleet Pipeline (Enterprise)

1. `maestro-fleet` commands drive control-plane and project-maestro lifecycle.
2. Command Center reads fleet registry and node status APIs.
3. Node modal reads/writes conversation through command-center API routes.
4. Backend parses OpenClaw session logs from `~/.openclaw/agents/{agent}/sessions`.
5. Websocket updates refresh node state in `command_center_frontend`.

## Heartbeat Overlay

1. Optional file: `<project_store>/.command_center/heartbeat.json`
2. If fresh (`<=120s`), heartbeat summary/risk/actions drive status report.
3. If stale/missing, computed snapshot remains source of truth.
