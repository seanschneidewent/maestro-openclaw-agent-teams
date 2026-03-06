"""Command-center state refresh and node indexing helpers."""

from __future__ import annotations

import sys
from typing import Any, Callable

BuildCommandCenterStateFn = Callable[[Any], dict[str, Any]]
ApplyRegistryIdentityToStateFn = Callable[[dict[str, Any], dict[str, Any]], None]
LoadOpenClawConfigFn = Callable[[], dict[str, Any]]
BuildAwarenessStateFn = Callable[..., dict[str, Any]]
SyncFleetRegistryFn = Callable[[Any], dict[str, Any]]
RegistryBySlugFn = Callable[[dict[str, Any]], dict[str, dict[str, Any]]]
WorkspaceRoutePayloadFn = Callable[[str, dict[str, Any] | None], dict[str, str]]
SlugifyFn = Callable[[str], str]
StateIsStaleFn = Callable[[dict[str, Any], str, int], bool]
RefreshFn = Callable[[], None]


def openclaw_agents(config: dict[str, Any]) -> list[dict[str, Any]]:
    agents = config.get("agents") if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list") if isinstance(agents.get("list"), list) else []
    normalized: list[dict[str, Any]] = []
    for item in agent_list:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id", "")).strip()
        if not agent_id:
            continue
        normalized.append({
            "id": agent_id,
            "name": str(item.get("name", "")).strip(),
            "model": str(item.get("model", "")).strip(),
            "workspace": str(item.get("workspace", "")).strip(),
            "default": bool(item.get("default")),
        })
    return normalized


def agent_node_slug(agent_id: str, used_slugs: set[str], *, slugify_fn: SlugifyFn) -> str:
    clean_id = str(agent_id or "").strip()
    if clean_id.startswith("maestro-project-"):
        suffix = clean_id[len("maestro-project-"):].strip()
        candidate = slugify_fn(suffix or clean_id)
    else:
        candidate = f"agent-{slugify_fn(clean_id)}"
    if candidate not in used_slugs:
        return candidate
    idx = 2
    while True:
        fallback = f"{candidate}-{idx}"
        if fallback not in used_slugs:
            return fallback
        idx += 1


def merge_agent_nodes_into_command_center_state(
    state: dict[str, Any],
    openclaw_config: dict[str, Any],
    *,
    slugify_fn: SlugifyFn,
):
    projects_payload = state.get("projects") if isinstance(state, dict) else None
    if not isinstance(projects_payload, list):
        return

    for project in projects_payload:
        if not isinstance(project, dict):
            continue
        project.setdefault("node_type", "project")
        project.setdefault("has_project_store", True)

    agents = openclaw_agents(openclaw_config)
    if not agents:
        return

    existing_by_agent: dict[str, dict[str, Any]] = {}
    used_slugs: set[str] = set()
    for project in projects_payload:
        if not isinstance(project, dict):
            continue
        slug = str(project.get("slug", "")).strip()
        if slug:
            used_slugs.add(slug)
        agent_id = str(project.get("agent_id", "")).strip()
        if agent_id:
            existing_by_agent[agent_id] = project

    commander = state.get("commander") if isinstance(state.get("commander"), dict) else {}
    orchestrator = state.get("orchestrator") if isinstance(state.get("orchestrator"), dict) else {}

    for agent in agents:
        agent_id = str(agent.get("id", "")).strip()
        if not agent_id:
            continue

        if agent_id == "maestro-company":
            display = str(agent.get("name") or "").strip() or str(commander.get("name", "The Commander")).strip() or "The Commander"
            commander["name"] = display
            commander["agent_id"] = "maestro-company"
            if str(agent.get("model", "")).strip():
                commander["model"] = str(agent.get("model", "")).strip()
            if str(agent.get("workspace", "")).strip():
                commander["workspace"] = str(agent.get("workspace", "")).strip()
            orchestrator["name"] = display
            state["commander"] = commander
            state["orchestrator"] = orchestrator
            continue

        existing = existing_by_agent.get(agent_id)
        if isinstance(existing, dict):
            if str(agent.get("model", "")).strip():
                existing["model"] = str(agent.get("model", "")).strip()
            if str(agent.get("workspace", "")).strip():
                existing["workspace"] = str(agent.get("workspace", "")).strip()
            existing["is_default_agent"] = bool(agent.get("default"))
            existing["node_type"] = existing.get("node_type") or (
                "project" if agent_id.startswith("maestro-project-") else "specialist"
            )
            continue

        display_name = str(agent.get("name", "")).strip() or agent_id
        node_slug = agent_node_slug(agent_id, used_slugs, slugify_fn=slugify_fn)
        used_slugs.add(node_slug)
        node_type = "project" if agent_id.startswith("maestro-project-") else "specialist"
        projects_payload.append({
            "slug": node_slug,
            "project_name": display_name,
            "name": display_name,
            "agent_id": agent_id,
            "node_display_name": display_name,
            "node_handle": "",
            "node_identity_source": "openclaw_agent",
            "status": "unbound" if node_type == "project" else "active",
            "last_updated": "",
            "superintendent": "Unknown",
            "page_count": 0,
            "pointer_count": 0,
            "health": {"percent_complete": 0, "schedule_performance_index": 1.0, "variance_days": 0, "weather_delays": 0},
            "critical_path": {"critical_activity_count": 0, "upcoming_critical_count": 0, "blocker_count": 0, "top_blockers": []},
            "rfis": {"open": 0, "blocking_open": 0, "aging_over_14_days": 0},
            "submittals": {"pending_review": 0, "rejected": 0, "overdue_submissions": 0},
            "decisions": {"pending_change_orders": 0, "total_exposure_usd": 0, "high_risk_decisions": 0},
            "scope_risk": {"gaps": 0, "overlaps": 0},
            "agent_status": "idle",
            "current_task": "Awaiting Commander instructions.",
            "comms": "No project telemetry bound yet.",
            "attention_score": 0,
            "heartbeat": {"available": False, "is_fresh": False, "generated_at": "", "summary": "", "loop_state": "idle"},
            "status_report": {
                "source": "openclaw_config",
                "stale": True,
                "summary": "No project store bound yet." if node_type == "project" else "Registered specialist agent.",
                "loop_state": "idle",
                "confidence": 0.5,
                "pending_questions": 0,
                "top_risks": [],
                "next_actions": [],
                "metrics": {"attention_score": 0},
            },
            "conversation_preview": {
                "last_message_at": "",
                "last_user_at": "",
                "last_assistant_at": "",
                "last_user_text": "",
                "last_assistant_text": "",
                "message_count": 0,
            },
            "model": str(agent.get("model", "")).strip(),
            "workspace": str(agent.get("workspace", "")).strip(),
            "is_default_agent": bool(agent.get("default")),
            "node_type": node_type,
            "has_project_store": False,
        })


