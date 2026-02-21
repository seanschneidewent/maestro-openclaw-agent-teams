# Architecture

## System Model

Maestro runs as a two-layer agent system:

1. **Company Maestro (default agent)**
- Control plane
- Awareness contract (`/api/system/awareness`)
- Fleet registry + project provisioning actions
- Command Center orchestration

2. **Project Maestro (specialized agents)**
- Data plane for a specific project
- Uses project knowledge store outputs
- Performs deep project reasoning/tooling

## Runtime Surfaces

### Backend
- FastAPI server (`maestro/server.py`)
- File-watch updates from fleet store root
- Websocket broadcasts for workspace + command center

### Frontends
- Workspace frontend (`frontend/`) on `/{slug}`
- Command Center frontend (`command_center_frontend/`) on `/command-center`

## Data Flow

1. Ingest builds/updates project knowledge stores (`maestro ingest` / `ingest.py`)
2. Command-center aggregator normalizes project snapshots (`maestro/command_center.py`)
3. Control-plane registry/awareness derives fleet state (`maestro/control_plane.py`)
4. Server exposes APIs and pushes updates (`maestro/server.py`)

## Store Resolution

Fleet store root resolution order:
1. CLI `--store`
2. install state (`~/.maestro/install.json`)
3. company workspace `.env` (`MAESTRO_STORE`)
4. process env `MAESTRO_STORE`
5. workspace fallback `workspace/knowledge_store`

## Registry

Registry path:
- `<fleet_store_root>/.command_center/fleet_registry.json`

Registry tracks normalized project identities and runtime metadata used by:
- awareness
- command-center cards
- onboarding/control actions
