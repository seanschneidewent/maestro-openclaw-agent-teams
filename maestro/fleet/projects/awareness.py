"""Fleet awareness-state helpers."""

from __future__ import annotations

import shutil
import sys
import warnings
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

_BUILD_PURCHASE_STATUS_DEPRECATED_WARNED = False


def _load_package_command_center_module():
    try:
        from maestro_fleet import command_center as command_center_module
        return command_center_module
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[3]
        package_src = repo_root / "packages" / "maestro-fleet" / "src"
        if package_src.exists() and str(package_src) not in sys.path:
            sys.path.insert(0, str(package_src))
        from maestro_fleet import command_center as command_center_module
        return command_center_module


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
    command_center_module = _load_package_command_center_module()
    return command_center_module.build_derived_onboarding_status(current_registry)


def build_purchase_status(
    store_root: Path,
    *,
    build_project_onboarding_status_fn: Callable[[Path, dict[str, Any] | None], dict[str, Any]],
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global _BUILD_PURCHASE_STATUS_DEPRECATED_WARNED
    if not _BUILD_PURCHASE_STATUS_DEPRECATED_WARNED:
        warnings.warn(
            "maestro.fleet.projects.awareness.build_purchase_status() is deprecated; use build_project_onboarding_status() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        _BUILD_PURCHASE_STATUS_DEPRECATED_WARNED = True
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
    root = Path(store_root).resolve()
    _ = (
        service_status_fn,
        resolve_network_urls_fn,
        build_project_onboarding_status_fn,
        summarize_system_directives_fn,
        parse_iso_fn,
        fleet_registry_path_fn,
        quote_path_fn,
        now_iso_fn,
    )
    command_center_module = _load_package_command_center_module()
    registry = sync_fleet_registry_fn(root)
    return command_center_module.build_derived_awareness_state(
        store_root=root,
        server_port=int(web_port or default_web_port),
        command_center_state=command_center_state if isinstance(command_center_state, dict) else {},
        fleet_registry=registry,
        command_runner=command_runner,
        home_dir=home_dir,
    )
