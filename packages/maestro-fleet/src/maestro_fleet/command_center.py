"""Fleet-derived Command Center state for the package-native server path."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maestro.command_center import build_command_center_state, build_project_snapshot, discover_project_dirs
import maestro.control_plane_core as legacy_control_plane
from maestro.fleet.projects import registry as legacy_registry
from maestro.system_directives import summarize_system_directives

from .openclaw_runtime import DEFAULT_FLEET_OPENCLAW_PROFILE, openclaw_config_path
from .runtime import resolve_network_urls
from .state import (
    load_openclaw_config,
    openclaw_agents,
    resolve_workspace_project_slug,
    resolve_workspace_role,
    resolve_workspace_store,
)

_AVAILABLE_ACTIONS = [
    "sync_registry",
    "list_system_directives",
    "upsert_system_directive",
    "archive_system_directive",
    "create_project_node",
    "onboard_project_store",
    "ingest_command",
    "preflight_ingest",
    "index_command",
    "move_project_store",
    "register_project_agent",
    "doctor_fix",
    "conversation_read",
    "conversation_send",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return payload


def _invoke_runner(runner: Any, args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        return runner(args, timeout)
    except TypeError:
        return runner(args)  # type: ignore[misc]


def _resolve_company_agent(config: dict[str, Any]) -> dict[str, Any]:
    for agent in openclaw_agents(config):
        if _clean(agent.get("id")) == "maestro-company":
            return agent
    for agent in openclaw_agents(config):
        if bool(agent.get("default")):
            return agent
    agents = openclaw_agents(config)
    return agents[0] if agents else {}


def _workspace_path(agent: dict[str, Any]) -> Path | None:
    raw = _clean(agent.get("workspace"))
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _project_agent_bindings(config: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for agent in openclaw_agents(config):
        agent_id = _clean(agent.get("id"))
        workspace = _workspace_path(agent)
        workspace_store = resolve_workspace_store(workspace)
        project_slug = resolve_workspace_project_slug(workspace)
        role = resolve_workspace_role(workspace)
        bindings.append({
            "id": agent_id,
            "name": _clean(agent.get("name")),
            "model": _clean(agent.get("model")),
            "default": bool(agent.get("default")),
            "workspace": _clean(agent.get("workspace")),
            "workspace_path": workspace,
            "workspace_store": workspace_store,
            "project_slug": project_slug,
            "role": role,
        })
    return bindings


def _agent_node_slug(agent_id: str, used_slugs: set[str], *, slugify_fn: Any) -> str:
    clean_id = _clean(agent_id)
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


def _merge_agent_nodes_into_command_center_state(
    state: dict[str, Any],
    openclaw_config: dict[str, Any],
    *,
    slugify_fn: Any,
) -> None:
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
        slug = _clean(project.get("slug"))
        if slug:
            used_slugs.add(slug)
        agent_id = _clean(project.get("agent_id"))
        if agent_id:
            existing_by_agent[agent_id] = project

    commander = state.get("commander") if isinstance(state.get("commander"), dict) else {}
    orchestrator = state.get("orchestrator") if isinstance(state.get("orchestrator"), dict) else {}

    for agent in agents:
        agent_id = _clean(agent.get("id"))
        if not agent_id:
            continue

        if agent_id == "maestro-company":
            display = _clean(agent.get("name")) or _clean(commander.get("name")) or "The Commander"
            commander["name"] = display
            commander["agent_id"] = "maestro-company"
            if _clean(agent.get("model")):
                commander["model"] = _clean(agent.get("model"))
            if _clean(agent.get("workspace")):
                commander["workspace"] = _clean(agent.get("workspace"))
            orchestrator["name"] = display
            state["commander"] = commander
            state["orchestrator"] = orchestrator
            continue

        existing = existing_by_agent.get(agent_id)
        if isinstance(existing, dict):
            if _clean(agent.get("model")):
                existing["model"] = _clean(agent.get("model"))
            if _clean(agent.get("workspace")):
                existing["workspace"] = _clean(agent.get("workspace"))
            existing["is_default_agent"] = bool(agent.get("default"))
            existing["node_type"] = existing.get("node_type") or (
                "project" if agent_id.startswith("maestro-project-") else "specialist"
            )
            continue

        display_name = _clean(agent.get("name")) or agent_id
        node_slug = _agent_node_slug(agent_id, used_slugs, slugify_fn=slugify_fn)
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
            "model": _clean(agent.get("model")),
            "workspace": _clean(agent.get("workspace")),
            "is_default_agent": bool(agent.get("default")),
            "node_type": node_type,
            "has_project_store": False,
        })


def _gateway_ready_for_node_actions(awareness: dict[str, Any]) -> tuple[bool, str]:
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


def _apply_runtime_node_state(state: dict[str, Any], awareness: dict[str, Any]) -> None:
    commander = state.get("commander") if isinstance(state.get("commander"), dict) else {}
    projects_payload = state.get("projects") if isinstance(state.get("projects"), list) else []
    if not isinstance(projects_payload, list):
        projects_payload = []

    gateway_ready, gateway_reason = _gateway_ready_for_node_actions(awareness)
    commander["online"] = bool(gateway_ready)
    commander["online_state"] = "online" if gateway_ready else "offline"
    commander["online_reason"] = gateway_reason
    commander["lastSeen"] = "Online" if gateway_ready else "Offline"
    state["commander"] = commander

    for node in projects_payload:
        if not isinstance(node, dict):
            continue
        node_type = _clean(node.get("node_type")).lower() or "project"
        has_store = bool(node.get("has_project_store", True))
        last_seen = (
            _clean(((node.get("conversation_preview") or {}).get("last_message_at")))
            or _clean(((node.get("heartbeat") or {}).get("generated_at")))
            or _clean(node.get("last_updated"))
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


def _build_command_center_node_index(
    command_center_state: dict[str, Any],
    *,
    commander_node_slug: str,
) -> dict[str, dict[str, Any]]:
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
            slug = _clean(node.get("slug"))
            if not slug:
                continue
            agent_id = _clean(node.get("agent_id")) or f"maestro-project-{slug}"
            has_store = bool(node.get("has_project_store", True))
            index[slug] = {
                "agent_id": agent_id,
                "node_type": _clean(node.get("node_type")) or "project",
                "has_project_store": has_store,
                "project_slug": slug if has_store else "",
            }
    return index


def _server_openclaw_config(server_module: Any) -> dict[str, Any]:
    loader = getattr(server_module, "_load_openclaw_config_for_command_center", None)
    if callable(loader):
        try:
            payload = loader()
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            return payload
    return load_openclaw_config()


def _matching_binding(bindings: list[dict[str, Any]], slug: str, project_dir: Path) -> dict[str, Any] | None:
    project_path = project_dir.resolve()
    preferred_id = f"maestro-project-{slug}"

    for binding in bindings:
        if _clean(binding.get("id")) == preferred_id:
            return binding
    for binding in bindings:
        if _clean(binding.get("project_slug")) == slug:
            return binding
    for binding in bindings:
        store = binding.get("workspace_store")
        if isinstance(store, Path) and store.resolve() == project_path:
            return binding
    return None


def _load_legacy_registry(root: Path) -> dict[str, Any]:
    return legacy_registry.load_fleet_registry(
        root,
        load_json_fn=lambda path, default=None: _load_json(Path(path), default=default),
    )


def _legacy_registry_by_slug(root: Path) -> dict[str, dict[str, Any]]:
    registry = _load_legacy_registry(root)
    return {
        _clean(item.get("project_slug")): item
        for item in registry.get("projects", [])
        if isinstance(item, dict) and _clean(item.get("project_slug"))
    }


def _registry_entry(
    *,
    slug: str,
    project_dir: Path,
    snapshot: dict[str, Any],
    binding: dict[str, Any] | None,
    legacy_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    project_data = _load_json(project_dir / "project.json", default={})
    if not isinstance(project_data, dict):
        project_data = {}
    maestro_meta = project_data.get("maestro") if isinstance(project_data.get("maestro"), dict) else {}
    if not isinstance(maestro_meta, dict):
        maestro_meta = {}

    agent_id = _clean((binding or {}).get("id")) or f"maestro-project-{slug}"
    entry = {
        "project_slug": slug,
        "project_name": _clean(snapshot.get("project_name") or snapshot.get("name")) or slug,
        "project_dir_name": project_dir.name,
        "project_store_path": str(project_dir.resolve()),
        "maestro_agent_id": agent_id,
        "ingest_input_root": _clean(maestro_meta.get("ingest_input_root")) or _clean((legacy_entry or {}).get("ingest_input_root")),
        "superintendent": (
            _clean(maestro_meta.get("superintendent"))
            or _clean(snapshot.get("superintendent"))
            or _clean((legacy_entry or {}).get("superintendent"))
            or "Unknown"
        ),
        "assignee": (
            _clean(maestro_meta.get("assignee"))
            or _clean(snapshot.get("assignee"))
            or _clean((legacy_entry or {}).get("assignee"))
            or "Unassigned"
        ),
        "status": _clean(snapshot.get("status")) or _clean(maestro_meta.get("status")) or _clean((legacy_entry or {}).get("status")) or "active",
        "last_ingest_at": _clean(project_data.get("ingested_at")),
        "last_index_at": _clean(legacy_control_plane._project_index_timestamp(project_dir)),
        "last_updated": _clean(snapshot.get("last_updated")),
        "telegram_bot_username": _clean(maestro_meta.get("telegram_bot_username")) or _clean((legacy_entry or {}).get("telegram_bot_username")),
        "telegram_bot_display_name": _clean(maestro_meta.get("telegram_bot_display_name")) or _clean((legacy_entry or {}).get("telegram_bot_display_name")),
        "last_conversation_at": _clean((legacy_entry or {}).get("last_conversation_at")),
        "workspace": _clean((binding or {}).get("workspace")),
        "model": _clean((binding or {}).get("model")) or _clean(maestro_meta.get("model")),
    }
    display_name, source, handle = legacy_registry.resolve_node_identity(entry)
    entry["node_display_name"] = display_name
    entry["node_identity_source"] = source
    entry["node_handle"] = handle
    return entry


def build_derived_registry(store_root: Path, *, home_dir: Path | None = None) -> dict[str, Any]:
    root = Path(store_root).resolve()
    config = load_openclaw_config(home_dir=home_dir)
    bindings = _project_agent_bindings(config)
    legacy_entries = _legacy_registry_by_slug(root)

    snapshots_by_slug: dict[str, dict[str, Any]] = {}
    project_dirs_by_slug: dict[str, Path] = {}
    for project_dir in discover_project_dirs(root):
        snapshot = build_project_snapshot(project_dir)
        slug = _clean(snapshot.get("slug"))
        if not slug:
            continue
        project_dirs_by_slug[slug] = project_dir.resolve()
        snapshots_by_slug[slug] = snapshot

    projects: list[dict[str, Any]] = []
    for slug in sorted(project_dirs_by_slug.keys()):
        project_dir = project_dirs_by_slug[slug]
        snapshot = snapshots_by_slug[slug]
        binding = _matching_binding(bindings, slug, project_dir)
        projects.append(_registry_entry(
            slug=slug,
            project_dir=project_dir,
            snapshot=snapshot,
            binding=binding,
            legacy_entry=legacy_entries.get(slug),
        ))

    registry = {
        "version": int(getattr(legacy_registry, "REGISTRY_VERSION", 1)),
        "updated_at": _now_iso(),
        "store_root": str(root),
        "projects": sorted(projects, key=lambda item: _clean(item.get("project_name")).lower()),
    }
    return registry


def build_derived_onboarding_status(fleet_registry: dict[str, Any]) -> dict[str, Any]:
    projects = fleet_registry.get("projects", []) if isinstance(fleet_registry.get("projects"), list) else []
    active_count = len([
        item for item in projects
        if isinstance(item, dict) and _clean(item.get("status")).lower() != "archived"
    ])
    return {
        "project_create_command": "maestro-fleet project create",
        "active_project_count": active_count,
        "project_creation_policy": "unrestricted",
        "next_node_badge": "+",
        "purchase_disabled": True,
        "disabled_reason": "Fleet purchase flow is disabled. Use `maestro-fleet project create` directly.",
    }


def build_derived_awareness_state(
    *,
    store_root: Path,
    server_port: int,
    command_center_state: dict[str, Any],
    fleet_registry: dict[str, Any],
    command_runner: Any | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    config = load_openclaw_config(home_dir=home_dir)
    config_path = openclaw_config_path(
        home_dir=home_dir,
        default_profile=DEFAULT_FLEET_OPENCLAW_PROFILE,
        enforce_profile=True,
    )
    company_agent = _resolve_company_agent(config)

    runner = command_runner or legacy_control_plane._default_runner
    tailscale_installed = shutil.which("tailscale") is not None
    tailscale_connected = False
    tailscale_ip = ""
    if tailscale_installed:
        ok, out = _invoke_runner(runner, ["tailscale", "ip", "-4"], 5)
        if ok:
            parsed = legacy_control_plane._parse_tailscale_ipv4(out)
            tailscale_ip = _clean(parsed)
            tailscale_connected = bool(tailscale_ip)

    openclaw_installed = shutil.which("openclaw") is not None
    openclaw_running = False
    pairing_required = False
    status_output = ""
    gateway_status: dict[str, Any] = {}
    if openclaw_installed:
        _ok, gateway_out = _invoke_runner(runner, ["openclaw", "gateway", "status", "--json"], 8)
        gateway_status = legacy_control_plane._parse_json_from_output(gateway_out)
        if gateway_status:
            openclaw_running = legacy_control_plane._gateway_status_running(gateway_status)
            status_output = gateway_out

        ok, out = _invoke_runner(runner, ["openclaw", "status"], 6)
        if not status_output:
            status_output = out
        lowered = out.lower()
        if not gateway_status:
            openclaw_running = (ok and "running" in lowered) or ("gateway service" in lowered and "running" in lowered)
        pairing_required = "pairing required" in lowered

    services = {
        "config_path": str(config_path),
        "tailscale": {
            "installed": tailscale_installed,
            "connected": tailscale_connected,
            "ip": tailscale_ip,
        },
        "openclaw": {
            "installed": openclaw_installed,
            "running": openclaw_running,
            "pairing_required": pairing_required,
            "gateway_auth": legacy_control_plane._gateway_auth_health(config),
            "device_pairing": legacy_control_plane._pending_device_pairing(
                runner=runner,
                openclaw_installed=openclaw_installed,
                pairing_required=pairing_required,
            ),
            "status_snippet": status_output[:240],
        },
        "telegram": {
            "configured": legacy_control_plane._telegram_configured(config),
            "routing": legacy_control_plane.telegram_binding_health(config),
        },
        "company_agent": {
            "configured": bool(company_agent),
            "id": _clean(company_agent.get("id")) or "maestro-company",
            "name": _clean(company_agent.get("name")) or "The Commander",
            "workspace": _clean(company_agent.get("workspace")),
        },
    }

    network = resolve_network_urls(
        web_port=int(server_port),
        route_path="/command-center",
        command_runner=runner,
    )

    fleet_projects = fleet_registry.get("projects", []) if isinstance(fleet_registry.get("projects"), list) else []
    slug_counts: dict[str, int] = {}
    for item in fleet_projects:
        if not isinstance(item, dict):
            continue
        slug = _clean(item.get("project_slug"))
        if slug:
            slug_counts[slug] = slug_counts.get(slug, 0) + 1
    duplicate_project_slugs = sorted(slug for slug, count in slug_counts.items() if count > 1)

    stale_projects: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for item in fleet_projects:
        if not isinstance(item, dict):
            continue
        dt = legacy_control_plane._parse_iso(item.get("last_updated")) or legacy_control_plane._parse_iso(item.get("last_ingest_at"))
        if dt is None:
            continue
        aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        age_hours = (now - aware.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours > 72:
            stale_projects.append({
                "project_slug": _clean(item.get("project_slug")),
                "project_name": _clean(item.get("project_name")),
                "last_updated": _clean(item.get("last_updated")),
                "age_hours": round(age_hours, 1),
            })

    degraded_reasons: list[str] = []
    if not services["tailscale"]["connected"]:
        degraded_reasons.append("Tailscale not connected")
    if not services["openclaw"]["running"]:
        degraded_reasons.append("OpenClaw gateway not running")
    gateway_auth = services["openclaw"]["gateway_auth"]
    if not bool(gateway_auth.get("tokens_aligned")):
        degraded_reasons.append("Gateway auth token mismatch or missing")
    device_pairing = services["openclaw"]["device_pairing"]
    if bool(device_pairing.get("required")):
        degraded_reasons.append("CLI device pairing approval required")
    if not services["telegram"]["configured"]:
        degraded_reasons.append("Telegram not configured")
    telegram_routing = services["telegram"]["routing"]
    if not bool(telegram_routing.get("fully_bound", True)):
        degraded_reasons.append("Telegram routing bindings missing")
    if not services["company_agent"]["configured"]:
        degraded_reasons.append("Commander agent not configured")
    project_count = len(fleet_projects)
    if not root.exists():
        degraded_reasons.append("Knowledge store root missing")
    if project_count == 0:
        degraded_reasons.append("No project nodes discovered")
    if duplicate_project_slugs:
        degraded_reasons.append("Duplicate project slug registrations: " + ", ".join(duplicate_project_slugs))

    orchestrator = command_center_state.get("orchestrator") if isinstance(command_center_state, dict) else {}
    current_action = _clean((orchestrator or {}).get("currentAction"))
    onboarding = build_derived_onboarding_status(fleet_registry)

    commander_name = _clean(company_agent.get("name")) or _clean((command_center_state.get("commander") or {}).get("name")) or "The Commander"
    commander_id = _clean(company_agent.get("id")) or "maestro-company"
    return {
        "generated_at": _now_iso(),
        "posture": "healthy" if not degraded_reasons else "degraded",
        "degraded_reasons": degraded_reasons,
        "network": network,
        "paths": {
            "store_root": str(root),
            "registry_path": str(legacy_registry.fleet_registry_path(root)),
            "workspace_root": _clean(company_agent.get("workspace")),
        },
        "services": services,
        "commander": {
            "display_name": commander_name,
            "agent_id": commander_id,
            "chat_transport": "openclaw_agent_invoke",
        },
        "fleet": {
            "project_count": project_count,
            "duplicate_project_slugs": duplicate_project_slugs,
            "stale_projects": stale_projects,
            "registry": fleet_registry,
            "current_action": current_action,
            "directives": summarize_system_directives(root),
        },
        "commands": {
            "update": "maestro update",
            "doctor": "maestro doctor --fix",
            "serve": f"maestro serve --port {int(server_port)} --store {legacy_control_plane._quote_path(root)}",
            "start": f"maestro start --port {int(server_port)} --store {legacy_control_plane._quote_path(root)}",
            "project_create": "maestro-fleet project create",
        },
        "onboarding": onboarding,
        "purchase": onboarding,
        "available_actions": list(_AVAILABLE_ACTIONS),
    }


class DerivedCommandCenterStateBackend:
    """Derived-state backend for Fleet server runtime."""

    def refresh_command_center_state(self, *, server_module: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        try:
            registry = build_derived_registry(Path(server_module.store_path))
            state = build_command_center_state(Path(server_module.store_path))
            if registry:
                server_module._apply_registry_identity_to_command_center_state(state, registry)
            config = _server_openclaw_config(server_module)
            _merge_agent_nodes_into_command_center_state(
                state,
                config,
                slugify_fn=server_module.slugify,
            )
            if isinstance(server_module.awareness_state, dict) and server_module.awareness_state:
                _apply_runtime_node_state(state, server_module.awareness_state)
        except Exception as exc:
            print(f"Fleet-derived command center refresh failed: {exc}", file=sys.stderr)
            state = {
                "updated_at": "",
                "store_root": str(server_module.store_path),
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
        node_index = _build_command_center_node_index(
            state,
            commander_node_slug=str(server_module.COMMANDER_NODE_SLUG),
        )
        return state, node_index

    def refresh_control_plane_state(
        self,
        *,
        server_module: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any], dict[str, dict[str, Any]]]:
        command_center_state = server_module.command_center_state if isinstance(server_module.command_center_state, dict) else {}
        command_center_node_index = (
            server_module.command_center_node_index if isinstance(server_module.command_center_node_index, dict) else {}
        )
        if not command_center_state:
            command_center_state, command_center_node_index = self.refresh_command_center_state(server_module=server_module)

        fleet_registry = build_derived_registry(Path(server_module.store_path))
        agent_project_slug_index = {
            _clean(item.get("maestro_agent_id")): _clean(item.get("project_slug"))
            for item in fleet_registry.get("projects", [])
            if isinstance(item, dict)
            and _clean(item.get("maestro_agent_id"))
            and _clean(item.get("project_slug"))
            and _clean(item.get("status")).lower() != "archived"
        }

        awareness_state = build_derived_awareness_state(
            store_root=Path(server_module.store_path),
            server_port=int(server_module.server_port),
            command_center_state=command_center_state,
            fleet_registry=fleet_registry,
        )
        if command_center_state:
            _apply_runtime_node_state(command_center_state, awareness_state)
            command_center_node_index = _build_command_center_node_index(
                command_center_state,
                commander_node_slug=str(server_module.COMMANDER_NODE_SLUG),
            )
        return (
            fleet_registry,
            awareness_state,
            agent_project_slug_index,
            command_center_state,
            command_center_node_index,
        )


def install_fleet_command_center_backend(server_module: Any) -> DerivedCommandCenterStateBackend:
    backend = DerivedCommandCenterStateBackend()
    setter = getattr(server_module, "set_command_center_state_backend", None)
    if callable(setter):
        setter(backend)
    else:
        server_module.command_center_state_backend = backend
    return backend


__all__ = [
    "DerivedCommandCenterStateBackend",
    "build_derived_awareness_state",
    "build_derived_registry",
    "install_fleet_command_center_backend",
]
