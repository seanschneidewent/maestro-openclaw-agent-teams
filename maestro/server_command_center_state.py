"""Command-center node/identity helpers extracted from ``server.py``.

The functions here are intentionally framework-agnostic and accept explicit
dependencies so API behavior can stay stable while server module boundaries
remain clean.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .server_actions import ActionError

ResolveNodeIdentityFn = Callable[[dict[str, Any]], tuple[str, str, str]]
ConversationPreviewFn = Callable[[str, str], dict[str, Any]]
DiscoverProjectDirsFn = Callable[[Path], list[Path]]
BuildSnapshotFn = Callable[[Path], dict[str, Any]]
BuildProjectDetailFn = Callable[[Path], dict[str, Any]]
EnsureFn = Callable[[], None]
ApplyRegistryIdentityFn = Callable[[dict[str, Any], dict[str, Any] | None], None]
ReadConversationFn = Callable[..., dict[str, Any]]
SendMessageFn = Callable[..., dict[str, Any]]
RegistryEntryGetterFn = Callable[[str], dict[str, Any] | None]
SaveFleetRegistryFn = Callable[[Path, dict[str, Any]], None]
ProjectDetailLoaderFn = Callable[[str], dict[str, Any]]
NodeAgentIdForSlugFn = Callable[[str], str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def registry_by_slug(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    by_slug: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("project_slug", "")).strip()
        if slug:
            by_slug[slug] = item
    return by_slug


def workspace_route_payload(slug: str, entry: dict[str, Any] | None = None) -> dict[str, str]:
    reg_entry = entry if isinstance(entry, dict) else {}
    agent_id = str(reg_entry.get("maestro_agent_id", "")).strip() or f"maestro-project-{slug}"
    return {
        "project_slug": slug,
        "agent_id": agent_id,
        "project_workspace_url": f"/{quote(slug)}/",
        "agent_workspace_url": f"/agents/{quote(agent_id, safe='')}/workspace/",
    }


def apply_registry_identity(
    snapshot: dict[str, Any],
    entry: dict[str, Any] | None,
    *,
    resolve_node_identity_fn: ResolveNodeIdentityFn,
    conversation_preview_builder: ConversationPreviewFn,
):
    if not isinstance(snapshot, dict):
        return

    slug = str(snapshot.get("slug", "")).strip()
    snapshot.update(workspace_route_payload(slug, entry))
    snapshot["project_name"] = str(snapshot.get("project_name") or snapshot.get("name") or slug)

    if not isinstance(entry, dict):
        default_agent_id = f"maestro-project-{slug}" if slug else ""
        snapshot.setdefault("agent_id", default_agent_id)
        snapshot.setdefault("node_display_name", snapshot.get("project_name") or slug)
        snapshot.setdefault("node_handle", "")
        snapshot.setdefault("node_identity_source", "project")
        snapshot["conversation_preview"] = conversation_preview_builder(default_agent_id, slug)
        return

    assignee = str(entry.get("assignee", "")).strip()
    superintendent = str(entry.get("superintendent", "")).strip()
    agent_id = str(entry.get("maestro_agent_id", "")).strip() or f"maestro-project-{slug}"

    if superintendent.lower() in ("", "unknown") and assignee.lower() not in ("", "unassigned"):
        superintendent = assignee

    if assignee:
        snapshot["assignee"] = assignee
    if superintendent:
        snapshot["superintendent"] = superintendent
    snapshot["agent_id"] = agent_id

    node_display_name, source, node_handle = resolve_node_identity_fn(entry)
    snapshot["node_display_name"] = node_display_name
    snapshot["node_identity_source"] = source
    snapshot["node_handle"] = node_handle
    snapshot["conversation_preview"] = conversation_preview_builder(agent_id, slug)


def apply_registry_identity_to_command_center_state(
    state: dict[str, Any],
    registry: dict[str, Any],
    *,
    apply_registry_identity_fn: ApplyRegistryIdentityFn,
):
    if not isinstance(state, dict):
        return
    projects_payload = state.get("projects")
    if not isinstance(projects_payload, list):
        return

    by_slug = registry_by_slug(registry)
    for project in projects_payload:
        if not isinstance(project, dict):
            continue
        slug = str(project.get("slug", "")).strip()
        if not slug:
            continue
        apply_registry_identity_fn(project, by_slug.get(slug))


def command_center_project_dirs_by_slug(
    store_path: Path,
    *,
    discover_project_dirs_fn: DiscoverProjectDirsFn,
    build_project_snapshot_fn: BuildSnapshotFn,
) -> dict[str, Path]:
    """Index discoverable project directories by normalized slug."""
    result: dict[str, Path] = {}
    for project_dir in discover_project_dirs_fn(store_path):
        try:
            snapshot = build_project_snapshot_fn(project_dir)
            slug = snapshot.get("slug")
            if isinstance(slug, str) and slug:
                result[slug] = project_dir
        except Exception:
            continue
    return result


def load_command_center_project_detail(
    slug: str,
    *,
    store_path: Path,
    fleet_registry: dict[str, Any],
    ensure_fleet_registry: EnsureFn,
    discover_project_dirs_fn: DiscoverProjectDirsFn,
    build_project_snapshot_fn: BuildSnapshotFn,
    build_project_detail_fn: BuildProjectDetailFn,
    apply_registry_identity_fn: ApplyRegistryIdentityFn,
) -> dict[str, Any]:
    project_dirs = command_center_project_dirs_by_slug(
        store_path,
        discover_project_dirs_fn=discover_project_dirs_fn,
        build_project_snapshot_fn=build_project_snapshot_fn,
    )
    project_dir = project_dirs.get(slug)
    if not project_dir:
        raise KeyError(slug)

    detail = build_project_detail_fn(project_dir)
    ensure_fleet_registry()
    snapshot = detail.get("snapshot")
    if isinstance(snapshot, dict):
        entry = registry_by_slug(fleet_registry).get(slug)
        apply_registry_identity_fn(snapshot, entry)
    return detail


def registry_entry_for_slug(
    slug: str,
    *,
    fleet_registry: dict[str, Any],
    ensure_fleet_registry: EnsureFn,
) -> dict[str, Any] | None:
    ensure_fleet_registry()
    return registry_by_slug(fleet_registry).get(slug)


def node_agent_id_for_slug(slug: str, *, entry: dict[str, Any] | None) -> str:
    if isinstance(entry, dict):
        agent_id = str(entry.get("maestro_agent_id", "")).strip()
        if agent_id:
            return agent_id
    return f"maestro-project-{slug}"


def load_command_center_node_status(
    slug: str,
    *,
    commander_node_slug: str,
    awareness_state: dict[str, Any],
    command_center_state: dict[str, Any],
    ensure_awareness_state: EnsureFn,
    load_project_detail_fn: ProjectDetailLoaderFn,
    node_agent_id_for_slug_fn: NodeAgentIdForSlugFn,
) -> dict[str, Any]:
    if slug == commander_node_slug:
        ensure_awareness_state()
        commander = awareness_state.get("commander", {}) if isinstance(awareness_state, dict) else {}
        display_name = str(commander.get("display_name", "")).strip() or "The Commander"
        action = (
            str(command_center_state.get("orchestrator", {}).get("currentAction", "")).strip()
            if isinstance(command_center_state, dict)
            else ""
        )
        posture = str(awareness_state.get("posture", "")).strip() if isinstance(awareness_state, dict) else ""
        status_report = {
            "source": "computed",
            "stale": False,
            "summary": action or "Monitoring fleet telemetry.",
            "loop_state": "idle",
            "confidence": 1.0,
            "pending_questions": 0,
            "top_risks": [],
            "next_actions": ["Coordinate project maestros", "Monitor system directives"],
            "metrics": {
                "attention_score": 0,
                "spi": 1.0,
                "variance_days": 0,
                "blocker_count": 0,
                "open_rfis": 0,
                "rejected_submittals": 0,
                "pending_change_orders": 0,
                "scope_gaps": 0,
            },
        }
        return {
            "ok": True,
            "project_slug": commander_node_slug,
            "agent_id": str(commander.get("agent_id", "maestro-company")).strip() or "maestro-company",
            "project_name": "Command Center Control Plane",
            "node_display_name": display_name,
            "status_report": status_report,
            "heartbeat": {
                "available": True,
                "is_fresh": True,
                "generated_at": str(awareness_state.get("generated_at", "")),
                "summary": f"System posture: {posture or 'unknown'}",
                "loop_state": "idle",
            },
            "snapshot": {
                "slug": commander_node_slug,
                "name": display_name,
                "project_name": "Command Center Control Plane",
                "node_display_name": display_name,
                "agent_id": "maestro-company",
                "status": "active",
                "last_updated": str(awareness_state.get("generated_at", "")),
            },
        }

    detail = load_project_detail_fn(slug)
    snapshot = detail.get("snapshot") if isinstance(detail.get("snapshot"), dict) else {}
    heartbeat = snapshot.get("heartbeat") if isinstance(snapshot.get("heartbeat"), dict) else {}
    status_report = snapshot.get("status_report") if isinstance(snapshot.get("status_report"), dict) else {}
    return {
        "ok": True,
        "project_slug": slug,
        "agent_id": str(snapshot.get("agent_id", node_agent_id_for_slug_fn(slug))),
        "project_name": str(snapshot.get("project_name", snapshot.get("name", slug))),
        "node_display_name": str(snapshot.get("node_display_name", "")),
        "status_report": status_report,
        "heartbeat": heartbeat,
        "snapshot": snapshot,
    }


def load_node_conversation(
    slug: str,
    *,
    commander_node_slug: str,
    projects: dict[str, dict[str, Any]],
    node_agent_id_for_slug_fn: NodeAgentIdForSlugFn,
    read_agent_conversation_fn: ReadConversationFn,
    limit: int = 100,
    before: str | None = None,
) -> dict[str, Any]:
    clamped_limit = max(1, min(int(limit), 500))
    if slug == commander_node_slug:
        payload = read_agent_conversation_fn(
            "maestro-company",
            limit=clamped_limit,
            before=before,
            project_slug=commander_node_slug,
        )
        payload["project_slug"] = commander_node_slug
        payload["agent_id"] = "maestro-company"
        return payload

    if slug not in projects:
        raise KeyError(slug)
    agent_id = node_agent_id_for_slug_fn(slug)
    payload = read_agent_conversation_fn(
        agent_id,
        limit=clamped_limit,
        before=before,
        project_slug=slug,
    )
    payload["project_slug"] = slug
    payload["agent_id"] = agent_id
    return payload


def send_node_message(
    slug: str,
    message: str,
    source: str,
    *,
    commander_node_slug: str,
    projects: dict[str, dict[str, Any]],
    store_path: Path,
    fleet_registry: dict[str, Any],
    registry_entry_for_slug_fn: RegistryEntryGetterFn,
    send_agent_message_fn: SendMessageFn,
    save_fleet_registry_fn: SaveFleetRegistryFn,
    max_message_chars: int,
) -> dict[str, Any]:
    if slug == commander_node_slug:
        raise ActionError(403, {"error": "Conversation send is restricted to project agents"})

    if slug not in projects:
        raise KeyError(slug)
    clean_message = str(message or "").strip()
    if not clean_message:
        raise ActionError(400, {"error": "Message is required"})
    if len(clean_message) > max_message_chars:
        raise ActionError(400, {"error": f"Message too long (max {max_message_chars} chars)"})

    clean_source = str(source or "").strip().lower()
    if clean_source != "command_center_ui":
        raise ActionError(400, {"error": "Manual send requires source=command_center_ui"})

    entry = registry_entry_for_slug_fn(slug)
    if not isinstance(entry, dict):
        raise KeyError(slug)
    if str(entry.get("status", "active")).strip().lower() == "archived":
        raise ActionError(404, {"error": f"Node '{slug}' is archived"})

    agent_id = str(entry.get("maestro_agent_id", "")).strip() or f"maestro-project-{slug}"
    if not agent_id.startswith("maestro-project-"):
        raise ActionError(403, {"error": "Conversation send is restricted to project agents"})

    result = send_agent_message_fn(
        agent_id=agent_id,
        message=clean_message,
        project_slug=slug,
        session_id=f"agent:{agent_id}:main",
    )
    if not bool(result.get("ok")):
        status_code = int(result.get("status_code", 503))
        raise ActionError(status_code, {"error": str(result.get("error", "Agent send failed"))})

    convo = result.get("conversation")
    if isinstance(convo, dict):
        messages = convo.get("messages")
        if isinstance(messages, list) and messages:
            last_msg = messages[-1] if isinstance(messages[-1], dict) else {}
            ts = str(last_msg.get("timestamp", "")).strip()
            if ts:
                entry["last_conversation_at"] = ts
                save_fleet_registry_fn(store_path, {
                    "version": int(fleet_registry.get("version", 1)),
                    "updated_at": _now_iso(),
                    "store_root": str(store_path.resolve()),
                    "projects": fleet_registry.get("projects", []),
                })

    return {
        "ok": True,
        "project_slug": slug,
        "agent_id": agent_id,
        "source": "openclaw_agent_invoke",
        "conversation": result.get("conversation", {}),
        "result": result.get("result", {}),
    }
