# Maestro

AI infrastructure for construction teams, with a setup-first Company Maestro and project-specific knowledge stores.

## Current Architecture

Maestro currently has two distinct frontends:

1. Workspace frontend (React, three-panel layout)
- Route: `/{project-slug}`
- Purpose: project plan exploration, workspaces, regions, highlights
- Backed by project APIs and WebSocket updates
- Source folder: `frontend/` (built assets served from `frontend/dist`)

2. Command Center frontend (placeholder HTML)
- Route: `/command-center`
- Purpose: company-level landing/status page for Company Maestro
- Full command center implementation is planned; placeholder is intentionally simple today
- Source folder: `command_center_frontend/`

## Agent Model

1. Company Maestro (default)
- Created by `maestro-setup`
- Configured as the default OpenClaw agent (`maestro-company`)
- Owns orchestration flow and Command Center entrypoint

2. Project/Specialized Maestro
- Backed by a project knowledge store under `knowledge_store/<project>/`
- Created by ingesting project plan PDFs
- Access to project tools is license-gated via project key

## CLI Commands

```bash
maestro-setup                                  # Interactive setup wizard (company/default agent)
maestro start [--port 3000] [--store ...]      # Runtime TUI + health checks + starts web server
maestro serve [--port 3000] [--store ...]      # FastAPI server only
maestro update [--dry-run] [--no-restart]      # Safe in-place update/migration for existing installs
maestro ingest <folder> [--project-name ...]   # Build project knowledge store from plan PDFs
maestro index <project_dir>                     # Rebuild project index.json
maestro tools <command> ...                     # Query/manage project knowledge store
maestro license <subcommand> ...                # Generate/validate license keys
```

## Setup Flow (Company Bootstrap)

```bash
pip install -e .
maestro-setup
```

`maestro-setup` walks through:
- company name
- prerequisites (OpenClaw, Node/npm, etc.)
- provider + API keys
- Telegram bot
- Tailscale (install/login checks)
- OpenClaw config merge and default agent wiring
- workspace materialization under `~/.openclaw/workspace-maestro`

Then run:

```bash
maestro start
```

## Project Ingest Flow (Specialized Maestro Data Plane)

`maestro ingest` is critical for specialized/project Maestro capability. It builds the knowledge store used by project tools and workspace UI.

```bash
maestro ingest "/path/to/plan-pdfs" --project-name "CFA Love Field"
```

Output structure:

```text
knowledge_store/
  <project>/
    project.json
    index.json
    pages/
      <page>/
        page.png
        pass1.json
        pointers/
          <region>/
            crop.png
            pass2.json
    workspaces/
```

## Serving and Routes

Start server directly:

```bash
maestro serve --port 3000
```

Routes:
- `/api/projects` (project list)
- `/{slug}/api/...` (project APIs)
- `/{slug}/ws` (project live updates)
- `/{slug}` (workspace frontend SPA)
- `/command-center` (company command center placeholder)

## Development

Install:

```bash
pip install -e "[dev]"
```

Run tests:

```bash
pytest
```

Current baseline: `109` passing tests.

## Compatibility Wrappers

Root-level `server.py` and `ingest.py` are compatibility shims for legacy usage (`python server.py`, `python ingest.py`) and delegate to canonical package modules (`maestro.server`, `maestro.ingest`).

## Key Files

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/setup.py` — setup wizard
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/runtime.py` — runtime TUI/health dashboard
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server.py` — FastAPI server + frontend serving
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/ingest.py` — two-pass ingest pipeline
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/tools.py` — licensed project tool surface
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/COMMAND_CENTER.md` — command center product spec
