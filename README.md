# Maestro

**AI that actually understands your construction plans.**

Maestro ingests construction plan PDFs, analyzes every sheet with AI vision, and gives superintendents instant answers about their plans — via text, voice, or a live web dashboard.

## Quick Start

```bash
# 1. Install
pip install -e .

# 2. Set your Gemini API key
cp .env.example .env
# Edit .env with your key from https://aistudio.google.com/apikey

# 3. Ingest a set of plans
maestro ingest "path/to/plan-pdfs/" --project-name "My Project"

# 4. Start the server
maestro serve
# Open http://localhost:3000 in your browser
```

## What It Does

1. **Ingest** — Converts PDFs to PNGs, then runs two-pass Gemini vision analysis:
   - **Pass 1:** Sheet-level analysis — identifies regions, details, cross-references, disciplines
   - **Pass 2:** Deep dive on every region — materials, dimensions, specs, coordination notes

2. **Serve** — FastAPI server with a React frontend showing:
   - Plan tree organized by discipline
   - Workspaces for organizing findings around a topic
   - Zoomable plan viewer with overlay annotations
   - Live updates via WebSocket when new analysis completes

3. **Agent** — OpenClaw agent integration with 29+ tools:
   - Search across all sheets and pointers
   - Create and manage workspaces
   - Highlight items on plans with Gemini vision
   - Generate images (visualizations, diagrams, annotated photos)
   - Answer questions about materials, specs, dimensions, cross-references

## Installation

### As a Package

```bash
pip install -e .          # Editable install
pip install -e ".[dev]"   # With test dependencies
```

This gives you the `maestro` CLI:

```bash
maestro ingest <folder> [--project-name "Name"] [--dpi 200]
maestro serve [--port 3000] [--store knowledge_store]
maestro tools <command> [args]
maestro index <project_dir>
```

### Frontend

```bash
cd frontend && npm install && npm run build && cd ..
```

## Architecture

```
maestro-ingest/
├── maestro/                   # Python package (the engine)
│   ├── __init__.py            # Version
│   ├── config.py              # Centralized config (models, paths, defaults)
│   ├── utils.py               # Shared utilities (JSON parsing, bbox, Gemini helpers)
│   ├── prompts.py             # All Gemini prompts (Pass 1, Pass 2, Highlight)
│   ├── loader.py              # Knowledge store loader
│   ├── index.py               # Project index builder
│   ├── tools.py               # MaestroTools class — query/workspace/highlight/image
│   ├── ingest.py              # PDF ingest pipeline
│   ├── server.py              # FastAPI server + WebSocket + frontend serving
│   └── cli.py                 # Unified CLI entry point
│
├── frontend/                  # React + Vite + Tailwind dashboard
│   └── src/
│       ├── App.jsx            # Main app — three-panel layout
│       ├── components/        # PlansPanel, WorkspaceView, PlanViewerModal, WorkspaceSwitcher
│       ├── hooks/             # useWebSocket
│       └── lib/               # API client
│
├── agent/                     # OpenClaw agent workspace template
│   ├── AGENTS.md              # Agent instructions
│   ├── SOUL.md                # Agent identity
│   └── skills/maestro/        # Skill definition + tools shim
│       ├── SKILL.md           # Tool documentation
│       └── scripts/
│           ├── tools.py       # CLI shim → maestro.cli
│           └── loader.py      # Import shim → maestro.loader
│
├── voice_proxy.py             # ElevenLabs ↔ OpenClaw voice bridge
├── tests/                     # 87 unit tests
│   ├── test_utils.py          # JSON parsing, bbox, slugify, file I/O
│   ├── test_loader.py         # Project loading, page resolution
│   ├── test_tools.py          # Knowledge queries, workspace management
│   └── test_index.py          # Index building, cross-refs
│
├── pyproject.toml             # Package config (hatchling)
├── requirements.txt           # Legacy deps (use pyproject.toml instead)
└── knowledge_store/           # Output from ingest (gitignored)
    └── <project>/
        ├── project.json
        ├── index.json
        ├── pages/
        │   └── <page>/
        │       ├── page.png
        │       ├── pass1.json
        │       └── pointers/
        │           └── <region>/
        │               ├── crop.png
        │               └── pass2.json
        └── workspaces/
            └── <workspace>/
                ├── workspace.json
                └── generated_images/
```

