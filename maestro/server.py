"""
Maestro Workspace Frontend Server — serves knowledge_store data + live WebSocket updates.

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
from .commander_chat import (
    MAX_MESSAGE_CHARS,
    build_conversation_preview,
    read_agent_conversation,
    send_agent_message,
)
from .config import THUMBNAIL_CACHE_DIR
from .control_plane import (
    build_awareness_state,
    resolve_node_identity,
    save_fleet_registry,
    sync_fleet_registry,
)
from .install_state import load_install_state
from .profile import fleet_enabled as profile_fleet_enabled
from .doctor import build_doctor_report
from .server_actions import ActionError, run_command_center_action
from .server_command_center import CommandCenterRouterContext, create_command_center_router
from .server_schedule import (
    close_schedule_item_for_project as _close_schedule_item_for_project,
    schedule_items_payload as _schedule_items_payload,
    schedule_status_payload as _schedule_status_payload,
    upsert_schedule_item_for_project as _upsert_schedule_item_for_project,
)
from .server_project_store import (
    load_all_projects as load_projects_from_store,
    load_page as load_project_page,
)
from .server_workspace_data import (
    get_page_bboxes as _get_page_bboxes,
    load_all_workspaces as _load_all_workspaces,
    load_workspace as _load_workspace,
    workspaces_dir as _workspaces_dir,
)
from . import server_command_center_state as command_center_state_ops
from .utils import slugify, slugify_underscore

# ── Config ──────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STORE = Path("knowledge_store")
# Workspace frontend: check bundled locations first (pip install), then repo layout.
_bundled_workspace_frontend = SCRIPT_DIR / "workspace_frontend"
_bundled_legacy_frontend = SCRIPT_DIR / "frontend"
_repo_workspace_frontend = SCRIPT_DIR.parent / "workspace_frontend" / "dist"
_repo_legacy_frontend = SCRIPT_DIR.parent / "frontend" / "dist"
if _bundled_workspace_frontend.exists():
    FRONTEND_DIR = _bundled_workspace_frontend
elif _bundled_legacy_frontend.exists():
    FRONTEND_DIR = _bundled_legacy_frontend
elif _repo_workspace_frontend.exists():
    FRONTEND_DIR = _repo_workspace_frontend
else:
    FRONTEND_DIR = _repo_legacy_frontend
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
agent_project_slug_index: dict[str, str] = {}
COMMANDER_NODE_SLUG = "commander"


def _fleet_mode_enabled() -> bool:
    return profile_fleet_enabled()


def _workspace_missing_project_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": "No active project available in Solo workspace.",
            "next_step": "Run maestro ingest <path-to-pdfs>",
        },
        status_code=404,
    )


def _active_workspace_slug() -> str | None:
    state = load_install_state()
    active_slug = str(state.get("active_project_slug", "")).strip()
    if active_slug and active_slug in projects:
        return active_slug

    active_name = str(state.get("active_project_name", "")).strip()
    if active_name:
        by_name = slugify(active_name)
        if by_name in projects:
            return by_name
        for slug, proj in projects.items():
            if str(proj.get("name", "")).strip().lower() == active_name.lower():
                return slug

    if projects:
        return next(iter(sorted(projects.keys())))
    return None


def load_all_projects():
    """Load all project directories from knowledge_store."""
    global projects, ws_clients, project_dir_slug_index
    projects, project_dir_slug_index = load_projects_from_store(
        store_path,
        discover_project_dirs_fn=discover_project_dirs,
        build_project_snapshot_fn=build_project_snapshot,
    )
    ws_clients = {slug: set() for slug in projects.keys()}

    for slug, proj in projects.items():
        page_count = len(proj.get("pages", {}))
        pointer_count = sum(len(p.get("pointers", {})) for p in proj.get("pages", {}).values())
        print(f"Loaded: {proj['name']} ({slug}) — {page_count} pages, {pointer_count} pointers")


def _get_project(slug: str) -> dict[str, Any] | None:
    return projects.get(slug)


def _registry_by_slug(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return command_center_state_ops.registry_by_slug(registry)


def _workspace_route_payload(slug: str, entry: dict[str, Any] | None = None) -> dict[str, str]:
    return command_center_state_ops.workspace_route_payload(slug, entry)


def _build_conversation_preview_for_node(agent_id: str, project_slug: str) -> dict[str, Any]:
    return build_conversation_preview(agent_id, project_slug=project_slug)


def _apply_registry_identity(snapshot: dict[str, Any], entry: dict[str, Any] | None):
    command_center_state_ops.apply_registry_identity(
        snapshot,
        entry,
        resolve_node_identity_fn=resolve_node_identity,
        conversation_preview_builder=_build_conversation_preview_for_node,
    )


def _apply_registry_identity_to_command_center_state(state: dict[str, Any], registry: dict[str, Any]):
    command_center_state_ops.apply_registry_identity_to_command_center_state(
        state,
        registry,
        apply_registry_identity_fn=_apply_registry_identity,
    )


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
            "commander": {"name": "The Commander", "lastSeen": "Unknown"},
            "orchestrator": {
                "id": "CM-01",
                "name": "The Commander",
                "status": "Error",
                "currentAction": "Failed to load command center state",
            },
            "directives": [],
            "projects": [],
        }


def _refresh_control_plane_state():
    """Recompute fleet registry + machine-specific awareness state."""
    global fleet_registry, awareness_state, command_center_state, agent_project_slug_index
    try:
        fleet_registry = sync_fleet_registry(store_path)
        by_slug = _registry_by_slug(fleet_registry)
        agent_project_slug_index = {}
        for slug in projects.keys():
            entry = by_slug.get(slug)
            routes = _workspace_route_payload(slug, entry)
            agent_project_slug_index[routes["agent_id"]] = slug
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
        agent_project_slug_index = {}

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


def _resolve_agent_slug(agent_id: str) -> str | None:
    clean = str(agent_id).strip()
    if not clean:
        return None
    slug = agent_project_slug_index.get(clean)
    if slug and slug in projects:
        return slug

    fallback_prefix = "maestro-project-"
    if clean.startswith(fallback_prefix):
        fallback = clean[len(fallback_prefix):].strip()
        if fallback in projects:
            return fallback
    return None


def _command_center_project_dirs_by_slug() -> dict[str, Path]:
    return command_center_state_ops.command_center_project_dirs_by_slug(
        store_path,
        discover_project_dirs_fn=discover_project_dirs,
        build_project_snapshot_fn=build_project_snapshot,
    )


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

            load_project_page(proj, pg_dir)

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

# Workspace data helpers moved to `maestro.server_workspace_data`.
# Schedule data helpers moved to `maestro.server_schedule`.

def _ensure_command_center_state():
    if not command_center_state:
        _refresh_command_center_state()


def _ensure_awareness_state():
    if not awareness_state:
        _refresh_control_plane_state()


def _ensure_fleet_registry():
    if not fleet_registry:
        _refresh_control_plane_state()


def _load_command_center_project_detail(slug: str) -> dict[str, Any]:
    return command_center_state_ops.load_command_center_project_detail(
        slug,
        store_path=store_path,
        fleet_registry=fleet_registry,
        ensure_fleet_registry=_ensure_fleet_registry,
        discover_project_dirs_fn=discover_project_dirs,
        build_project_snapshot_fn=build_project_snapshot,
        build_project_detail_fn=build_project_detail,
        apply_registry_identity_fn=_apply_registry_identity,
    )


def _registry_entry_for_slug(slug: str) -> dict[str, Any] | None:
    return command_center_state_ops.registry_entry_for_slug(
        slug,
        fleet_registry=fleet_registry,
        ensure_fleet_registry=_ensure_fleet_registry,
    )


def _node_agent_id_for_slug(slug: str) -> str:
    return command_center_state_ops.node_agent_id_for_slug(
        slug,
        entry=_registry_entry_for_slug(slug),
    )


def _load_command_center_node_status(slug: str) -> dict[str, Any]:
    return command_center_state_ops.load_command_center_node_status(
        slug,
        commander_node_slug=COMMANDER_NODE_SLUG,
        awareness_state=awareness_state,
        command_center_state=command_center_state,
        ensure_awareness_state=_ensure_awareness_state,
        load_project_detail_fn=_load_command_center_project_detail,
        node_agent_id_for_slug_fn=_node_agent_id_for_slug,
    )


def _load_node_conversation(slug: str, limit: int = 100, before: str | None = None) -> dict[str, Any]:
    return command_center_state_ops.load_node_conversation(
        slug,
        commander_node_slug=COMMANDER_NODE_SLUG,
        projects=projects,
        node_agent_id_for_slug_fn=_node_agent_id_for_slug,
        read_agent_conversation_fn=read_agent_conversation,
        limit=limit,
        before=before,
    )


def _send_node_message(slug: str, message: str, source: str) -> dict[str, Any]:
    payload = command_center_state_ops.send_node_message(
        slug,
        message,
        source,
        commander_node_slug=COMMANDER_NODE_SLUG,
        projects=projects,
        store_path=store_path,
        fleet_registry=fleet_registry,
        registry_entry_for_slug_fn=_registry_entry_for_slug,
        send_agent_message_fn=send_agent_message,
        save_fleet_registry_fn=save_fleet_registry,
        max_message_chars=MAX_MESSAGE_CHARS,
    )

    _refresh_command_center_state()
    _refresh_control_plane_state()
    try:
        asyncio.create_task(_broadcast_command_center_update())
    except RuntimeError:
        pass

    return payload


async def _run_command_center_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return await run_command_center_action(
        payload,
        store_path=store_path,
        refresh_all_state=_refresh_all_state,
        broadcast_command_center_update=_broadcast_command_center_update,
        get_fleet_registry=lambda: fleet_registry,
        get_awareness_state=lambda: awareness_state,
        doctor_builder=build_doctor_report,
    )


async def api_command_center_state():
    """Compatibility wrapper for tests and internal callers."""
    _ensure_command_center_state()
    _ensure_awareness_state()
    return command_center_state


async def api_command_center_project_detail(slug: str):
    """Compatibility wrapper for tests and internal callers."""
    try:
        return _load_command_center_project_detail(slug)
    except KeyError:
        return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to build project detail: {exc}"}, status_code=500)


async def api_command_center_node_status(slug: str):
    """Compatibility wrapper for node status endpoint."""
    try:
        return _load_command_center_node_status(slug)
    except KeyError:
        return JSONResponse({"error": f"Node '{slug}' not found"}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to load node status: {exc}"}, status_code=500)


async def api_command_center_node_conversation(slug: str, limit: int = 100, before: str | None = None):
    """Compatibility wrapper for node conversation endpoint."""
    try:
        return _load_node_conversation(slug, limit=limit, before=before)
    except KeyError:
        return JSONResponse({"error": f"Node '{slug}' not found"}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to load node conversation: {exc}"}, status_code=500)


async def api_command_center_node_send(slug: str, payload: dict[str, Any]):
    """Compatibility wrapper for node send endpoint."""
    try:
        return _send_node_message(
            slug,
            str(payload.get("message", "")),
            str(payload.get("source", "command_center_ui")),
        )
    except KeyError:
        return JSONResponse({"error": f"Node '{slug}' not found"}, status_code=404)
    except ActionError as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to send node message: {exc}"}, status_code=500)


async def api_system_awareness():
    """Compatibility wrapper for tests and internal callers."""
    _ensure_awareness_state()
    return awareness_state


async def api_fleet_registry():
    """Compatibility wrapper for tests and internal callers."""
    _ensure_fleet_registry()
    return fleet_registry


async def api_command_center_actions(payload: dict[str, Any]):
    """Compatibility wrapper for tests and internal callers."""
    try:
        return await _run_command_center_action_payload(payload)
    except ActionError as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)


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

app.include_router(create_command_center_router(CommandCenterRouterContext(
    command_center_dir=COMMAND_CENTER_DIR,
    command_center_ws_clients=command_center_ws_clients,
    ensure_command_center_state=_ensure_command_center_state,
    ensure_awareness_state=_ensure_awareness_state,
    ensure_fleet_registry=_ensure_fleet_registry,
    get_command_center_state=lambda: command_center_state,
    get_awareness_state=lambda: awareness_state,
    get_fleet_registry=lambda: fleet_registry,
    load_project_detail=_load_command_center_project_detail,
    load_project_status=_load_command_center_node_status,
    read_node_conversation=_load_node_conversation,
    send_node_message=_send_node_message,
    run_action=_run_command_center_action_payload,
    fleet_enabled_fn=_fleet_mode_enabled,
)))


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


@app.get("/api/agents/workspaces")
async def api_agent_workspace_index():
    if not fleet_registry:
        _refresh_control_plane_state()
    by_slug = _registry_by_slug(fleet_registry)
    payload = []
    for slug, proj in projects.items():
        entry = by_slug.get(slug)
        routes = _workspace_route_payload(slug, entry)
        payload.append({
            "slug": slug,
            "name": proj.get("name", slug),
            "status": str(entry.get("status", "active")) if isinstance(entry, dict) else "active",
            "agent_id": routes["agent_id"],
            "project_workspace_url": routes["project_workspace_url"],
            "agent_workspace_url": routes["agent_workspace_url"],
        })
    payload.sort(key=lambda item: str(item.get("name", "")).lower())
    return {"agents": payload}


def _workspace_slug_or_response() -> tuple[str | None, JSONResponse | None]:
    slug = _active_workspace_slug()
    if not slug:
        return None, _workspace_missing_project_response()
    return slug, None


@app.get("/workspace/api/project")
async def api_workspace_project():
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_project(str(slug))


@app.get("/workspace/api/disciplines")
async def api_workspace_disciplines():
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_disciplines(str(slug))


@app.get("/workspace/api/pages")
async def api_workspace_pages(discipline: str | None = None):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_pages(str(slug), discipline=discipline)


@app.get("/workspace/api/pages/{page_name}")
async def api_workspace_page(page_name: str):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_page(str(slug), page_name)


@app.get("/workspace/api/pages/{page_name}/thumb")
async def api_workspace_page_thumb(page_name: str, w: int = 800, q: int = 80):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_page_thumb(str(slug), page_name, w=w, q=q)


@app.get("/workspace/api/pages/{page_name}/image")
async def api_workspace_page_image(page_name: str):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_page_image(str(slug), page_name)


@app.get("/workspace/api/pages/{page_name}/regions")
async def api_workspace_regions(page_name: str):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_page_regions(str(slug), page_name)


@app.get("/workspace/api/pages/{page_name}/regions/{region_id}")
async def api_workspace_region(page_name: str, region_id: str):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_region(str(slug), page_name, region_id)


@app.get("/workspace/api/pages/{page_name}/regions/{region_id}/crop")
async def api_workspace_region_crop(page_name: str, region_id: str):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_region_crop(str(slug), page_name, region_id)


@app.get("/workspace/api/workspaces")
async def api_workspace_workspaces():
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_workspaces(str(slug))


@app.get("/workspace/api/workspaces/{ws_slug}")
async def api_workspace_workspace(ws_slug: str):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_workspace(str(slug), ws_slug)


@app.get("/workspace/api/workspaces/{ws_slug}/images/{filename}")
async def api_workspace_generated_image(ws_slug: str, filename: str):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_workspace_image(str(slug), ws_slug, filename)


@app.get("/workspace/api/workspaces/{ws_slug}/images/{filename}/thumb")
async def api_workspace_generated_image_thumb(ws_slug: str, filename: str, w: int = 800, q: int = 80):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_workspace_image_thumb(str(slug), ws_slug, filename, w=w, q=q)


@app.get("/workspace/api/schedule/status")
async def api_workspace_schedule_status():
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_schedule_status(str(slug))


@app.get("/workspace/api/schedule/items")
async def api_workspace_schedule_items(status: str | None = None):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_schedule_items(str(slug), status=status)


@app.post("/workspace/api/schedule/items/upsert")
async def api_workspace_schedule_upsert(payload: dict[str, Any]):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_schedule_upsert_item(str(slug), payload)


@app.post("/workspace/api/schedule/constraints")
async def api_workspace_schedule_constraint(payload: dict[str, Any]):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_schedule_set_constraint(str(slug), payload)


@app.post("/workspace/api/schedule/items/{item_id}/close")
async def api_workspace_schedule_close(item_id: str, payload: dict[str, Any] | None = None):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_schedule_close_item(str(slug), item_id, payload)


@app.get("/{slug}/api/project")
async def api_project(slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)
    return {
        "name": proj["name"],
        "slug": proj["slug"],
        "routes": _workspace_route_payload(slug, _registry_by_slug(fleet_registry).get(slug)),
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


@app.get("/{slug}/api/schedule/status")
async def api_schedule_status(slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return _schedule_status_payload(proj)


@app.get("/{slug}/api/schedule/items")
async def api_schedule_items(slug: str, status: str | None = None):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    try:
        return _schedule_items_payload(proj, status=status)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/{slug}/api/schedule/items/upsert")
async def api_schedule_upsert_item(slug: str, payload: dict[str, Any]):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    try:
        result, _ = _upsert_schedule_item_for_project(proj, payload if isinstance(payload, dict) else {})
        await broadcast(slug, {"type": "schedule_updated"})
        return result
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/{slug}/api/schedule/constraints")
async def api_schedule_set_constraint(slug: str, payload: dict[str, Any]):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)

    data = payload if isinstance(payload, dict) else {}
    description = str(data.get("description", "")).strip()
    if not description:
        return JSONResponse({"error": "description is required."}, status_code=400)

    constraint_id = slugify_underscore(str(data.get("constraint_id") or data.get("id") or "").strip())
    if not constraint_id:
        constraint_id = slugify_underscore(description)

    try:
        result, _ = _upsert_schedule_item_for_project(proj, {
            "item_id": constraint_id,
            "title": description,
            "type": "constraint",
            "status": data.get("status", "blocked"),
            "activity_id": data.get("activity_id"),
            "impact": data.get("impact"),
            "due_date": data.get("due_date"),
            "owner": data.get("owner"),
            "notes": data.get("notes"),
        })
        await broadcast(slug, {"type": "schedule_updated"})
        return result
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/{slug}/api/schedule/items/{item_id}/close")
async def api_schedule_close_item(slug: str, item_id: str, payload: dict[str, Any] | None = None):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    body = payload if isinstance(payload, dict) else {}
    try:
        result = _close_schedule_item_for_project(
            proj,
            item_id,
            reason=body.get("reason"),
            status=str(body.get("status", "done")),
        )
        await broadcast(slug, {"type": "schedule_updated"})
        return result
    except KeyError:
        return JSONResponse({"error": f"Schedule item '{item_id}' not found."}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


# ── Agent-scoped workspace API routes ──────────────────────────

@app.get("/agents/{agent_id}/workspace/api/project")
async def api_agent_project(agent_id: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_project(slug)


@app.get("/agents/{agent_id}/workspace/api/disciplines")
async def api_agent_disciplines(agent_id: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_disciplines(slug)


@app.get("/agents/{agent_id}/workspace/api/pages")
async def api_agent_pages(agent_id: str, discipline: str | None = None):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_pages(slug, discipline=discipline)


@app.get("/agents/{agent_id}/workspace/api/pages/{page_name}")
async def api_agent_page(agent_id: str, page_name: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_page(slug, page_name)


@app.get("/agents/{agent_id}/workspace/api/pages/{page_name}/thumb")
async def api_agent_page_thumb(agent_id: str, page_name: str, w: int = 800, q: int = 80):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_page_thumb(slug, page_name, w=w, q=q)


@app.get("/agents/{agent_id}/workspace/api/pages/{page_name}/image")
async def api_agent_page_image(agent_id: str, page_name: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_page_image(slug, page_name)


@app.get("/agents/{agent_id}/workspace/api/pages/{page_name}/regions")
async def api_agent_page_regions(agent_id: str, page_name: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_page_regions(slug, page_name)


@app.get("/agents/{agent_id}/workspace/api/pages/{page_name}/regions/{region_id}")
async def api_agent_region(agent_id: str, page_name: str, region_id: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_region(slug, page_name, region_id)


@app.get("/agents/{agent_id}/workspace/api/pages/{page_name}/regions/{region_id}/crop")
async def api_agent_region_crop(agent_id: str, page_name: str, region_id: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_region_crop(slug, page_name, region_id)


@app.get("/agents/{agent_id}/workspace/api/workspaces")
async def api_agent_workspaces_for_agent(agent_id: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_workspaces(slug)


@app.get("/agents/{agent_id}/workspace/api/workspaces/{ws_slug}")
async def api_agent_workspace(agent_id: str, ws_slug: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_workspace(slug, ws_slug)


@app.get("/agents/{agent_id}/workspace/api/schedule/status")
async def api_agent_schedule_status(agent_id: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_schedule_status(slug)


@app.get("/agents/{agent_id}/workspace/api/schedule/items")
async def api_agent_schedule_items(agent_id: str, status: str | None = None):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_schedule_items(slug, status=status)


@app.post("/agents/{agent_id}/workspace/api/schedule/items/upsert")
async def api_agent_schedule_upsert_item(agent_id: str, payload: dict[str, Any]):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_schedule_upsert_item(slug, payload)


@app.post("/agents/{agent_id}/workspace/api/schedule/constraints")
async def api_agent_schedule_constraint(agent_id: str, payload: dict[str, Any]):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_schedule_set_constraint(slug, payload)


@app.post("/agents/{agent_id}/workspace/api/schedule/items/{item_id}/close")
async def api_agent_schedule_close_item(agent_id: str, item_id: str, payload: dict[str, Any] | None = None):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_schedule_close_item(slug, item_id, payload)


@app.get("/agents/{agent_id}/workspace/api/workspaces/{ws_slug}/images/{filename}")
async def api_agent_workspace_image(agent_id: str, ws_slug: str, filename: str):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_workspace_image(slug, ws_slug, filename)


@app.get("/agents/{agent_id}/workspace/api/workspaces/{ws_slug}/images/{filename}/thumb")
async def api_agent_workspace_image_thumb(
    agent_id: str,
    ws_slug: str,
    filename: str,
    w: int = 800,
    q: int = 80,
):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)
    return await api_workspace_image_thumb(slug, ws_slug, filename, w=w, q=q)


# ── WebSocket ───────────────────────────────────────────────────
@app.websocket("/workspace/ws")
async def websocket_workspace(websocket: WebSocket):
    slug = _active_workspace_slug()
    if not slug:
        await websocket.close(code=4004)
        return
    await websocket_endpoint(slug, websocket)


@app.websocket("/agents/{agent_id}/workspace/ws")
async def websocket_agent_workspace(agent_id: str, websocket: WebSocket):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        await websocket.close(code=4004)
        return
    await websocket_endpoint(slug, websocket)


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


@app.get("/assets/{rest:path}")
async def serve_static_assets(rest: str):
    if FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / "assets" / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)
    return JSONResponse({"error": "Not found"}, status_code=404)


@app.get("/agents/{agent_id}/workspace/{rest:path}")
async def serve_agent_workspace(agent_id: str, rest: str = ""):
    slug = _resolve_agent_slug(agent_id)
    if not slug:
        return JSONResponse({"error": f"Agent '{agent_id}' not found"}, status_code=404)

    if rest.startswith("api/") or rest.startswith("ws/"):
        return JSONResponse({"error": "Not found"}, status_code=404)

    if rest and FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)

    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return JSONResponse({"error": "Frontend not built"}, status_code=404)


@app.get("/agents/{agent_id}/workspace")
async def serve_agent_workspace_root(agent_id: str):
    return await serve_agent_workspace(agent_id, "")


@app.get("/workspace/{rest:path}")
async def serve_workspace(rest: str = ""):
    if rest.startswith("api/") or rest.startswith("ws/"):
        return JSONResponse({"error": "Not found"}, status_code=404)

    if rest and FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)

    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return JSONResponse({"error": "Frontend not built"}, status_code=404)


@app.get("/workspace")
async def serve_workspace_root():
    return await serve_workspace("")


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
    if not _fleet_mode_enabled():
        from starlette.responses import RedirectResponse

        return RedirectResponse(url="/workspace")
    if len(projects) == 1:
        slug = list(projects.keys())[0]
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=f"/{slug}/")
    return await api_projects()
