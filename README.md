# Maestro

Maestro is a setup-first OpenClaw deployment for construction teams:
- **Company Maestro (default agent):** control plane, command center, orchestration.
- **Project Maestros:** project-specific agents backed by project knowledge stores.

## Frontends

1. **Workspace frontend** (`frontend/`)
- Route: `/{project-slug}`
- Purpose: sheet/page exploration, workspaces, pointers, highlights.

2. **Command Center frontend** (`command_center_frontend/`)
- Route: `/command-center`
- Purpose: fleet topology, node intelligence modal, control-plane actions.

## Recommended Runtime Flow

```bash
# First-time install
pip install -e .
maestro-setup

# Daily startup path (recommended)
maestro up

# Optional: startup with monitor TUI (logs/compute/tokens)
maestro up --tui
```

`maestro up` runs `maestro doctor --fix` before serving.

## CLI Commands

```bash
maestro-setup                                  # Company bootstrap wizard
maestro update [--dry-run] [--no-restart]      # Safe, idempotent install migration
maestro doctor [--fix] [--json]                # Validate/repair runtime wiring
maestro up [--port 3000] [--store ...]         # Preferred startup
maestro up --tui [--port 3000] [--store ...]   # Preferred startup + monitor TUI
maestro serve [--port 3000] [--store ...]      # Server only
maestro start [--port 3000] [--store ...]      # Legacy runtime path
maestro-purchase                                # Provision a dedicated project maestro
maestro ingest <folder> [--project-name ...]   # Build/update project knowledge store
maestro index <project_dir>                     # Rebuild project index.json
maestro tools <command> ...                     # Project tool surface
maestro license <subcommand> ...                # License utilities
```

## Project Maestro Provisioning

```bash
maestro-purchase
```

`maestro-purchase` handles:
- project identity (`project_name`, `slug`, `assignee`)
- project OpenClaw agent registration
- project Telegram bot validation
- project license activation flow (free first node, paid slots require card-on-file)
- registry sync into fleet control plane

## Knowledge Store Model

`ingest.py` / `maestro ingest` is critical for specialized Project Maestros.
Company Maestro reads project intelligence from knowledge-store outputs; it does not replace per-project ingest.

Default resolved fleet store root is from install state/workspace config. Manual `--store` is an advanced override.

Example fixture path used in local validation:
- `/Users/seanschneidewent/Desktop/knowledge_store_data`

## Server Routes

### Workspace APIs/UI
- `/api/projects`
- `/{slug}/api/...`
- `/{slug}/ws`
- `/{slug}`

### Command Center + Control Plane
- `/api/command-center/state`
- `/api/command-center/projects/{slug}`
- `/api/system/awareness`
- `/api/command-center/fleet-registry`
- `/api/command-center/actions`
- `/ws/command-center`
- `/command-center`

## Action API (`POST /api/command-center/actions`)

Supported actions:
- `sync_registry`
- `doctor_fix`
- `create_project_node`
- `onboard_project_store`
- `ingest_command`
- `preflight_ingest`
- `index_command`
- `move_project_store`
- `register_project_agent`

## Documentation Map

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/architecture.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/command-center.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/operations.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/troubleshooting.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/api-contracts.md`

Legacy product/spec docs retained for context:
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/MAESTRO_SPEC.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/LICENSE_SYSTEM.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/LICENSE_IMPLEMENTATION.md`

## Development

```bash
pip install -e "[dev]"
pytest
```

Frontend builds:

```bash
cd frontend && npm install && npm run build
cd command_center_frontend && npm install && npm run build
```

## Key Modules

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/setup.py` - setup wizard
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/setup_wizard.py` - setup wizard implementation
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/update.py` - install update/migration
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/doctor.py` - runtime doctor/fix
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/control_plane.py` - control-plane compatibility facade
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/control_plane_core.py` - awareness + fleet control plane implementation
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/command_center.py` - read-only intelligence aggregation
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server.py` - FastAPI server + route layer
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server_actions.py` - command-center action execution
