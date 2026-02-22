"""Command-center action execution helpers for the FastAPI server."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from .control_plane import (
    create_project_node,
    move_project_store,
    onboard_project_store,
    project_control_payload,
    register_project_agent,
)
from .system_directives import (
    archive_system_directive,
    list_system_directives,
    upsert_system_directive,
)


class ActionError(Exception):
    """Structured action error raised by command-center action handlers."""

    def __init__(self, status_code: int, payload: dict[str, Any]):
        super().__init__(payload.get("error", "Command-center action failed"))
        self.status_code = int(status_code)
        self.payload = payload


DoctorBuilder = Callable[..., dict[str, Any]]
StateGetter = Callable[[], dict[str, Any]]
RefreshFn = Callable[[], None]
BroadcastFn = Callable[[], Awaitable[None]]


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "y", "on"):
            return True
        if lowered in ("0", "false", "no", "n", "off"):
            return False
    return default


async def run_command_center_action(
    payload: dict[str, Any],
    *,
    store_path: Path,
    refresh_all_state: RefreshFn,
    broadcast_command_center_update: BroadcastFn,
    get_fleet_registry: StateGetter,
    get_awareness_state: StateGetter,
    doctor_builder: DoctorBuilder,
) -> dict[str, Any]:
    """Execute a command-center action payload and return response payload."""
    action = str(payload.get("action", "")).strip().lower()
    if not action:
        raise ActionError(400, {"error": "Missing action"})

    if action == "sync_registry":
        refresh_all_state()
        await broadcast_command_center_update()
        return {"ok": True, "registry": get_fleet_registry()}

    if action == "doctor_fix":
        try:
            report = doctor_builder(
                fix=_to_bool(payload.get("fix"), default=True),
                store_override=str(store_path),
                restart_gateway=_to_bool(payload.get("restart_gateway"), default=True),
            )
        except Exception as exc:
            raise ActionError(500, {"error": f"Doctor action failed: {exc}"}) from exc

        refresh_all_state()
        await broadcast_command_center_update()
        return {
            "ok": bool(report.get("ok")),
            "doctor": report,
            "awareness": get_awareness_state(),
        }

    if action == "list_system_directives":
        include_archived = _to_bool(payload.get("include_archived"), default=False)
        directives = list_system_directives(store_path, include_archived=include_archived)
        return {
            "ok": True,
            "directives": directives,
            "count": len(directives),
        }

    if action == "upsert_system_directive":
        directive = payload.get("directive")
        if not isinstance(directive, dict):
            raise ActionError(400, {"error": "Missing directive object"})
        result = upsert_system_directive(
            store_path,
            directive,
            updated_by=str(payload.get("updated_by", "command_center")),
        )
        refresh_all_state()
        await broadcast_command_center_update()
        return result

    if action == "archive_system_directive":
        directive_id = str(payload.get("directive_id", "")).strip()
        if not directive_id:
            raise ActionError(400, {"error": "Missing directive_id"})
        result = archive_system_directive(
            store_path,
            directive_id,
            updated_by=str(payload.get("updated_by", "command_center")),
        )
        if not result.get("ok"):
            raise ActionError(404, result)
        refresh_all_state()
        await broadcast_command_center_update()
        return result

    if action == "create_project_node":
        project_name = str(payload.get("project_name", "")).strip()
        if not project_name:
            raise ActionError(400, {"error": "Missing project_name"})

        result = create_project_node(
            store_path,
            project_name=project_name,
            project_slug=str(payload.get("project_slug", "")).strip() or None,
            project_dir_name=str(payload.get("project_dir_name", "")).strip() or None,
            ingest_input_root=str(payload.get("ingest_input_root", "")).strip() or None,
            superintendent=str(payload.get("superintendent", "")).strip() or None,
            assignee=str(payload.get("assignee", "")).strip() or None,
            register_agent=_to_bool(payload.get("register_agent"), default=False),
            agent_model=str(payload.get("agent_model", "")).strip() or None,
            dry_run=_to_bool(payload.get("dry_run"), default=False),
        )
        refresh_all_state()
        await broadcast_command_center_update()
        return result

    if action == "onboard_project_store":
        source_path = str(payload.get("source_path", "")).strip()
        if not source_path:
            raise ActionError(400, {"error": "Missing source_path"})

        result = onboard_project_store(
            store_root=store_path,
            source_path=source_path,
            project_name=str(payload.get("project_name", "")).strip() or None,
            project_slug=str(payload.get("project_slug", "")).strip() or None,
            project_dir_name=str(payload.get("project_dir_name", "")).strip() or None,
            ingest_input_root=str(payload.get("ingest_input_root", "")).strip() or None,
            superintendent=str(payload.get("superintendent", "")).strip() or None,
            assignee=str(payload.get("assignee", "")).strip() or None,
            register_agent=_to_bool(payload.get("register_agent"), default=True),
            move_source=_to_bool(payload.get("move_source"), default=True),
            agent_model=str(payload.get("agent_model", "")).strip() or None,
            dry_run=_to_bool(payload.get("dry_run"), default=False),
        )
        if not result.get("ok"):
            raise ActionError(400, result)

        refresh_all_state()
        await broadcast_command_center_update()
        return result

    if action in ("ingest_command", "preflight_ingest", "index_command"):
        project_slug = str(payload.get("project_slug", "")).strip()
        if not project_slug:
            raise ActionError(400, {"error": "Missing project_slug"})
        control = project_control_payload(
            store_path,
            project_slug=project_slug,
            input_root_override=str(payload.get("input_root", "")).strip() or None,
            dpi=int(payload.get("dpi", 200)),
        )
        if not control.get("ok"):
            raise ActionError(404, {"error": control.get("error", "Project not found")})
        if action == "ingest_command":
            return {
                "ok": True,
                "project": control.get("project"),
                "workspace": control.get("workspace"),
                "ingest": control.get("ingest"),
                "preflight": control.get("preflight"),
            }
        if action == "preflight_ingest":
            return {
                "ok": True,
                "project": control.get("project"),
                "workspace": control.get("workspace"),
                "preflight": control.get("preflight"),
            }
        return {
            "ok": True,
            "project": control.get("project"),
            "workspace": control.get("workspace"),
            "index_command": control.get("index_command"),
        }

    if action == "move_project_store":
        project_slug = str(payload.get("project_slug", "")).strip()
        new_dir_name = str(payload.get("new_dir_name", "")).strip()
        if not project_slug or not new_dir_name:
            raise ActionError(400, {"error": "Missing project_slug or new_dir_name"})

        dry_run = _to_bool(payload.get("dry_run"), default=True)
        result = move_project_store(
            store_root=store_path,
            project_slug=project_slug,
            new_dir_name=new_dir_name,
            dry_run=dry_run,
        )
        if not result.get("ok"):
            raise ActionError(400, result)
        if not dry_run:
            refresh_all_state()
            await broadcast_command_center_update()
        return result

    if action == "register_project_agent":
        project_slug = str(payload.get("project_slug", "")).strip()
        if not project_slug:
            raise ActionError(400, {"error": "Missing project_slug"})
        control = project_control_payload(store_path, project_slug=project_slug)
        if not control.get("ok"):
            raise ActionError(404, {"error": control.get("error", "Project not found")})
        project = control.get("project", {}) if isinstance(control.get("project"), dict) else {}
        registration = register_project_agent(
            store_root=store_path,
            project_slug=project_slug,
            project_name=str(project.get("project_name", project_slug)),
            project_store_path=str(project.get("project_store_path", "")),
            dry_run=_to_bool(payload.get("dry_run"), default=False),
            model=str(payload.get("agent_model", "")).strip() or None,
        )
        refresh_all_state()
        await broadcast_command_center_update()
        return registration

    raise ActionError(400, {"error": f"Unsupported action: {action}"})