## Python API

```python
from maestro.tools import MaestroTools

# Load a project
tools = MaestroTools(store_path="knowledge_store")

# Search
results = tools.search("waterproofing membrane")

# Get details
summary = tools.get_sheet_summary("A101")
detail = tools.get_region_detail("A101_Floor_Plan_p001", "r_100_200_300_400")

# Workspaces
tools.create_workspace("Refuse Enclosure", "All refuse enclosure details")
tools.add_workspace_page("refuse_enclosure", "A101")
tools.highlight("refuse_enclosure", "A101", "dumpster pad and enclosure walls")
```

## CLI Tools Reference

```bash
# Knowledge queries
maestro tools list_disciplines
maestro tools list_pages [--discipline Architectural]
maestro tools search "waterproofing"
maestro tools get_sheet_summary A101
maestro tools get_sheet_index A101
maestro tools list_regions A101
maestro tools get_region_detail A101_Floor_Plan_p001 r_100_200_300_400
maestro tools find_cross_references A101_Floor_Plan_p001
maestro tools list_modifications
maestro tools check_gaps

# Workspaces
maestro tools create_workspace "Title" "Description"
maestro tools list_workspaces
maestro tools get_workspace <slug>
maestro tools add_page <slug> <page>
maestro tools remove_page <slug> <page>
maestro tools select_pointers <slug> <page> <pointer_id> [...]
maestro tools deselect_pointers <slug> <page> <pointer_id> [...]
maestro tools add_note <slug> "text" [--source_page X]
maestro tools add_description <slug> <page> "description"

# Gemini vision
maestro tools highlight <slug> <page> "query"
maestro tools clear_highlights <slug> <page>

# Image generation
maestro tools generate_image <slug> "prompt" [--reference_pages A101 S201] [--aspect_ratio 16:9]
maestro tools delete_image <slug> <filename>
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | List all projects |
| GET | `/{slug}/api/project` | Project metadata |
| GET | `/{slug}/api/disciplines` | List disciplines |
| GET | `/{slug}/api/pages` | List pages (filterable by discipline) |
| GET | `/{slug}/api/pages/{page}` | Page detail |
| GET | `/{slug}/api/pages/{page}/image` | Full-resolution PNG |
| GET | `/{slug}/api/pages/{page}/thumb` | JPEG thumbnail |
| GET | `/{slug}/api/pages/{page}/regions` | List regions |
| GET | `/{slug}/api/pages/{page}/regions/{id}` | Region deep detail |
| GET | `/{slug}/api/pages/{page}/regions/{id}/crop` | Cropped region PNG |
| GET | `/{slug}/api/workspaces` | List workspaces |
| GET | `/{slug}/api/workspaces/{ws}` | Workspace detail |
| GET | `/{slug}/api/workspaces/{ws}/images/{file}` | Generated image |
| WS | `/{slug}/ws` | Live updates |

## Testing

```bash
pip install -e ".[dev]"
pytest                    # Run all 87 tests
pytest -v                 # Verbose
pytest tests/test_utils.py  # Specific module
```

## Multi-Project

The server supports multiple projects. Each project directory in `knowledge_store/` becomes a route prefix:

```
http://localhost:3000/my-project/          # Frontend
http://localhost:3000/my-project/api/...   # API
```

## Requirements

- Python 3.11+
- Node.js 18+ (for frontend build)
- Gemini API key (Google AI Studio)

## License

Proprietary. © Maestro Construction Agents.