def gateway_ready_for_node_actions(awareness: dict[str, Any]) -> tuple[bool, str]:
    services = awareness.get("services") if isinstance(awareness.get("services"), dict) else {}
    openclaw = services.get("openclaw") if isinstance(services.get("openclaw"), dict) else {}
    if not bool(openclaw.get("running")):
        return False, "OpenClaw gateway is not running."
    gateway_auth = openclaw.get("gateway_auth") if isinstance(openclaw.get("gateway_auth"), dict) else {}
    if not bool(gateway_auth.get("tokens_aligned")):
        return False, "Gateway auth tokens are not aligned."
    pairing = openclaw.get("device_pairing") if isinstance(openclaw.get("device_pairing"), dict) else {}
    if bool(pairing.get("required")):
        return False, "CLI device pairing approval is required."
    return True, "Gateway reachable and node registered."


def apply_runtime_node_state(state: dict[str, Any], awareness: dict[str, Any]):
    commander = state.get("commander") if isinstance(state.get("commander"), dict) else {}
    projects_payload = state.get("projects") if isinstance(state.get("projects"), list) else []
    if not isinstance(projects_payload, list):
        projects_payload = []

    gateway_ready, gateway_reason = gateway_ready_for_node_actions(awareness)
    commander["online"] = bool(gateway_ready)
    commander["online_state"] = "online" if gateway_ready else "offline"
    commander["online_reason"] = gateway_reason
    commander["lastSeen"] = "Online" if gateway_ready else "Offline"
    state["commander"] = commander

    for node in projects_payload:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("node_type", "project")).strip().lower() or "project"
        has_store = bool(node.get("has_project_store", True))
        last_seen = (
            str(((node.get("conversation_preview") or {}).get("last_message_at", ""))).strip()
            or str(((node.get("heartbeat") or {}).get("generated_at", ""))).strip()
            or str(node.get("last_updated", "")).strip()
            or "—"
        )
        node["last_seen"] = last_seen

        if not gateway_ready:
            node["online"] = False
            node["online_state"] = "offline"
            node["online_reason"] = gateway_reason
            continue

        if node_type == "project" and not has_store:
            node["online"] = False
            node["online_state"] = "unbound"
            node["online_reason"] = "Agent exists, but no project store is bound yet."
            continue

        node["online"] = True
        node["online_state"] = "online"
        node["online_reason"] = "Reachable through Commander routing."


