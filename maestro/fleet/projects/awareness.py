"""Fleet awareness-state helpers."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CommandRunner = Callable[[list[str], int], tuple[bool, str]]
LoadOpenClawConfigFn = Callable[[Path | None], tuple[dict[str, Any], Path]]
ResolveCompanyAgentFn = Callable[[dict[str, Any]], dict[str, Any]]
ParseTailscaleIPv4Fn = Callable[[str], str | None]
ParseJsonFromOutputFn = Callable[[str], dict[str, Any]]
GatewayStatusRunningFn = Callable[[dict[str, Any]], bool]
GatewayAuthHealthFn = Callable[[dict[str, Any]], dict[str, Any]]
PendingDevicePairingFn = Callable[..., dict[str, Any]]
TelegramConfiguredFn = Callable[[dict[str, Any]], bool]
TelegramBindingHealthFn = Callable[[dict[str, Any]], dict[str, Any]]
ResolveNetworkUrlsFn = Callable[..., dict[str, Any]]
SyncFleetRegistryFn = Callable[[Path], dict[str, Any]]
SummarizeSystemDirectivesFn = Callable[[Path], dict[str, Any]]
ParseIsoFn = Callable[[Any], datetime | None]
FleetRegistryPathFn = Callable[[Path], Path]
QuotePathFn = Callable[[str | Path], str]
NowIsoFn = Callable[[], str]


def _invoke_runner(runner: CommandRunner, args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        return runner(args, timeout)
    except TypeError:
        return runner(args)  # type: ignore[misc]


def service_status(
    *,
    command_runner: CommandRunner | None,
    default_runner_fn: CommandRunner,
    load_openclaw_config_fn: LoadOpenClawConfigFn,
    resolve_company_agent_fn: ResolveCompanyAgentFn,
    parse_tailscale_ipv4_fn: ParseTailscaleIPv4Fn,
    parse_json_from_output_fn: ParseJsonFromOutputFn,
    gateway_status_running_fn: GatewayStatusRunningFn,
    gateway_auth_health_fn: GatewayAuthHealthFn,
    pending_device_pairing_fn: PendingDevicePairingFn,
    telegram_configured_fn: TelegramConfiguredFn,
    telegram_binding_health_fn: TelegramBindingHealthFn,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    runner = command_runner or default_runner_fn
    config, config_path = load_openclaw_config_fn(home_dir=home_dir)
    agent = resolve_company_agent_fn(config)

    tailscale_installed = shutil.which("tailscale") is not None
    tailscale_connected = False
    tailscale_ip = None
    if tailscale_installed:
        ok, out = _invoke_runner(runner, ["tailscale", "ip", "-4"], 5)
        if ok:
            tailscale_ip = parse_tailscale_ipv4_fn(out)
            tailscale_connected = bool(tailscale_ip)

    openclaw_installed = shutil.which("openclaw") is not None
    openclaw_running = False
    pairing_required = False
    status_output = ""
    gw_status: dict[str, Any] = {}
    if openclaw_installed:
        gw_ok, gw_out = _invoke_runner(runner, ["openclaw", "gateway", "status", "--json"], 8)
        _ = gw_ok
        gw_status = parse_json_from_output_fn(gw_out)
        if gw_status:
            openclaw_running = gateway_status_running_fn(gw_status)
            status_output = gw_out

        ok, out = _invoke_runner(runner, ["openclaw", "status"], 6)
        if not status_output:
            status_output = out
        lowered = out.lower()
        if not gw_status:
            openclaw_running = (ok and "running" in lowered) or ("gateway service" in lowered and "running" in lowered)
        pairing_required = "pairing required" in lowered

    gateway_auth = gateway_auth_health_fn(config)
    device_pairing = pending_device_pairing_fn(
        runner=runner,
        openclaw_installed=openclaw_installed,
        pairing_required=pairing_required,
    )

    return {
        "config_path": str(config_path),
        "tailscale": {
            "installed": tailscale_installed,
            "connected": tailscale_connected,
            "ip": tailscale_ip or "",
        },
        "openclaw": {
            "installed": openclaw_installed,
            "running": openclaw_running,
            "pairing_required": pairing_required,
            "gateway_auth": gateway_auth,
            "device_pairing": device_pairing,
            "status_snippet": status_output[:240],
        },
        "telegram": {
            "configured": telegram_configured_fn(config),
            "routing": telegram_binding_health_fn(config),
        },
        "company_agent": {
            "configured": bool(agent),
            "id": str(agent.get("id", "")),
            "name": str(agent.get("name", "")),
            "workspace": str(agent.get("workspace", "")),
        },
    }


def build_project_onboarding_status(
    store_root: Path,
    *,
    sync_fleet_registry_fn: SyncFleetRegistryFn,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_registry = registry if isinstance(registry, dict) else sync_fleet_registry_fn(store_root)
    projects = current_registry.get("projects", []) if isinstance(current_registry.get("projects"), list) else []
    active_count = len([
        item for item in projects
        if isinstance(item, dict) and str(item.get("status", "active")).strip().lower() != "archived"
    ])
    next_node_badge = "+"
    return {
        "project_create_command": "maestro-fleet project create",
        "active_project_count": active_count,
        "project_creation_policy": "unrestricted",
        "next_node_badge": next_node_badge,
        "purchase_disabled": True,
        "disabled_reason": "Fleet purchase flow is disabled. Use `maestro-fleet project create` directly.",
    }


def build_purchase_status(
    store_root: Path,
    *,
    build_project_onboarding_status_fn: Callable[[Path, dict[str, Any] | None], dict[str, Any]],
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_project_onboarding_status_fn(store_root, registry=registry)


def build_awareness_state(
    store_root: Path,
    *,
    sync_fleet_registry_fn: SyncFleetRegistryFn,
    service_status_fn: Callable[..., dict[str, Any]],
    resolve_network_urls_fn: ResolveNetworkUrlsFn,
    build_project_onboarding_status_fn: Callable[[Path, dict[str, Any] | None], dict[str, Any]],
    summarize_system_directives_fn: SummarizeSystemDirectivesFn,
    parse_iso_fn: ParseIsoFn,
    now_iso_fn: NowIsoFn,
    fleet_registry_path_fn: FleetRegistryPathFn,
    quote_path_fn: QuotePathFn,
    default_web_port: int,
    command_center_state: dict[str, Any] | None = None,
    web_port: int | None = None,
    command_runner: CommandRunner | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a machine-specific, runtime-specific awareness state contract."""
    root = Path(store_root).resolve()
    registry = sync_fleet_registry_fn(root)
    port = int(web_port or default_web_port)
    services = service_status_fn(command_runner=command_runner, home_dir=home_dir)
    network = resolve_network_urls_fn(web_port=port, command_runner=command_runner)
    onboarding = build_project_onboarding_status_fn(root, registry=registry)
    directives_summary = summarize_system_directives_fn(root)

    fleet_projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    project_count = len([p for p in fleet_projects if isinstance(p, dict) and p.get("status") != "archived"])
    slug_counts: dict[str, int] = {}
    for item in fleet_projects:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("project_slug", "")).strip()
        if not slug:
            continue
        slug_counts[slug] = slug_counts.get(slug, 0) + 1
    duplicate_project_slugs = sorted(slug for slug, count in slug_counts.items() if count > 1)

    stale_projects: list[dict[str, Any]] = []
    for item in fleet_projects:
        if not isinstance(item, dict):
            continue
        dt = parse_iso_fn(item.get("last_updated")) or parse_iso_fn(item.get("last_ingest_at"))
        if not dt:
            continue
        age_hours = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours > 72:
            stale_projects.append({
                "project_slug": item.get("project_slug", ""),
                "project_name": item.get("project_name", ""),
                "last_updated": item.get("last_updated", ""),
                "age_hours": round(age_hours, 1),
            })

    degraded_reasons: list[str] = []
    if not services["tailscale"]["connected"]:
        degraded_reasons.append("Tailscale not connected")
    if not services["openclaw"]["running"]:
        degraded_reasons.append("OpenClaw gateway not running")
    gateway_auth = services["openclaw"].get("gateway_auth", {}) if isinstance(services["openclaw"], dict) else {}
    if not bool(gateway_auth.get("tokens_aligned")):
        degraded_reasons.append("Gateway auth token mismatch or missing")
    device_pairing = services["openclaw"].get("device_pairing", {}) if isinstance(services["openclaw"], dict) else {}
    if bool(device_pairing.get("required")):
        degraded_reasons.append("CLI device pairing approval required")
    if not services["telegram"]["configured"]:
        degraded_reasons.append("Telegram not configured")
    telegram_routing = services.get("telegram", {}).get("routing", {}) if isinstance(services.get("telegram"), dict) else {}
    if not bool(telegram_routing.get("fully_bound", True)):
        degraded_reasons.append("Telegram routing bindings missing")
    if not services["company_agent"]["configured"]:
        degraded_reasons.append("Commander agent not configured")
    if not root.exists():
        degraded_reasons.append("Knowledge store root missing")
    if project_count == 0:
        degraded_reasons.append("No project nodes discovered")
    if duplicate_project_slugs:
        degraded_reasons.append(
            "Duplicate project slug registrations: " + ", ".join(duplicate_project_slugs)
        )

    posture = "healthy" if not degraded_reasons else "degraded"
    current_action = ""
    if isinstance(command_center_state, dict):
        orchestrator = command_center_state.get("orchestrator")
        if isinstance(orchestrator, dict):
            current_action = str(orchestrator.get("currentAction", "")).strip()

    return {
        "generated_at": now_iso_fn(),
        "posture": posture,
        "degraded_reasons": degraded_reasons,
        "network": network,
        "paths": {
            "store_root": str(root),
            "registry_path": str(fleet_registry_path_fn(root)),
            "workspace_root": str(services["company_agent"].get("workspace", "")).strip(),
        },
        "services": services,
        "commander": {
            "display_name": "The Commander",
            "agent_id": "maestro-company",
            "chat_transport": "openclaw_agent_invoke",
        },
        "fleet": {
            "project_count": project_count,
            "duplicate_project_slugs": duplicate_project_slugs,
            "stale_projects": stale_projects,
            "registry": registry,
            "current_action": current_action,
            "directives": directives_summary,
        },
        "commands": {
            "update": "maestro update",
            "doctor": "maestro doctor --fix",
            "serve": f"maestro serve --port {port} --store {quote_path_fn(root)}",
            "start": f"maestro start --port {port} --store {quote_path_fn(root)}",
            "project_create": "maestro-fleet project create",
        },
        "onboarding": onboarding,
        "purchase": onboarding,
        "available_actions": [
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
        ],
    }
