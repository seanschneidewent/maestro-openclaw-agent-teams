"""Default-agent control plane for command-center awareness and actions.

This module intentionally keeps all orchestration logic deterministic and
filesystem-driven so The Commander can reason from live state.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .command_center import build_project_snapshot, discover_project_dirs
from .fleet.projects import awareness as project_awareness
from .fleet.projects import ingest_commands as project_ingest_commands
from .fleet.projects import lifecycle as project_lifecycle
from .fleet.projects import registry as project_registry
from .fleet.shared import subprocesses as fleet_subprocesses
from .openclaw_profile import (
    DEFAULT_FLEET_OPENCLAW_PROFILE,
    openclaw_config_path,
    openclaw_workspace_root,
    prepend_openclaw_profile_args,
)
from .profile import PROFILE_FLEET, resolve_profile
from .system_directives import summarize_system_directives
from .utils import load_json, save_json, slugify
from .workspace_templates import (
    provider_env_key_for_model,
    render_project_agents_md,
    render_project_tools_md,
    render_workspace_awareness_md,
    should_remove_generic_project_bootstrap,
    should_refresh_generic_project_file,
)


REGISTRY_VERSION = 1
DEFAULT_WEB_PORT = 3000
DEFAULT_INPUT_PLACEHOLDER = "<ABS_PATH_TO_PLAN_PDFS>"
CommandRunner = Callable[[list[str], int], tuple[bool, str]]
PLACEHOLDER_MARKERS = ("<PASTE_", "PASTE_", "YOUR_KEY_HERE", "CHANGEME")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_runner(args: list[str], timeout: int = 6) -> tuple[bool, str]:
    default_profile = DEFAULT_FLEET_OPENCLAW_PROFILE if resolve_profile() == PROFILE_FLEET else ""
    return fleet_subprocesses.run_profiled_cmd(
        args,
        timeout=timeout,
        prepend_profile_args=lambda cmd: prepend_openclaw_profile_args(cmd, default_profile=default_profile),
    )


def _invoke_runner(runner: CommandRunner, args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        return runner(args, timeout)
    except TypeError:
        return runner(args)  # type: ignore[misc]


def _parse_json_from_output(text: str) -> dict[str, Any]:
    return fleet_subprocesses.parse_json_from_output(text)


def _gateway_status_running(gateway_status: dict[str, Any]) -> bool:
    service = gateway_status.get("service", {}) if isinstance(gateway_status.get("service"), dict) else {}
    runtime = service.get("runtime", {}) if isinstance(service.get("runtime"), dict) else {}
    status_text = str(runtime.get("status", "")).strip().lower()
    if status_text in {"running", "started", "active"}:
        return True

    rpc = gateway_status.get("rpc", {}) if isinstance(gateway_status.get("rpc"), dict) else {}
    if bool(rpc.get("ok")):
        return True

    port = gateway_status.get("port", {}) if isinstance(gateway_status.get("port"), dict) else {}
    port_status = str(port.get("status", "")).strip().lower()
    listeners = port.get("listeners")
    if port_status in {"busy", "listening", "occupied"} and isinstance(listeners, list) and listeners:
        return True
    return False


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for candidate in (raw, raw.replace("Z", "+00:00"), f"{raw}T00:00:00"):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _parse_tailscale_ipv4(output: str) -> str | None:
    for line in output.splitlines():
        ip = line.strip()
        if ip and "." in ip:
            return ip
    return None


def _project_index_timestamp(project_dir: Path) -> str:
    index_data = load_json(project_dir / "index.json")
    if not isinstance(index_data, dict):
        return ""

    candidates = [
        index_data.get("updated_at"),
        index_data.get("generated"),
    ]
    summary = index_data.get("summary")
    if isinstance(summary, dict):
        candidates.extend([
            summary.get("updated_at"),
            summary.get("generated"),
        ])
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _load_openclaw_config(home_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    profile = resolve_profile(home_dir=home_dir)
    default_profile = DEFAULT_FLEET_OPENCLAW_PROFILE if profile == PROFILE_FLEET else ""
    path = openclaw_config_path(home_dir=home_dir, default_profile=default_profile)
    payload = load_json(path)
    if not isinstance(payload, dict):
        payload = {}
    return payload, path


def _resolve_company_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    company = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("id") == "maestro-company"),
        None,
    )
    if isinstance(company, dict):
        return company
    default_agent = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("default")),
        None,
    )
    if isinstance(default_agent, dict):
        return default_agent
    legacy = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("id") == "maestro"),
        None,
    )
    return legacy if isinstance(legacy, dict) else {}


def _telegram_configured(config: dict[str, Any]) -> bool:
    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    tg = channels.get("telegram")
    if not isinstance(tg, dict):
        return False
    if tg.get("enabled") and tg.get("botToken"):
        return True
    accounts = tg.get("accounts")
    return isinstance(accounts, dict) and any(
        isinstance(account, dict) and account.get("botToken") for account in accounts.values()
    )


def _telegram_account_ids(config: dict[str, Any]) -> list[str]:
    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        return []
    accounts = telegram.get("accounts")
    if not isinstance(accounts, dict):
        return []
    ids: list[str] = []
    for key, value in accounts.items():
        if not isinstance(value, dict):
            continue
        account_id = str(key).strip()
        if account_id:
            ids.append(account_id)
    return ids


def ensure_telegram_account_bindings(
    config: dict[str, Any],
    *,
    include_company: bool = True,
) -> list[str]:
    """Ensure each Telegram account routes to its matching isolated agent.

    OpenClaw supports a top-level `bindings` route table. Without explicit
    bindings, inbound messages may hit the default company agent.
    """
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    known_agent_ids = {
        str(agent.get("id", "")).strip()
        for agent in agent_list
        if isinstance(agent, dict) and str(agent.get("id", "")).strip()
    }

    account_ids = _telegram_account_ids(config)
    if not account_ids:
        return []

    bindings = config.get("bindings")
    if not isinstance(bindings, list):
        bindings = []
        config["bindings"] = bindings

    existing_pairs: set[tuple[str, str, str]] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        agent_id = str(binding.get("agentId", "")).strip()
        match = binding.get("match")
        if not isinstance(match, dict):
            continue
        channel = str(match.get("channel", "")).strip().lower()
        account_id = str(match.get("accountId", "")).strip()
        if agent_id and channel and account_id:
            existing_pairs.add((agent_id, channel, account_id))

    changes: list[str] = []
    for account_id in account_ids:
        if (not include_company) and account_id == "maestro-company":
            continue
        if account_id not in known_agent_ids:
            continue
        key = (account_id, "telegram", account_id)
        if key in existing_pairs:
            continue
        bindings.append({
            "agentId": account_id,
            "match": {
                "channel": "telegram",
                "accountId": account_id,
            },
        })
        existing_pairs.add(key)
        changes.append(f"Added Telegram binding: {account_id} -> telegram:{account_id}")

    return changes


def telegram_binding_health(config: dict[str, Any]) -> dict[str, Any]:
    """Return routing health for Telegram account-to-agent bindings."""
    accounts = _telegram_account_ids(config)
    bindings = config.get("bindings")
    binding_pairs: set[tuple[str, str, str]] = set()
    if isinstance(bindings, list):
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            agent_id = str(binding.get("agentId", "")).strip()
            match = binding.get("match")
            if not isinstance(match, dict):
                continue
            channel = str(match.get("channel", "")).strip().lower()
            account_id = str(match.get("accountId", "")).strip()
            if agent_id and channel and account_id:
                binding_pairs.add((agent_id, channel, account_id))

    missing = [
        account_id
        for account_id in accounts
        if (account_id, "telegram", account_id) not in binding_pairs
    ]
    return {
        "configured_accounts": len(accounts),
        "missing_bindings": missing,
        "fully_bound": len(missing) == 0,
    }


def _is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    text = value.strip()
    if not text:
        return True
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def _gateway_auth_health(config: dict[str, Any]) -> dict[str, Any]:
    gateway = config.get("gateway") if isinstance(config.get("gateway"), dict) else {}
    auth = gateway.get("auth") if isinstance(gateway.get("auth"), dict) else {}
    remote = gateway.get("remote") if isinstance(gateway.get("remote"), dict) else {}
    auth_token = str(auth.get("token", "")).strip()
    remote_token = str(remote.get("token", "")).strip()

    auth_ok = bool(auth_token) and not _is_placeholder_secret(auth_token)
    remote_ok = bool(remote_token) and not _is_placeholder_secret(remote_token)
    aligned = bool(auth_ok and remote_ok and auth_token == remote_token)
    return {
        "auth_token_configured": auth_ok,
        "remote_token_configured": remote_ok,
        "tokens_aligned": aligned,
    }


def _pending_device_pairing(
    *,
    runner: CommandRunner,
    openclaw_installed: bool,
    pairing_required: bool,
) -> dict[str, Any]:
    status = {
        "required": pairing_required,
        "pending_requests": 0,
        "auto_approvable": False,
        "source": "none",
    }
    if not openclaw_installed:
        status["source"] = "openclaw_missing"
        return status
    if not pairing_required:
        status["source"] = "status"
        return status

    ok, out = _invoke_runner(runner, ["openclaw", "devices", "list", "--json"], 8)
    if not ok:
        status["source"] = "devices_list_failed"
        return status
    try:
        payload = json.loads(out)
    except Exception:
        status["source"] = "devices_list_invalid_json"
        return status

    pending = payload.get("pending")
    pending_list = pending if isinstance(pending, list) else []
    count = len(pending_list)
    status["pending_requests"] = count
    status["auto_approvable"] = count == 1
    status["source"] = "devices_list"
    return status


def resolve_network_urls(
    web_port: int = DEFAULT_WEB_PORT,
    command_runner: CommandRunner | None = None,
    route_path: str = "/command-center",
) -> dict[str, Any]:
    runner = command_runner or _default_runner
    path = str(route_path or "/").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    localhost = f"http://localhost:{web_port}{path}"

    tailnet_ip: str | None = None
    if shutil.which("tailscale"):
        ok, out = _invoke_runner(runner, ["tailscale", "ip", "-4"], 5)
        if ok:
            tailnet_ip = _parse_tailscale_ipv4(out)

    tailnet = f"http://{tailnet_ip}:{web_port}{path}" if tailnet_ip else None
    return {
        "localhost_url": localhost,
        "tailnet_url": tailnet,
        "recommended_url": tailnet or localhost,
        "tailscale_ip": tailnet_ip,
    }


def fleet_registry_path(store_root: Path) -> Path:
    return project_registry.fleet_registry_path(store_root)


def _default_registry(store_root: Path) -> dict[str, Any]:
    return project_registry.default_registry(store_root)


def _clean_registry_text(value: Any) -> str:
    return project_registry.clean_registry_text(value)


def _normalize_bot_username(value: Any) -> str:
    return project_registry.normalize_bot_username(value)


def resolve_node_identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return project_registry.resolve_node_identity(entry)


def load_fleet_registry(store_root: Path) -> dict[str, Any]:
    return project_registry.load_fleet_registry(store_root, load_json_fn=load_json)


def _registries_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return project_registry.registries_equal(left, right)


def save_fleet_registry(store_root: Path, registry: dict[str, Any]):
    project_registry.save_fleet_registry(store_root, registry, save_json_fn=save_json)


def sync_fleet_registry(store_root: Path, dry_run: bool = False) -> dict[str, Any]:
    return project_registry.sync_fleet_registry(
        store_root,
        discover_project_dirs_fn=discover_project_dirs,
        build_project_snapshot_fn=build_project_snapshot,
        load_json_fn=load_json,
        save_json_fn=save_json,
        project_index_timestamp_fn=_project_index_timestamp,
        now_iso_fn=_now_iso,
        dry_run=dry_run,
    )


def _find_registry_project(registry: dict[str, Any], project_slug: str) -> dict[str, Any] | None:
    return project_registry.find_registry_project(registry, project_slug)


def _quote_path(path: str | Path) -> str:
    return project_ingest_commands.quote_path(path)


def _workspace_routes(project_slug: str, project_entry: dict[str, Any] | None = None) -> dict[str, str]:
    return project_ingest_commands.workspace_routes(project_slug, project_entry)


def _resolve_input_root(path: str | None) -> Path | None:
    return project_ingest_commands.resolve_input_root(path)


def build_ingest_preflight(
    store_root: Path,
    project_entry: dict[str, Any],
    input_root_override: str | None = None,
) -> dict[str, Any]:
    return project_ingest_commands.build_ingest_preflight(store_root, project_entry, input_root_override=input_root_override)


def build_ingest_command(
    store_root: Path,
    project_entry: dict[str, Any],
    input_root_override: str | None = None,
    dpi: int = 200,
) -> dict[str, Any]:
    return project_ingest_commands.build_ingest_command(
        store_root,
        project_entry,
        input_root_override=input_root_override,
        dpi=dpi,
    )


def build_index_command(project_entry: dict[str, Any]) -> str:
    return project_ingest_commands.build_index_command(project_entry)


def project_control_payload(
    store_root: Path,
    project_slug: str,
    input_root_override: str | None = None,
    dpi: int = 200,
) -> dict[str, Any]:
    return project_ingest_commands.project_control_payload(
        store_root,
        project_slug,
        sync_fleet_registry_fn=sync_fleet_registry,
        find_registry_project_fn=_find_registry_project,
        workspace_routes_fn=_workspace_routes,
        input_root_override=input_root_override,
        dpi=dpi,
    )


def create_project_node(
    store_root: Path,
    project_name: str,
    project_slug: str | None = None,
    project_dir_name: str | None = None,
    ingest_input_root: str | None = None,
    superintendent: str | None = None,
    assignee: str | None = None,
    register_agent: bool = False,
    home_dir: Path | None = None,
    agent_model: str | None = None,
    telegram_bot_username: str | None = None,
    telegram_bot_display_name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return project_lifecycle.create_project_node(
        store_root,
        project_name,
        slugify_fn=slugify,
        now_iso_fn=_now_iso,
        save_json_fn=save_json,
        sync_fleet_registry_fn=lambda root: sync_fleet_registry(root, dry_run=dry_run),
        find_registry_project_fn=_find_registry_project,
        save_fleet_registry_fn=save_fleet_registry,
        resolve_node_identity_fn=resolve_node_identity,
        project_control_payload_fn=lambda root, slug: project_control_payload(root, slug, dpi=200),
        register_project_agent_fn=register_project_agent,
        registry_version=REGISTRY_VERSION,
        project_slug=project_slug,
        project_dir_name=project_dir_name,
        ingest_input_root=ingest_input_root,
        superintendent=superintendent,
        assignee=assignee,
        register_agent=register_agent,
        home_dir=home_dir,
        agent_model=agent_model,
        telegram_bot_username=telegram_bot_username,
        telegram_bot_display_name=telegram_bot_display_name,
        normalize_bot_username_fn=_normalize_bot_username,
        dry_run=dry_run,
    )


def onboard_project_store(
    store_root: Path,
    source_path: str,
    project_name: str | None = None,
    project_slug: str | None = None,
    project_dir_name: str | None = None,
    ingest_input_root: str | None = None,
    superintendent: str | None = None,
    assignee: str | None = None,
    register_agent: bool = True,
    move_source: bool = True,
    home_dir: Path | None = None,
    agent_model: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return project_lifecycle.onboard_project_store(
        store_root,
        source_path,
        load_json_fn=load_json,
        save_json_fn=save_json,
        slugify_fn=slugify,
        now_iso_fn=_now_iso,
        sync_fleet_registry_fn=lambda root: sync_fleet_registry(root, dry_run=dry_run),
        find_registry_project_fn=_find_registry_project,
        save_fleet_registry_fn=save_fleet_registry,
        resolve_node_identity_fn=resolve_node_identity,
        register_project_agent_fn=register_project_agent,
        build_ingest_command_fn=lambda root, entry, input_root_override, dpi: build_ingest_command(
            root,
            entry,
            input_root_override=input_root_override,
            dpi=dpi,
        ),
        build_ingest_preflight_fn=lambda root, entry, input_root_override: build_ingest_preflight(
            root,
            entry,
            input_root_override=input_root_override,
        ),
        resolve_network_urls_fn=resolve_network_urls,
        quote_path_fn=_quote_path,
        registry_version=REGISTRY_VERSION,
        default_web_port=DEFAULT_WEB_PORT,
        default_input_placeholder=DEFAULT_INPUT_PLACEHOLDER,
        project_name=project_name,
        project_slug=project_slug,
        project_dir_name=project_dir_name,
        ingest_input_root=ingest_input_root,
        superintendent=superintendent,
        assignee=assignee,
        register_agent=register_agent,
        move_source=move_source,
        home_dir=home_dir,
        agent_model=agent_model,
        dry_run=dry_run,
    )


def move_project_store(
    store_root: Path,
    project_slug: str,
    new_dir_name: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    return project_lifecycle.move_project_store(
        store_root,
        project_slug,
        new_dir_name,
        sync_fleet_registry_fn=sync_fleet_registry,
        find_registry_project_fn=_find_registry_project,
        quote_path_fn=_quote_path,
        dry_run=dry_run,
    )


def _default_model_from_agents(agent_list: list[dict[str, Any]]) -> str:
    return project_lifecycle.default_model_from_agents(agent_list)


def register_project_agent(
    store_root: Path,
    project_slug: str,
    project_name: str,
    project_store_path: str,
    home_dir: Path | None = None,
    dry_run: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    result = project_lifecycle.register_project_agent(
        store_root,
        project_slug,
        project_name,
        project_store_path,
        load_openclaw_config_fn=_load_openclaw_config,
        resolve_company_agent_fn=_resolve_company_agent,
        openclaw_workspace_root_fn=openclaw_workspace_root,
        resolve_profile_fn=resolve_profile,
        ensure_telegram_account_bindings_fn=ensure_telegram_account_bindings,
        save_json_fn=save_json,
        default_fleet_openclaw_profile=DEFAULT_FLEET_OPENCLAW_PROFILE,
        profile_fleet=PROFILE_FLEET,
        home_dir=home_dir,
        dry_run=dry_run,
        model=model,
    )
    if bool(result.get("ok")) and not dry_run:
        project_workspace = Path(str(result.get("workspace", "")).strip()).expanduser()
        if str(project_workspace):
            urls = resolve_network_urls(route_path=f"/{project_slug}/")
            model_value = str(result.get("model", "")).strip() or "unknown"
            awareness = render_workspace_awareness_md(
                model=model_value,
                preferred_url=str(urls.get("recommended_url", "")).strip(),
                local_url=str(urls.get("localhost_url", "")).strip(),
                tailnet_url=str(urls.get("tailnet_url") or "").strip(),
                store_root=project_store_path,
                surface_label="Workspace",
                generated_by="maestro-fleet project create",
            )
            project_workspace.mkdir(parents=True, exist_ok=True)
            (project_workspace / "AWARENESS.md").write_text(awareness, encoding="utf-8")
            agents_path = project_workspace / "AGENTS.md"
            current_agents = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
            if (not agents_path.exists()) or should_refresh_generic_project_file("AGENTS.md", current_agents):
                agents_path.write_text(render_project_agents_md(), encoding="utf-8")
            tools_path = project_workspace / "TOOLS.md"
            current_tools = tools_path.read_text(encoding="utf-8") if tools_path.exists() else ""
            if (not tools_path.exists()) or should_refresh_generic_project_file("TOOLS.md", current_tools):
                tools_path.write_text(
                    render_project_tools_md(provider_env_key_for_model(model_value)),
                    encoding="utf-8",
                )
            bootstrap_path = project_workspace / "BOOTSTRAP.md"
            if bootstrap_path.exists():
                bootstrap_content = bootstrap_path.read_text(encoding="utf-8")
                if should_remove_generic_project_bootstrap(bootstrap_content):
                    bootstrap_path.unlink()
    return result


def _service_status(
    command_runner: CommandRunner | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    return project_awareness.service_status(
        command_runner=command_runner,
        default_runner_fn=_default_runner,
        load_openclaw_config_fn=_load_openclaw_config,
        resolve_company_agent_fn=_resolve_company_agent,
        parse_tailscale_ipv4_fn=_parse_tailscale_ipv4,
        parse_json_from_output_fn=_parse_json_from_output,
        gateway_status_running_fn=_gateway_status_running,
        gateway_auth_health_fn=_gateway_auth_health,
        pending_device_pairing_fn=_pending_device_pairing,
        telegram_configured_fn=_telegram_configured,
        telegram_binding_health_fn=telegram_binding_health,
        home_dir=home_dir,
    )


def build_project_onboarding_status(
    store_root: Path,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return project_awareness.build_project_onboarding_status(
        store_root,
        sync_fleet_registry_fn=sync_fleet_registry,
        registry=registry,
    )


def build_purchase_status(
    store_root: Path,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for older callers."""
    return project_awareness.build_purchase_status(
        store_root,
        build_project_onboarding_status_fn=build_project_onboarding_status,
        registry=registry,
    )


def build_awareness_state(
    store_root: Path,
    command_center_state: dict[str, Any] | None = None,
    web_port: int = DEFAULT_WEB_PORT,
    command_runner: CommandRunner | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    return project_awareness.build_awareness_state(
        store_root,
        sync_fleet_registry_fn=sync_fleet_registry,
        service_status_fn=_service_status,
        resolve_network_urls_fn=resolve_network_urls,
        build_project_onboarding_status_fn=build_project_onboarding_status,
        summarize_system_directives_fn=summarize_system_directives,
        parse_iso_fn=_parse_iso,
        now_iso_fn=_now_iso,
        fleet_registry_path_fn=fleet_registry_path,
        quote_path_fn=_quote_path,
        default_web_port=DEFAULT_WEB_PORT,
        command_center_state=command_center_state,
        web_port=web_port,
        command_runner=command_runner,
        home_dir=home_dir,
    )
