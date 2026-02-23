# Maestro

Maestro is now **Solo-first** by default, with Fleet/enterprise features available behind explicit activation.

## Product Profiles

1. **Solo (default)**
- Default agent: `maestro-personal`
- Primary UI: `/workspace`
- Focus: one personal Maestro engine for plan search, workspace management, and schedule management

2. **Fleet (advanced / enterprise)**
- Commander + project maestros
- Command Center UI: `/command-center`
- Enabled explicitly with `maestro fleet enable`

## Solo Quickstart (Primary Path)

```bash
# Install once
pip install -e .

# 1) Setup (primary command)
maestro setup

# 2) Start runtime (doctor + serve)
maestro up

# 3) Ingest plans
maestro ingest /abs/path/to/plans
```

Open: `http://localhost:3000/workspace`

Field access (same tailnet/VPN):

- Connect host + mobile/laptop to Tailscale.
- Use `http://<tailscale-ip>:3000/workspace`.

## Fleet Enablement (Advanced)

```bash
# Turn on fleet profile + migrations + health checks
maestro fleet enable

# Optional: provision project maestros
maestro fleet purchase

# Fleet status / URL helpers
maestro fleet status
maestro fleet command-center
```

Open: `http://localhost:3000/command-center`

In Solo profile, command-center APIs/routes return:

```json
{"error":"Fleet mode not enabled","next_step":"Run maestro fleet enable"}
```

## CLI Surface

Primary commands:

- `maestro setup`
- `maestro up`
- `maestro ingest`
- `maestro doctor`
- `maestro doctor --field-access-required`
- `maestro update`
- `maestro serve`
- `maestro fleet ...`

Fleet namespace:

- `maestro fleet enable`
- `maestro fleet status`
- `maestro fleet purchase`
- `maestro fleet command-center [--open]`

Compatibility aliases retained (with deprecation warnings):

- `maestro-setup` -> `maestro setup`
- `maestro-purchase` -> `maestro fleet purchase`
- `maestro start` remains legacy; prefer `maestro up`

## Canonical Routes

### Solo workspace routes

- `/workspace`
- `/workspace/ws`
- `/workspace/api/*`

Legacy compatibility routes remain active:

- `/{slug}` and `/{slug}/api/*`
- `/agents/{agent_id}/workspace` and `/agents/{agent_id}/workspace/api/*`

### Fleet routes (enabled only in Fleet profile)

- `/command-center`
- `/ws/command-center`
- `/api/command-center/*`
- `/api/system/awareness`

## Ingest Semantics in Solo

Solo defaults to a single active project target:

1. First ingest creates/sets active project.
2. Later ingests update active project by default.
3. Use `--new-project-name` to intentionally create a different project target.
4. `--project-name` is retained for compatibility and mapped to new-project behavior in Solo.

## Documentation Map

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/README.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/setup.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/ingest.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/workspace.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/fleet/enable.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/fleet/command-center.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/fleet/purchase.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/reference/cli.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/reference/paths-env.md`

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

## Backend Module Boundaries

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server.py`: FastAPI composition + route wiring.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server_project_store.py`: project/page loading from knowledge-store layout.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server_workspace_data.py`: workspace JSON and pointer bbox helpers.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server_schedule.py`: managed schedule load/upsert/close/status payload logic.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server_command_center.py`: command-center router (fleet-gated).
