"""
Maestro Frontend Server — serves knowledge_store data + live WebSocket updates.

Multi-project: each project dir becomes a route prefix (slug).
No database. No auth. Reads from filesystem, watches for changes.

Usage:
    maestro serve [--port 3000] [--store knowledge_store]
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image

from .command_center import (
    build_command_center_state,
    build_project_detail,
    build_project_snapshot,
    discover_project_dirs,
)
from .config import THUMBNAIL_CACHE_DIR
from .control_plane import (
    build_awareness_state,
    sync_fleet_registry,
)
from .doctor import build_doctor_report
from .server_actions import ActionError, run_command_center_action
from .utils import load_json, slugify

# ── Config ──────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STORE = Path("knowledge_store")
# Check bundled location first (pip install), then repo layout
_bundled_frontend = SCRIPT_DIR / "frontend"
_repo_frontend = SCRIPT_DIR.parent / "frontend" / "dist"
FRONTEND_DIR = _bundled_frontend if _bundled_frontend.exists() else _repo_frontend
_bundled_command_center = SCRIPT_DIR / "command_center_frontend"
_repo_command_center_dist = SCRIPT_DIR.parent / "command_center_frontend" / "dist"
_repo_command_center_root = SCRIPT_DIR.parent / "command_center_frontend"
if _bundled_command_center.exists():
    COMMAND_CENTER_DIR = _bundled_command_center
elif _repo_command_center_dist.exists():
    COMMAND_CENTER_DIR = _repo_command_center_dist
else:
    COMMAND_CENTER_DIR = _repo_command_center_root

# ── In-memory data ─────────────────────────────────────────────

projects: dict[str, dict[str, Any]] = {}
store_path: Path = DEFAULT_STORE
server_port: int = 3000
ws_clients: dict[str, set[WebSocket]] = {}
project_dir_slug_index: dict[str, str] = {}
command_center_state: dict[str, Any] = {}
command_center_ws_clients: set[WebSocket] = set()
fleet_registry: dict[str, Any] = {}
awareness_state: dict[str, Any] = {}


def load_all_projects():
    """Load all project directories from knowledge_store."""
    global projects, ws_clients, project_dir_slug_index
    projects = {}
    ws_clients = {}
    project_dir_slug_index = {}
    if not store_path.exists():
        return

    for project_dir in discover_project_dirs(store_path):
        try:
            cc_snapshot = build_project_snapshot(project_dir)
            slug = str(cc_snapshot.get("slug", "")) or slugify(project_dir.name)
        except Exception:
            slug = slugify(project_dir.name)
        project_dir_slug_index[project_dir.name] = slug
        projects[slug] = _load_project(project_dir, slug)
        ws_clients.setdefault(slug, set())

    for slug, proj in projects.items():
        page_count = len(proj.get("pages", {}))
        pointer_count = sum(len(p.get("pointers", {})) for p in proj.get("pages", {}).values())
        print(f"Loaded: {proj['name']} ({slug}) — {page_count} pages, {pointer_count} pointers")


def _load_project(project_dir: Path, slug: str) -> dict[str, Any]:
    project_meta = load_json(project_dir / "project.json")
    project_name = project_dir.name
    if isinstance(project_meta, dict):
        maybe_name = project_meta.get("name")
        if isinstance(maybe_name, str) and maybe_name.strip():
            project_name = maybe_name.strip()

    proj: dict[str, Any] = {
        "name": project_name,
        "slug": slug,
        "path": str(project_dir),
        "pages": {},
    }

    pages_dir = project_dir / "pages"
    if pages_dir.exists():
        for page_dir in sorted(pages_dir.iterdir(), key=lambda p: p.name.lower()):
            if page_dir.is_dir():
                _load_page(proj, page_dir)

    proj["disciplines"] = sorted({
        str(p.get("discipline", "General")).strip() or "General"
        for p in proj["pages"].values()
    })

    return proj


def _load_page(proj: dict[str, Any], page_dir: Path) -> dict[str, Any] | None:
    page_name = page_dir.name
    page: dict[str, Any] = {
        "name": page_name,
        "path": str(page_dir),
        "page_type": "unknown",
        "discipline": "General",
        "sheet_reflection": "",
        "index": {},
        "cross_references": [],
        "regions": [],
        "pointers": {},
    }

    pass1 = load_json(page_dir / "pass1.json")
    if isinstance(pass1, dict):
        page["page_type"] = pass1.get("page_type", "unknown")
        page["discipline"] = pass1.get("discipline", "General") or "General"
        page["sheet_reflection"] = pass1.get("sheet_reflection", "")
        page["index"] = pass1.get("index", {}) if isinstance(pass1.get("index"), dict) else {}
        page["cross_references"] = pass1.get("cross_references", []) if isinstance(pass1.get("cross_references"), list) else []
        page["regions"] = pass1.get("regions", []) if isinstance(pass1.get("regions"), list) else []
        page["sheet_info"] = pass1.get("sheet_info", {})

    pointers_dir = page_dir / "pointers"
    if pointers_dir.exists():
        for pointer_dir in sorted(pointers_dir.iterdir(), key=lambda p: p.name.lower()):
            if not pointer_dir.is_dir():
                continue
            region_id = pointer_dir.name
            pass2_path = pointer_dir / "pass2.json"
            if pass2_path.exists():
                try:
                    pointer_data = json.loads(pass2_path.read_text(encoding="utf-8"))
                    if not isinstance(pointer_data, dict):
                        pointer_data = {}
                    pointer_data.setdefault("content_markdown", "")
                    page["pointers"][region_id] = pointer_data
                except Exception:
                    pass

    proj["pages"][page_name] = page
    proj["disciplines"] = sorted({
        str(p.get("discipline", "General")).strip() or "General"
        for p in proj["pages"].values()
    })
    return page


def _get_project(slug: str) -> dict[str, Any] | None:
    return projects.get(slug)


def _registry_by_slug(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    by_slug: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("project_slug", "")).strip()
        if slug:
            by_slug[slug] = item
    return by_slug


def _apply_registry_identity(snapshot: dict[str, Any], entry: dict[str, Any] | None):
    if not isinstance(snapshot, dict) or not isinstance(entry, dict):
        return

    assignee = str(entry.get("assignee", "")).strip()
    superintendent = str(entry.get("superintendent", "")).strip()

    if superintendent.lower() in ("", "unknown") and assignee.lower() not in ("", "unassigned"):
        superintendent = assignee

    if assignee:
        snapshot["assignee"] = assignee
    if superintendent:
        snapshot["superintendent"] = superintendent


def _apply_registry_identity_to_command_center_state(state: dict[str, Any], registry: dict[str, Any]):
    if not isinstance(state, dict):
        return
    projects_payload = state.get("projects")
    if not isinstance(projects_payload, list):
        return

    by_slug = _registry_by_slug(registry)
    for project in projects_payload:
        if not isinstance(project, dict):
            continue
        slug = str(project.get("slug", "")).strip()
        if not slug:
            continue
        _apply_registry_identity(project, by_slug.get(slug))


def _refresh_command_center_state():
    """Recompute in-memory command-center state from the current store path."""
    global command_center_state
    try:
        command_center_state = build_command_center_state(store_path)
        if fleet_registry:
            _apply_registry_identity_to_command_center_state(command_center_state, fleet_registry)
    except Exception as exc:
        print(f"Command center state refresh failed: {exc}", file=sys.stderr)
        command_center_state = {
            "updated_at": "",
            "store_root": str(store_path),
            "commander": {"name": "Sean (GC Owner)", "lastSeen": "Unknown"},
            "orchestrator": {
                "id": "CM-01",
                "name": "Company Maestro",
                "status": "Error",
                "currentAction": "Failed to load command center state",
            },
            "directives": [],
            "projects": [],
        }


def _refresh_control_plane_state():
    """Recompute fleet registry + machine-specific awareness state."""
    global fleet_registry, awareness_state, command_center_state
    try:
        fleet_registry = sync_fleet_registry(store_path)
        if command_center_state:
            _apply_registry_identity_to_command_center_state(command_center_state, fleet_registry)
    except Exception as exc:
        print(f"Fleet registry refresh failed: {exc}", file=sys.stderr)
        fleet_registry = {
            "version": 1,
            "updated_at": "",
            "store_root": str(store_path),
            "projects": [],
        }

    try:
        awareness_state = build_awareness_state(
            store_path,
            command_center_state=command_center_state,
            web_port=server_port,
        )
    except Exception as exc:
        print(f"Awareness state refresh failed: {exc}", file=sys.stderr)
        awareness_state = {
            "generated_at": "",
            "posture": "degraded",
            "degraded_reasons": [f"awareness refresh failed: {exc}"],
            "paths": {"store_root": str(store_path)},
        }


def _refresh_all_state():
    load_all_projects()
    _refresh_command_center_state()
    _refresh_control_plane_state()


def _command_center_project_dirs_by_slug() -> dict[str, Path]:
    """Index discoverable project directories by normalized slug."""
    result: dict[str, Path] = {}
    for project_dir in discover_project_dirs(store_path):
        try:
            snapshot = build_project_snapshot(project_dir)
            slug = snapshot.get("slug")
            if isinstance(slug, str) and slug:
                result[slug] = project_dir
        except Exception:
            continue
    return result


def _is_command_center_relevant(path: Path) -> bool:
    """Whether a changed file should trigger command-center state refresh."""
    if path.suffix.lower() != ".json":
        return False

    name = path.name.lower()
    if name in ("project.json", "index.json"):
        return True
    if name in ("current_update.json", "lookahead.json", "baseline.json"):
        return True
    if name == "log.json":
        return True
    if name == "decisions.json":
        return True
    if name == "scope_matrix.json":
        return True
    if ".command_center" in path.parts:
        return True
    return False


# ── Filesystem watcher ──────────────────────────────────────────

async def watch_knowledge_store():
    try:
        from watchfiles import awatch
    except ImportError:
        print("watchfiles not installed — live updates disabled", file=sys.stderr)
        return

    if not store_path.exists():
        return

    print(f"Watching {store_path} for changes...")

    async for changes in awatch(store_path):
        for change_type, path_str in changes:
            path = Path(path_str)
            if path.suffix not in (".json", ".png"):
                continue

            try:
                rel_parts = path.relative_to(store_path).parts
            except ValueError:
                continue

            # Command-center updates are store-wide (single-root or multi-root).
            if _is_command_center_relevant(path):
                _refresh_all_state()
                await _broadcast_command_center_update()

            # Existing workspace frontend live updates are only for multi-project
            # page/workspace changes where first segment is a project dir.
            if len(rel_parts) < 2:
                continue

            project_dir_name = rel_parts[0]
            slug = project_dir_slug_index.get(project_dir_name, slugify(project_dir_name))
            proj = projects.get(slug)
            if not proj:
                continue

            if len(rel_parts) >= 3 and rel_parts[1] == "workspaces":
                ws_slug = rel_parts[2] if len(rel_parts) > 2 else None
                await broadcast(slug, {"type": "workspace_updated", "slug": ws_slug})
                continue

            if len(rel_parts) < 3 or rel_parts[1] != "pages":
                continue

            pg_name = rel_parts[2]
            pg_dir = store_path / rel_parts[0] / "pages" / pg_name

            if not pg_dir.is_dir():
                continue

            _load_page(proj, pg_dir)

            if path.name == "pass1.json":
                event = {"type": "page_added", "page": pg_name}
            elif path.name == "pass2.json" and len(rel_parts) >= 5:
                event = {"type": "region_complete", "page": pg_name, "region": rel_parts[4]}
            elif path.name == "page.png":
                event = {"type": "page_image_ready", "page": pg_name}
            else:
                event = {"type": "page_updated", "page": pg_name}

            await broadcast(slug, event)


async def broadcast(slug: str, event: dict):
    clients = ws_clients.get(slug, set())
    if not clients:
        return
    data = json.dumps(event)
    disconnected = set()
    for ws in clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    clients -= disconnected


async def broadcast_command_center(event: dict[str, Any]):
    if not command_center_ws_clients:
        return

    payload = json.dumps(event)
    disconnected: set[WebSocket] = set()
    for ws in command_center_ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)
    command_center_ws_clients.difference_update(disconnected)


async def _broadcast_command_center_update():
    await broadcast_command_center({
        "type": "command_center_updated",
        "state": command_center_state,
        "awareness": awareness_state,
    })


# ── Thumbnails ──────────────────────────────────────────────────

def get_thumbnail(page_dir: Path, width: int = 800, quality: int = 80) -> bytes | None:
    png_path = page_dir / "page.png"
    if not png_path.exists():
        return None

    cache_dir = page_dir / THUMBNAIL_CACHE_DIR
    cache_key = f"thumb_{width}q{quality}.jpg"
    cache_path = cache_dir / cache_key

    if cache_path.exists() and cache_path.stat().st_mtime >= png_path.stat().st_mtime:
        return cache_path.read_bytes()

    try:
        img = Image.open(png_path)
        w_ratio = width / img.width
        new_height = int(img.height * w_ratio)
        img = img.resize((width, new_height), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        cache_dir.mkdir(exist_ok=True)
        cache_path.write_bytes(data)
        return data
    except Exception as e:
        print(f"Thumbnail error for {png_path}: {e}", file=sys.stderr)
        return None


# ── Workspace helpers ───────────────────────────────────────────

def _workspaces_dir(proj: dict[str, Any]) -> Path:
    ws_dir = Path(proj["path"]) / "workspaces"
    ws_dir.mkdir(exist_ok=True)
    return ws_dir


def _load_workspace(proj: dict[str, Any], ws_slug: str) -> dict[str, Any] | None:
    ws_path = _workspaces_dir(proj) / ws_slug / "workspace.json"
    return load_json(ws_path) if ws_path.exists() else None


def _load_all_workspaces(proj: dict[str, Any]) -> list[dict[str, Any]]:
    ws_dir = _workspaces_dir(proj)
    workspaces = []
    for d in sorted(ws_dir.iterdir()):
        if d.is_dir():
            ws = _load_workspace(proj, d.name)
            if ws:
                workspaces.append(ws)
    return workspaces


def _get_page_bboxes(proj: dict[str, Any], page_name: str, pointer_ids: list[str]) -> list[dict[str, Any]]:
    page = proj.get("pages", {}).get(page_name, {})
    regions = page.get("regions", [])
    bboxes = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        if r.get("id") in pointer_ids:
            bboxes.append({
                "id": r["id"],
                "label": r.get("label", ""),
                "type": r.get("type", ""),
                "bbox": r.get("bbox", {}),
            })
    return bboxes


# ── FastAPI app ─────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(_: FastAPI):
    _refresh_all_state()
    watch_task = asyncio.create_task(watch_knowledge_store())
    try:
        yield
    finally:
        watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await watch_task


app = FastAPI(title="Maestro", docs_url=None, redoc_url=None, lifespan=_lifespan)


@app.get("/api/projects")
async def api_projects():
    return {"projects": [
        {
            "slug": proj["slug"],
            "name": proj["name"],
            "page_count": len(proj.get("pages", {})),
            "pointer_count": sum(len(p.get("pointers", {})) for p in proj.get("pages", {}).values()),
            "disciplines": proj.get("disciplines", []),
        }
        for proj in projects.values()
    ]}


@app.get("/api/command-center/state")
async def api_command_center_state():
    if not command_center_state:
        _refresh_command_center_state()
    if not awareness_state:
        _refresh_control_plane_state()
    return command_center_state


@app.get("/api/command-center/projects/{slug}")
async def api_command_center_project_detail(slug: str):
    project_dirs = _command_center_project_dirs_by_slug()
    project_dir = project_dirs.get(slug)
    if not project_dir:
        return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)

    try:
        detail = build_project_detail(project_dir)
        if not fleet_registry:
            _refresh_control_plane_state()
        snapshot = detail.get("snapshot")
        if isinstance(snapshot, dict):
            entry = _registry_by_slug(fleet_registry).get(slug)
            _apply_registry_identity(snapshot, entry)
        return detail
    except Exception as exc:
        return JSONResponse({"error": f"Failed to build project detail: {exc}"}, status_code=500)


@app.get("/api/system/awareness")
async def api_system_awareness():
    if not awareness_state:
        _refresh_control_plane_state()
    return awareness_state


@app.get("/api/command-center/fleet-registry")
async def api_fleet_registry():
    if not fleet_registry:
        _refresh_control_plane_state()
    return fleet_registry


@app.post("/api/command-center/actions")
async def api_command_center_actions(payload: dict[str, Any]):
    try:
        return await run_command_center_action(
            payload,
            store_path=store_path,
            refresh_all_state=_refresh_all_state,
            broadcast_command_center_update=_broadcast_command_center_update,
            get_fleet_registry=lambda: fleet_registry,
            get_awareness_state=lambda: awareness_state,
            doctor_builder=build_doctor_report,
        )
    except ActionError as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)


@app.get("/{slug}/api/project")
async def api_project(slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)
    return {
        "name": proj["name"],
        "slug": proj["slug"],
        "page_count": len(proj.get("pages", {})),
        "pointer_count": sum(len(p.get("pointers", {})) for p in proj.get("pages", {}).values()),
        "disciplines": proj.get("disciplines", []),
    }


@app.get("/{slug}/api/disciplines")
async def api_disciplines(slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"disciplines": proj.get("disciplines", [])}


@app.get("/{slug}/api/pages")
async def api_pages(slug: str, discipline: str | None = None):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    pages = []
    for name, page in proj.get("pages", {}).items():
        page_disc = str(page.get("discipline", ""))
        if discipline and page_disc.lower() != discipline.lower():
            continue
        pages.append({
            "name": name,
            "page_type": page.get("page_type", "unknown"),
            "discipline": page_disc,
            "region_count": len(page.get("regions", [])),
            "pointer_count": len(page.get("pointers", {})),
            "sheet_info": page.get("sheet_info", {}),
            "has_image": (Path(page["path"]) / "page.png").exists() if page.get("path") else False,
        })
    return {"pages": sorted(pages, key=lambda p: p["name"].lower())}


@app.get("/{slug}/api/pages/{page_name}")
async def api_page(slug: str, page_name: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    page = proj.get("pages", {}).get(page_name)
    if not page:
        return JSONResponse({"error": f"Page '{page_name}' not found"}, status_code=404)
    return {
        "name": page["name"],
        "page_type": page.get("page_type"),
        "discipline": page.get("discipline"),
        "sheet_reflection": page.get("sheet_reflection", ""),
        "index": page.get("index", {}),
        "cross_references": page.get("cross_references", []),
        "regions": page.get("regions", []),
        "sheet_info": page.get("sheet_info", {}),
    }


@app.get("/{slug}/api/pages/{page_name}/thumb")
async def api_page_thumb(slug: str, page_name: str, w: int = 800, q: int = 80):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    page = proj.get("pages", {}).get(page_name)
    if not page or not page.get("path"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    data = get_thumbnail(Path(page["path"]), width=min(w, 2000), quality=min(q, 95))
    if not data:
        return JSONResponse({"error": "Image not available"}, status_code=404)
    return Response(content=data, media_type="image/jpeg")


@app.get("/{slug}/api/pages/{page_name}/image")
async def api_page_image(slug: str, page_name: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    page = proj.get("pages", {}).get(page_name)
    if not page or not page.get("path"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    png_path = Path(page["path"]) / "page.png"
    if not png_path.exists():
        return JSONResponse({"error": "Image not available"}, status_code=404)
    return FileResponse(png_path, media_type="image/png")


@app.get("/{slug}/api/pages/{page_name}/regions")
async def api_page_regions(slug: str, page_name: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    page = proj.get("pages", {}).get(page_name)
    if not page:
        return JSONResponse({"error": "Not found"}, status_code=404)
    pointers = page.get("pointers", {})
    regions = []
    for r in page.get("regions", []):
        if not isinstance(r, dict):
            continue
        rid = r.get("id", "")
        regions.append({
            "id": rid,
            "type": r.get("type"),
            "label": r.get("label"),
            "detail_number": r.get("detail_number"),
            "bbox": r.get("bbox"),
            "shows": r.get("shows"),
            "has_pass2": bool(rid and rid in pointers),
        })
    return {"regions": regions}


@app.get("/{slug}/api/pages/{page_name}/regions/{region_id}")
async def api_region(slug: str, page_name: str, region_id: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    page = proj.get("pages", {}).get(page_name)
    if not page:
        return JSONResponse({"error": "Page not found"}, status_code=404)
    pointer = page.get("pointers", {}).get(region_id)
    if not pointer:
        return JSONResponse({"error": "Region not found"}, status_code=404)
    return pointer


@app.get("/{slug}/api/pages/{page_name}/regions/{region_id}/crop")
async def api_region_crop(slug: str, page_name: str, region_id: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    page = proj.get("pages", {}).get(page_name)
    if not page or not page.get("path"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    crop_path = Path(page["path"]) / "pointers" / region_id / "crop.png"
    if not crop_path.exists():
        return JSONResponse({"error": "Crop not available"}, status_code=404)
    return FileResponse(crop_path, media_type="image/png")


# ── Workspace routes ────────────────────────────────────────────

@app.get("/{slug}/api/workspaces")
async def api_workspaces(slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    workspaces = _load_all_workspaces(proj)
    return {"workspaces": [
        {
            "slug": ws["slug"],
            "title": ws.get("title", ""),
            "description": ws.get("description", ""),
            "page_count": len(ws.get("pages", [])),
            "note_count": len(ws.get("notes", [])),
            "created_at": ws.get("created_at", ""),
        }
        for ws in workspaces
    ]}


@app.get("/{slug}/api/workspaces/{ws_slug}/images/{filename}")
async def api_workspace_image(slug: str, ws_slug: str, filename: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    img_path = _workspaces_dir(proj) / ws_slug / "generated_images" / filename
    if not img_path.exists() or not img_path.is_file():
        return JSONResponse({"error": "Image not found"}, status_code=404)
    suffix = img_path.suffix.lower()
    media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return FileResponse(img_path, media_type=media_type)


@app.get("/{slug}/api/workspaces/{ws_slug}/images/{filename}/thumb")
async def api_workspace_image_thumb(slug: str, ws_slug: str, filename: str, w: int = 800, q: int = 80):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    img_dir = _workspaces_dir(proj) / ws_slug / "generated_images"
    img_path = img_dir / filename
    if not img_path.exists():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    cache_dir = img_dir / ".cache"
    cache_key = f"{img_path.stem}_thumb_{min(w, 2000)}q{min(q, 95)}.jpg"
    cache_path = cache_dir / cache_key

    if cache_path.exists() and cache_path.stat().st_mtime >= img_path.stat().st_mtime:
        return Response(content=cache_path.read_bytes(), media_type="image/jpeg")

    try:
        img = Image.open(img_path)
        w_ratio = min(w, 2000) / img.width
        new_height = int(img.height * w_ratio)
        img = img.resize((min(w, 2000), new_height), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=min(q, 95))
        data = buf.getvalue()
        cache_dir.mkdir(exist_ok=True)
        cache_path.write_bytes(data)
        return Response(content=data, media_type="image/jpeg")
    except Exception as e:
        print(f"Thumbnail error for {img_path}: {e}", file=sys.stderr)
        return JSONResponse({"error": "Thumbnail generation failed"}, status_code=500)


@app.get("/{slug}/api/workspaces/{ws_slug}")
async def api_workspace(slug: str, ws_slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    ws = _load_workspace(proj, ws_slug)
    if not ws:
        return JSONResponse({"error": f"Workspace '{ws_slug}' not found"}, status_code=404)

    enriched_pages = []
    for page in ws.get("pages", []):
        pg_name = page.get("page_name", "")
        selected = page.get("selected_pointers", [])
        enriched = {
            **page,
            "pointer_bboxes": _get_page_bboxes(proj, pg_name, selected),
            "has_image": (Path(proj.get("pages", {}).get(pg_name, {}).get("path", "")) / "page.png").exists()
                if proj.get("pages", {}).get(pg_name, {}).get("path") else False,
        }
        enriched_pages.append(enriched)

    generated_images = []
    for img in ws.get("generated_images", []):
        img_path = _workspaces_dir(proj) / ws_slug / "generated_images" / img.get("filename", "")
        generated_images.append({**img, "has_file": img_path.exists()})

    return {**ws, "pages": enriched_pages, "generated_images": generated_images}


# ── WebSocket ───────────────────────────────────────────────────

@app.websocket("/ws/command-center")
async def websocket_command_center(websocket: WebSocket):
    await websocket.accept()
    command_center_ws_clients.add(websocket)
    try:
        if not command_center_state:
            _refresh_command_center_state()
        if not awareness_state:
            _refresh_control_plane_state()
        await websocket.send_text(json.dumps({
            "type": "command_center_init",
            "state": command_center_state,
            "awareness": awareness_state,
        }))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        command_center_ws_clients.discard(websocket)


@app.websocket("/{slug}/ws")
async def websocket_endpoint(slug: str, websocket: WebSocket):
    proj = _get_project(slug)
    if not proj:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    ws_clients.setdefault(slug, set()).add(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "init",
            "page_count": len(proj.get("pages", {})),
            "disciplines": proj.get("disciplines", []),
        }))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.get(slug, set()).discard(websocket)


# ── Frontend SPA ────────────────────────────────────────────────


def _command_center_index_path() -> Path:
    return COMMAND_CENTER_DIR / "index.html"


@app.get("/command-center")
async def command_center():
    index_path = _command_center_index_path()
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(
        {
            "error": "Command Center frontend not found",
            "hint": "Build with: cd command_center_frontend && npm install && npm run build",
        },
        status_code=404,
    )


@app.get("/command-center/assets/{rest:path}")
async def command_center_assets(rest: str):
    asset_path = COMMAND_CENTER_DIR / "assets" / rest
    if asset_path.exists() and asset_path.is_file():
        return FileResponse(asset_path)
    return JSONResponse({"error": "Not found"}, status_code=404)


@app.get("/command-center/{rest:path}")
async def command_center_spa(rest: str):
    if rest.startswith("api/") or rest.startswith("ws/"):
        return JSONResponse({"error": "Not found"}, status_code=404)

    file_path = COMMAND_CENTER_DIR / rest
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)

    index_path = _command_center_index_path()
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"error": "Command Center frontend not found"}, status_code=404)


@app.get("/assets/{rest:path}")
async def serve_static_assets(rest: str):
    if FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / "assets" / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)
    return JSONResponse({"error": "Not found"}, status_code=404)


@app.get("/{slug}/{rest:path}")
async def serve_frontend(slug: str, rest: str = ""):
    if slug in ("api", "ws"):
        return JSONResponse({"error": "Not found"}, status_code=404)

    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)

    if rest and FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)

    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return JSONResponse({"error": "Frontend not built"}, status_code=404)


@app.get("/{slug}")
async def serve_frontend_root(slug: str):
    return await serve_frontend(slug, "")


@app.get("/")
async def root():
    if len(projects) == 1:
        slug = list(projects.keys())[0]
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=f"/{slug}/")
    return await api_projects()
