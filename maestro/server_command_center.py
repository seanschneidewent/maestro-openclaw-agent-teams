"""Command-center API/WebSocket/static routes.

This module isolates command-center specific endpoints from the broader
workspace server routes in ``server.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from .server_actions import ActionError

EnsureFn = Callable[[], None]
StateGetter = Callable[[], dict[str, Any]]
ProjectDetailLoader = Callable[[str], dict[str, Any]]
ProjectStatusLoader = Callable[[str], dict[str, Any]]
ConversationReader = Callable[[str, int, str | None], dict[str, Any]]
ConversationSender = Callable[[str, str, str], dict[str, Any]]
ActionRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class CommandCenterRouterContext:
    """Dependencies required to serve command-center routes."""

    command_center_dir: Path
    command_center_ws_clients: set[WebSocket]
    ensure_command_center_state: EnsureFn
    ensure_awareness_state: EnsureFn
    ensure_fleet_registry: EnsureFn
    get_command_center_state: StateGetter
    get_awareness_state: StateGetter
    get_fleet_registry: StateGetter
    load_project_detail: ProjectDetailLoader
    load_project_status: ProjectStatusLoader
    read_node_conversation: ConversationReader
    send_node_message: ConversationSender
    run_action: ActionRunner


def create_command_center_router(ctx: CommandCenterRouterContext) -> APIRouter:
    """Build an APIRouter containing command-center endpoints."""
    router = APIRouter()

    def _command_center_index_path() -> Path:
        return ctx.command_center_dir / "index.html"

    @router.get("/api/command-center/state")
    async def api_command_center_state():
        ctx.ensure_command_center_state()
        ctx.ensure_awareness_state()
        return ctx.get_command_center_state()

    @router.get("/api/command-center/projects/{slug}")
    async def api_command_center_project_detail(slug: str):
        try:
            return ctx.load_project_detail(slug)
        except KeyError:
            return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)
        except Exception as exc:  # pragma: no cover - defensive API boundary
            return JSONResponse({"error": f"Failed to build project detail: {exc}"}, status_code=500)

    @router.get("/api/command-center/nodes/{slug}/status")
    async def api_command_center_node_status(slug: str):
        try:
            return ctx.load_project_status(slug)
        except KeyError:
            return JSONResponse({"error": f"Node '{slug}' not found"}, status_code=404)
        except Exception as exc:  # pragma: no cover - defensive API boundary
            return JSONResponse({"error": f"Failed to load node status: {exc}"}, status_code=500)

    @router.get("/api/command-center/nodes/{slug}/conversation")
    async def api_command_center_node_conversation(slug: str, limit: int = 100, before: str | None = None):
        try:
            return ctx.read_node_conversation(slug, int(limit), before)
        except KeyError:
            return JSONResponse({"error": f"Node '{slug}' not found"}, status_code=404)
        except Exception as exc:  # pragma: no cover - defensive API boundary
            return JSONResponse({"error": f"Failed to load node conversation: {exc}"}, status_code=500)

    @router.post("/api/command-center/nodes/{slug}/conversation/send")
    async def api_command_center_node_send(slug: str, payload: dict[str, Any]):
        message = str(payload.get("message", "")).strip()
        source = str(payload.get("source", "")).strip() or "unknown"
        try:
            return ctx.send_node_message(slug, message, source)
        except KeyError:
            return JSONResponse({"error": f"Node '{slug}' not found"}, status_code=404)
        except ActionError as exc:
            return JSONResponse(exc.payload, status_code=exc.status_code)
        except Exception as exc:  # pragma: no cover - defensive API boundary
            return JSONResponse({"error": f"Failed to send message: {exc}"}, status_code=500)

    @router.get("/api/system/awareness")
    async def api_system_awareness():
        ctx.ensure_awareness_state()
        return ctx.get_awareness_state()

    @router.get("/api/command-center/fleet-registry")
    async def api_fleet_registry():
        ctx.ensure_fleet_registry()
        return ctx.get_fleet_registry()

    @router.post("/api/command-center/actions")
    async def api_command_center_actions(payload: dict[str, Any]):
        try:
            return await ctx.run_action(payload)
        except ActionError as exc:
            return JSONResponse(exc.payload, status_code=exc.status_code)

    @router.websocket("/ws/command-center")
    async def websocket_command_center(websocket: WebSocket):
        await websocket.accept()
        ctx.command_center_ws_clients.add(websocket)
        try:
            ctx.ensure_command_center_state()
            ctx.ensure_awareness_state()
            await websocket.send_text(json.dumps({
                "type": "command_center_init",
                "state": ctx.get_command_center_state(),
                "awareness": ctx.get_awareness_state(),
            }))
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ctx.command_center_ws_clients.discard(websocket)

    @router.get("/command-center")
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

    @router.get("/command-center/assets/{rest:path}")
    async def command_center_assets(rest: str):
        asset_path = ctx.command_center_dir / "assets" / rest
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)
        return JSONResponse({"error": "Not found"}, status_code=404)

    @router.get("/command-center/{rest:path}")
    async def command_center_spa(rest: str):
        if rest.startswith("api/") or rest.startswith("ws/"):
            return JSONResponse({"error": "Not found"}, status_code=404)

        file_path = ctx.command_center_dir / rest
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

        index_path = _command_center_index_path()
        if index_path.exists():
            return FileResponse(index_path)
        return JSONResponse({"error": "Command Center frontend not found"}, status_code=404)

    return router
