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
- Enabled explicitly with `maestro-fleet enable`

## Solo Quickstart (Primary Path)

```bash
# Install extracted packages (local editable)
pip install -e /absolute/path/to/repo/packages/maestro-engine -e /absolute/path/to/repo/packages/maestro-solo

# 1) Setup (primary command)
maestro-solo setup

# 2) Start runtime (doctor + serve + Solo TUI monitor)
maestro-solo up --tui

# 3) Ingest plans
maestro-solo ingest /abs/path/to/plans
```

Open: `http://localhost:3000/workspace`

Field access (same tailnet/VPN):

- Connect host + mobile/laptop to Tailscale.
- Use `http://<tailscale-ip>:3000/workspace`.

## Solo Payment + License Test (Dev)

Run two local services in separate terminals:

```bash
maestro-solo-license-service --port 8082
maestro-solo-billing-service --port 8081
```

Then in another terminal:

```bash
# Purchase + poll until licensed (test mode)
maestro-solo purchase --email you@example.com --plan solo_test_monthly

# Check local license
maestro-solo status

# Start runtime (license-gated + Solo TUI monitor)
maestro-solo up --tui
```

Test mode supports a manual trigger if needed:

```bash
curl -sS -X POST http://127.0.0.1:8081/v1/solo/dev/mark-paid \
  -H 'content-type: application/json' \
  -d '{"purchase_id":"<PURCHASE_ID>"}'
```

## Fleet Enablement (Advanced)

Install Fleet product package:

```bash
pip install -e /absolute/path/to/repo -e /absolute/path/to/repo/packages/maestro-fleet
```

```bash
# Turn on fleet profile + migrations + health checks
maestro-fleet enable

# Optional: provision project maestros
maestro-fleet purchase

# Fleet status / URL helpers
maestro-fleet status
maestro-fleet command-center
```

Open: `http://localhost:3000/command-center`

In Solo profile, command-center APIs/routes return:

```json
{"error":"Fleet mode not enabled","next_step":"Run maestro-fleet enable"}
```

## CLI Surface

Primary commands:

- `maestro-solo setup`
- `maestro-solo up --tui`
- `maestro-solo ingest`
- `maestro-solo doctor`
- `maestro-solo doctor --field-access-required`
- `maestro-solo status`
- `maestro-solo purchase`
- `maestro-solo migrate-legacy`

Fleet namespace:

- `maestro-fleet enable`
- `maestro-fleet status`
- `maestro-fleet purchase`
- `maestro-fleet command-center [--open]`
- `maestro-fleet up --tui`

Compatibility aliases retained (with deprecation warnings):

- `maestro-setup` -> `maestro-solo setup`
- `maestro-purchase` -> `maestro-fleet purchase`
- `maestro fleet ...` -> `maestro-fleet ...` (transition alias path)
- `maestro start` is deprecated; prefer `maestro-solo up --tui`

## Canonical Routes

### Solo workspace routes

- `/workspace`
- `/workspace/ws`
- `/workspace/api/*`

Compatibility routes remain active:

- `/{slug}` and `/{slug}/api/*`
- `/agents/{agent_id}/workspace` and `/agents/{agent_id}/workspace/api/*`

### Fleet routes (enabled only in Fleet profile)

- `/command-center`
- `/ws/command-center`
- `/api/command-center/*`
- `/api/system/awareness`

## Ingest Semantics in Solo

Solo defaults to a single active project target:

1. Ingest uses folder name when `--project-name` is omitted.
2. The resolved target is recorded as active project metadata.
3. Use `--project-name` to force a specific project target.

## Documentation Map

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/README.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/setup.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/ingest.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/workspace.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/payment-license.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/migrate-legacy.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/solo/clean-machine-test.md`
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

Workspace + Command Center frontend builds:

```bash
cd workspace_frontend && npm install && npm run build
cd command_center_frontend && npm install && npm run build
```

## Backend Module Boundaries

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-solo/src/maestro_solo/server.py`: Solo FastAPI composition and workspace route wiring.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-solo/src/maestro_solo/cli.py`: Solo product CLI surface.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-engine/src/maestro_engine/server_project_store.py`: project/page loading from knowledge-store layout.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-engine/src/maestro_engine/server_workspace_data.py`: workspace JSON and pointer bbox helpers.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-engine/src/maestro_engine/server_schedule.py`: managed schedule load/upsert/close/status payload logic.
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-fleet/src/maestro_fleet/cli.py`: Fleet product CLI surface.
