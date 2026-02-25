"""Maestro Solo workspace frontend server (workspace-only)."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

from maestro_engine.server_schedule import (
    close_schedule_item_for_project as _close_schedule_item_for_project,
    schedule_items_payload as _schedule_items_payload,
    schedule_status_payload as _schedule_status_payload,
    schedule_timeline_payload as _schedule_timeline_payload,
    upsert_schedule_item_for_project as _upsert_schedule_item_for_project,
)
from maestro_engine.server_project_store import (
    load_all_projects as load_projects_from_store,
    load_page as load_project_page,
)
from maestro_engine.server_workspace_data import (
    get_page_bboxes as _get_page_bboxes,
    load_all_workspaces as _load_all_workspaces,
    load_project_notes as _load_project_notes,
    load_workspace as _load_workspace,
    workspaces_dir as _workspaces_dir,
)
from maestro_engine.server_runtime_shared import (
    THUMB_MAX_QUALITY,
    THUMB_MAX_WIDTH,
    get_generated_image_thumbnail,
    get_page_thumbnail,
    page_event_from_change,
    remap_ws_clients,
    resolve_active_project_slug,
    resolve_project_change_context,
)
from maestro_engine.utils import slugify, slugify_underscore

from .install_state import load_install_state


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STORE = Path("knowledge_store")


def _discover_frontend_dir() -> Path:
    bundled_workspace = SCRIPT_DIR / "workspace_frontend"
    if bundled_workspace.exists():
        return bundled_workspace

    bundled_legacy = SCRIPT_DIR / "frontend"
    if bundled_legacy.exists():
        return bundled_legacy

    for parent in SCRIPT_DIR.parents:
        workspace_candidate = parent / "workspace_frontend" / "dist"
        if workspace_candidate.exists():
            return workspace_candidate
        legacy_candidate = parent / "frontend" / "dist"
        if legacy_candidate.exists():
            return legacy_candidate

    return SCRIPT_DIR / "workspace_frontend"


FRONTEND_DIR = _discover_frontend_dir()


projects: dict[str, dict[str, Any]] = {}
store_path: Path = DEFAULT_STORE
server_port: int = 3000
ws_clients: dict[str, set[WebSocket]] = {}
project_dir_slug_index: dict[str, str] = {}


def _workspace_missing_project_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": "No active project available in Solo workspace.",
            "next_step": "Run maestro-solo ingest <path-to-pdfs>",
        },
        status_code=404,
    )


def _active_workspace_slug() -> str | None:
    return resolve_active_project_slug(projects, load_install_state(), slugify)


def load_all_projects():
    """Load all project directories from knowledge_store."""
    global projects, ws_clients, project_dir_slug_index
    existing_clients = ws_clients
    projects, project_dir_slug_index = load_projects_from_store(store_path)
    ws_clients = remap_ws_clients(existing_clients, projects)

    for slug, proj in projects.items():
        page_count = len(proj.get("pages", {}))
        pointer_count = sum(len(p.get("pointers", {})) for p in proj.get("pages", {}).values())
        print(f"Loaded: {proj['name']} ({slug}) — {page_count} pages, {pointer_count} pointers")


def _get_project(slug: str) -> dict[str, Any] | None:
    return projects.get(slug)


def _workspace_route_payload(slug: str) -> dict[str, str]:
    return {
        "workspace_url": f"/{slug}/",
        "workspace_api": f"/{slug}/api",
        "workspace_ws": f"/{slug}/ws",
        "solo_workspace": "/workspace",
    }


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
        load_all_projects()
        for _, path_str in changes:
            path = Path(path_str)

            slug, project_rel_parts = resolve_project_change_context(
                path=path,
                projects=projects,
                store_path=store_path,
                project_dir_slug_index=project_dir_slug_index,
                slugify_fn=slugify,
            )
            if not slug:
                continue
            proj = projects.get(slug)
            if not proj:
                continue

            # Workspace mutations should show up live in the workspace list/details.
            if project_rel_parts and project_rel_parts[0] == "workspaces":
                ws_slug = project_rel_parts[1] if len(project_rel_parts) > 1 else None
                await broadcast(slug, {"type": "workspace_updated", "slug": ws_slug})
                continue

            # Schedule file changes should live-refresh schedule UI.
            if project_rel_parts and project_rel_parts[0] == "schedule":
                await broadcast(slug, {"type": "schedule_updated"})
                continue

            # Project-level note changes should live-refresh notes UI.
            if project_rel_parts and project_rel_parts[0] == "notes":
                await broadcast(slug, {"type": "project_notes_updated"})
                continue

            if path.suffix not in (".json", ".png"):
                continue

            if len(project_rel_parts) < 2 or project_rel_parts[0] != "pages":
                # Unknown but relevant project-level JSON/PNG mutation.
                await broadcast(slug, {"type": "reload"})
                continue

            pg_name = project_rel_parts[1]
            pg_dir = Path(str(proj.get("path", ""))) / "pages" / pg_name
            if not pg_dir.is_dir():
                await broadcast(slug, {"type": "reload"})
                continue

            load_project_page(proj, pg_dir)
            await broadcast(slug, page_event_from_change(path.name, project_rel_parts, pg_name))


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

@asynccontextmanager
async def _lifespan(_: FastAPI):
    load_all_projects()
    watch_task = asyncio.create_task(watch_knowledge_store())
    try:
        yield
    finally:
        watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await watch_task


app = FastAPI(title="Maestro Solo", docs_url=None, redoc_url=None, lifespan=_lifespan)


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


@app.get("/workspace/api/project-notes")
async def api_workspace_project_notes():
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_project_notes(str(slug))


@app.get("/workspace/api/schedule/status")
async def api_workspace_schedule_status():
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_schedule_status(str(slug))


@app.get("/workspace/api/schedule/timeline")
async def api_workspace_schedule_timeline(month: str | None = None, include_empty_days: bool = True):
    slug, response = _workspace_slug_or_response()
    if response is not None:
        return response
    return await api_schedule_timeline(str(slug), month=month, include_empty_days=include_empty_days)


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
        "routes": _workspace_route_payload(slug),
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
    data = get_page_thumbnail(Path(page["path"]), width=min(w, THUMB_MAX_WIDTH), quality=min(q, THUMB_MAX_QUALITY))
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

    data = get_generated_image_thumbnail(
        image_path=img_path,
        cache_dir=img_dir / ".cache",
        width=min(w, THUMB_MAX_WIDTH),
        quality=min(q, THUMB_MAX_QUALITY),
    )
    if data is None:
        return JSONResponse({"error": "Thumbnail generation failed"}, status_code=500)
    return Response(content=data, media_type="image/jpeg")


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


@app.get("/{slug}/api/project-notes")
async def api_project_notes(slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    payload = _load_project_notes(proj)
    return {
        "ok": True,
        "project_slug": slug,
        "version": payload.get("version", 1),
        "updated_at": payload.get("updated_at", ""),
        "category_count": len(payload.get("categories", [])),
        "note_count": len(payload.get("notes", [])),
        "categories": payload.get("categories", []),
        "notes": payload.get("notes", []),
    }


@app.get("/{slug}/api/schedule/status")
async def api_schedule_status(slug: str):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return _schedule_status_payload(proj)


@app.get("/{slug}/api/schedule/timeline")
async def api_schedule_timeline(slug: str, month: str | None = None, include_empty_days: bool = True):
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    try:
        return _schedule_timeline_payload(proj, month=month, include_empty_days=include_empty_days)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


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


@app.websocket("/workspace/ws")
async def websocket_workspace(websocket: WebSocket):
    slug = _active_workspace_slug()
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


@app.get("/assets/{rest:path}")
async def serve_static_assets(rest: str):
    if FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / "assets" / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)
    return JSONResponse({"error": "Not found"}, status_code=404)


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
    from starlette.responses import RedirectResponse

    return RedirectResponse(url="/workspace")


def run_server(port: int, store: str, host: str = "0.0.0.0"):
    import uvicorn

    global store_path, server_port
    store_path = Path(store).resolve()
    server_port = int(port)
    load_all_projects()

    print(f"Maestro Solo server starting on http://localhost:{port}")
    print(f"Knowledge store: {store_path}")
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


def main(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(description="Start Maestro Solo web server")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--store", type=str, default="knowledge_store")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args(argv)
    run_server(port=args.port, store=args.store, host=args.host)


if __name__ == "__main__":
    main()
