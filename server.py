#!/usr/bin/env python3
"""
Maestro Frontend Server — serves knowledge_store data + live WebSocket updates.
Multi-project: each project dir becomes a route prefix (slug).

Usage:
    python server.py [--port 3000] [--store knowledge_store]

No database. No auth. Reads from filesystem, watches for changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import io
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
import uvicorn

# ── Config ──────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STORE = SCRIPT_DIR / "knowledge_store"
FRONTEND_DIR = SCRIPT_DIR / "frontend" / "dist"
THUMBNAIL_CACHE_DIR = ".cache"

# ── In-memory data ─────────────────────────────────────────────

projects: dict[str, dict[str, Any]] = {}  # slug -> project data
store_path: Path = DEFAULT_STORE
ws_clients: dict[str, set[WebSocket]] = {}  # slug -> clients


def slugify(name: str) -> str:
    """Convert project directory name to URL-safe slug."""
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def load_all_projects():
    """Load all project directories from knowledge_store."""
    global projects
    if not store_path.exists():
        return

    for project_dir in sorted(store_path.iterdir()):
        if not project_dir.is_dir():
            continue
        slug = slugify(project_dir.name)
        projects[slug] = load_project(project_dir, slug)
        ws_clients.setdefault(slug, set())

    for slug, proj in projects.items():
        page_count = len(proj.get("pages", {}))
        pointer_count = sum(len(p.get("pointers", {})) for p in proj.get("pages", {}).values())
        print(f"Loaded: {proj['name']} ({slug}) — {page_count} pages, {pointer_count} pointers")


def load_project(project_dir: Path, slug: str) -> dict[str, Any]:
    """Load a single project directory."""
    proj: dict[str, Any] = {
        "name": project_dir.name,
        "slug": slug,
        "path": str(project_dir),
        "pages": {},
    }

    pages_dir = project_dir / "pages"
    if pages_dir.exists():
        for page_dir in sorted(pages_dir.iterdir(), key=lambda p: p.name.lower()):
            if page_dir.is_dir():
                load_page(proj, page_dir)

    proj["disciplines"] = sorted({
        str(p.get("discipline", "General")).strip() or "General"
        for p in proj["pages"].values()
    })

    return proj


def load_page(proj: dict[str, Any], page_dir: Path) -> dict[str, Any] | None:
    """Load or reload a single page into a project."""
    page_name = page_dir.name
    pass1_path = page_dir / "pass1.json"

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

    if pass1_path.exists():
        try:
            with pass1_path.open("r", encoding="utf-8") as f:
                pass1 = json.load(f)
            if isinstance(pass1, dict):
                page["page_type"] = pass1.get("page_type", "unknown")
                page["discipline"] = pass1.get("discipline", "General") or "General"
                page["sheet_reflection"] = pass1.get("sheet_reflection", "")
                page["index"] = pass1.get("index", {}) if isinstance(pass1.get("index"), dict) else {}
                page["cross_references"] = pass1.get("cross_references", []) if isinstance(pass1.get("cross_references"), list) else []
                page["regions"] = pass1.get("regions", []) if isinstance(pass1.get("regions"), list) else []
                page["sheet_info"] = pass1.get("sheet_info", {})
        except Exception as e:
            print(f"Error loading {pass1_path}: {e}", file=sys.stderr)

    # Load pointers
    pointers_dir = page_dir / "pointers"
    if pointers_dir.exists():
        for pointer_dir in sorted(pointers_dir.iterdir(), key=lambda p: p.name.lower()):
            if not pointer_dir.is_dir():
                continue
            region_id = pointer_dir.name
            pass2_path = pointer_dir / "pass2.json"
            if pass2_path.exists():
                try:
                    with pass2_path.open("r", encoding="utf-8") as f:
                        pointer_data = json.load(f)
                    if not isinstance(pointer_data, dict):
                        pointer_data = {}
                    pointer_data.setdefault("content_markdown", "")
                    page["pointers"][region_id] = pointer_data
                except Exception:
                    pass

    proj["pages"][page_name] = page

    # Update disciplines
    proj["disciplines"] = sorted({
        str(p.get("discipline", "General")).strip() or "General"
        for p in proj["pages"].values()
    })

    return page


def _get_project(slug: str) -> dict[str, Any] | None:
    return projects.get(slug)


# ── Filesystem watcher ──────────────────────────────────────────

async def watch_knowledge_store():
    """Watch for file changes and push WebSocket events."""
    try:
        from watchfiles import awatch, Change
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

            # Path: knowledge_store/<project_dir>/pages/<page_name>/...
            parts = path.relative_to(store_path).parts
            if len(parts) < 2:
                continue

            project_dir_name = parts[0]
            slug = slugify(project_dir_name)
            proj = projects.get(slug)
            if not proj:
                continue

            # Workspace changes
            if len(parts) >= 3 and parts[1] == "workspaces":
                ws_slug = parts[2] if len(parts) > 2 else None
                await broadcast(slug, {"type": "workspace_updated", "slug": ws_slug})
                continue

            if len(parts) < 3 or parts[1] != "pages":
                continue

            page_name = parts[2]
            page_dir = store_path / parts[0] / "pages" / page_name

            if not page_dir.is_dir():
                continue

            load_page(proj, page_dir)

            if path.name == "pass1.json":
                event = {"type": "page_added", "page": page_name}
            elif path.name == "pass2.json" and len(parts) >= 5:
                region_id = parts[4]
                event = {"type": "region_complete", "page": page_name, "region": region_id}
            elif path.name == "page.png":
                event = {"type": "page_image_ready", "page": page_name}
            else:
                event = {"type": "page_updated", "page": page_name}

            await broadcast(slug, event)


async def broadcast(slug: str, event: dict):
    """Send event to all WebSocket clients for a project."""
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


# ── JPEG thumbnail generation ───────────────────────────────────

def get_thumbnail(page_dir: Path, width: int = 800, quality: int = 80) -> bytes | None:
    """Generate or return cached JPEG thumbnail."""
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
    if not ws_path.exists():
        return None
    try:
        with ws_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


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

app = FastAPI(title="Maestro", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def startup():
    load_all_projects()
    asyncio.create_task(watch_knowledge_store())


# ── Project listing (root) ──────────────────────────────────────

@app.get("/api/projects")
async def api_projects():
    """List all available projects."""
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


# ── Per-project API routes (/{slug}/api/...) ────────────────────

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
    """Serve a generated image from a workspace."""
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    img_path = _workspaces_dir(proj) / ws_slug / "generated_images" / filename
    if not img_path.exists() or not img_path.is_file():
        return JSONResponse({"error": "Image not found"}, status_code=404)
    # Determine media type
    suffix = img_path.suffix.lower()
    media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return FileResponse(img_path, media_type=media_type)


@app.get("/{slug}/api/workspaces/{ws_slug}/images/{filename}/thumb")
async def api_workspace_image_thumb(slug: str, ws_slug: str, filename: str, w: int = 800, q: int = 80):
    """Serve a thumbnail of a generated workspace image."""
    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    img_dir = _workspaces_dir(proj) / ws_slug / "generated_images"
    img_path = img_dir / filename
    if not img_path.exists():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    # Cache thumbnails
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
        page_name = page.get("page_name", "")
        selected = page.get("selected_pointers", [])
        enriched = {
            **page,
            "pointer_bboxes": _get_page_bboxes(proj, page_name, selected),
            "has_image": (Path(proj.get("pages", {}).get(page_name, {}).get("path", "")) / "page.png").exists()
                if proj.get("pages", {}).get(page_name, {}).get("path") else False,
        }
        enriched_pages.append(enriched)

    # Enrich generated images with has_file status
    generated_images = []
    for img in ws.get("generated_images", []):
        img_path = _workspaces_dir(proj) / ws_slug / "generated_images" / img.get("filename", "")
        generated_images.append({
            **img,
            "has_file": img_path.exists(),
        })

    return {**ws, "pages": enriched_pages, "generated_images": generated_images}


# ── WebSocket (per-project) ────────────────────────────────────

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


# ── Frontend SPA (served per-project) ───────────────────────────

@app.get("/assets/{rest:path}")
async def serve_static_assets(rest: str):
    """Serve built frontend assets at /assets/..."""
    if FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / "assets" / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)
    return JSONResponse({"error": "Not found"}, status_code=404)


@app.get("/{slug}/{rest:path}")
async def serve_frontend(slug: str, rest: str = ""):
    """Serve the frontend SPA for any project slug."""
    if slug in ("api", "ws"):
        return JSONResponse({"error": "Not found"}, status_code=404)

    proj = _get_project(slug)
    if not proj:
        return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)

    # Serve static assets if they exist
    if rest and FRONTEND_DIR.exists():
        asset_path = FRONTEND_DIR / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)

    # Serve index.html for SPA routing
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return JSONResponse({"error": "Frontend not built"}, status_code=404)


@app.get("/{slug}")
async def serve_frontend_root(slug: str):
    """Redirect bare slug to slug/."""
    return await serve_frontend(slug, "")


# ── Root ────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Root — list projects or redirect to single project."""
    if len(projects) == 1:
        slug = list(projects.keys())[0]
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=f"/{slug}/")
    return await api_projects()


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Maestro Frontend Server")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--store", type=str, default=str(DEFAULT_STORE))
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    store_path = Path(args.store).resolve()
    print(f"Maestro server starting on http://localhost:{args.port}")
    print(f"Knowledge store: {store_path}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