def build_command_center_node_index(command_center_state: dict[str, Any], *, commander_node_slug: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {
        commander_node_slug: {
            "agent_id": "maestro-company",
            "node_type": "commander",
            "has_project_store": False,
            "project_slug": commander_node_slug,
        }
    }
    projects_payload = command_center_state.get("projects") if isinstance(command_center_state, dict) else []
    if isinstance(projects_payload, list):
        for node in projects_payload:
            if not isinstance(node, dict):
                continue
            slug = str(node.get("slug", "")).strip()
            if not slug:
                continue
            agent_id = str(node.get("agent_id", "")).strip() or f"maestro-project-{slug}"
            has_store = bool(node.get("has_project_store", True))
            index[slug] = {
                "agent_id": agent_id,
                "node_type": str(node.get("node_type", "project")).strip() or "project",
                "has_project_store": has_store,
                "project_slug": slug if has_store else "",
            }
    return index


def refresh_command_center_state(
    *,
    store_path: Any,
    fleet_registry: dict[str, Any],
    awareness_state: dict[str, Any],
    commander_node_slug: str,
    build_command_center_state_fn: BuildCommandCenterStateFn,
    apply_registry_identity_to_state_fn: ApplyRegistryIdentityToStateFn,
    load_openclaw_config_fn: LoadOpenClawConfigFn,
    slugify_fn: SlugifyFn,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        command_center_state = build_command_center_state_fn(store_path)
        if fleet_registry:
            apply_registry_identity_to_state_fn(command_center_state, fleet_registry)
        merge_agent_nodes_into_command_center_state(
            command_center_state,
            load_openclaw_config_fn(),
            slugify_fn=slugify_fn,
        )
        if awareness_state:
            apply_runtime_node_state(command_center_state, awareness_state)
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
    return command_center_state, build_command_center_node_index(command_center_state, commander_node_slug=commander_node_slug)


def refresh_control_plane_state(
    *,
    store_path: Any,
    projects: dict[str, dict[str, Any]],
    command_center_state: dict[str, Any],
    server_port: int,
    commander_node_slug: str,
    sync_fleet_registry_fn: SyncFleetRegistryFn,
    registry_by_slug_fn: RegistryBySlugFn,
    workspace_route_payload_fn: WorkspaceRoutePayloadFn,
    apply_registry_identity_to_state_fn: ApplyRegistryIdentityToStateFn,
    build_awareness_state_fn: BuildAwarenessStateFn,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        fleet_registry = sync_fleet_registry_fn(store_path)
        by_slug = registry_by_slug_fn(fleet_registry)
        agent_project_slug_index: dict[str, str] = {}
        for slug in projects.keys():
            entry = by_slug.get(slug)
            routes = workspace_route_payload_fn(slug, entry)
            agent_project_slug_index[routes["agent_id"]] = slug
        if command_center_state:
            apply_registry_identity_to_state_fn(command_center_state, fleet_registry)
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
        awareness_state = build_awareness_state_fn(
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

    if command_center_state:
        apply_runtime_node_state(command_center_state, awareness_state)

    return (
        fleet_registry,
        awareness_state,
        agent_project_slug_index,
        command_center_state,
        build_command_center_node_index(command_center_state, commander_node_slug=commander_node_slug),
    )


def refresh_all_state(*, load_all_projects_fn: RefreshFn, refresh_command_center_state_fn: RefreshFn, refresh_control_plane_state_fn: RefreshFn):
    load_all_projects_fn()
    refresh_command_center_state_fn()
    refresh_control_plane_state_fn()


def ensure_command_center_state(
    *,
    command_center_state: dict[str, Any],
    awareness_state: dict[str, Any],
    state_refresh_ttl_seconds: int,
    state_is_stale_fn: StateIsStaleFn,
    refresh_command_center_state_fn: RefreshFn,
) -> bool:
    refreshed = False
    if state_is_stale_fn(command_center_state, "updated_at", state_refresh_ttl_seconds):
        refresh_command_center_state_fn()
        refreshed = True
    if command_center_state and awareness_state and (refreshed or not state_is_stale_fn(awareness_state, "generated_at", state_refresh_ttl_seconds)):
        apply_runtime_node_state(command_center_state, awareness_state)
    return refreshed


def ensure_awareness_state(
    *,
    awareness_state: dict[str, Any],
    command_center_state: dict[str, Any],
    state_refresh_ttl_seconds: int,
    state_is_stale_fn: StateIsStaleFn,
    refresh_control_plane_state_fn: RefreshFn,
) -> None:
    if state_is_stale_fn(awareness_state, "generated_at", state_refresh_ttl_seconds):
        refresh_control_plane_state_fn()
    elif command_center_state and awareness_state:
        apply_runtime_node_state(command_center_state, awareness_state)


def ensure_fleet_registry(*, fleet_registry: dict[str, Any], refresh_control_plane_state_fn: RefreshFn) -> None:
    if not fleet_registry:
        refresh_control_plane_state_fn()


def resolve_agent_slug(agent_id: str, *, agent_project_slug_index: dict[str, str], projects: dict[str, dict[str, Any]]) -> str | None:
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
