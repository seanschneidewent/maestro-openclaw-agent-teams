"""Fleet model/binding helpers for commander and project agents."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from .command_center import discover_project_dirs
from .control_plane import ensure_telegram_account_bindings
from .fleet_deploy import (
    _approve_telegram_pairing_code,
    _fleet_gateway_port,
    _is_maestro_managed_agent,
    _validate_api_key,
    _validate_telegram_token,
)
from .fleet_constants import FLEET_PROFILE, canonicalize_model
from .fleet.runtime import gateway as fleet_gateway_runtime
from .fleet.shared.subprocesses import parse_json_from_output
from .install_state import resolve_fleet_store_root
from .openclaw_guard import ensure_openclaw_override_allowed
from .openclaw_profile import (
    openclaw_config_path,
    prepend_openclaw_profile_args,
)
from .utils import load_json, save_json, slugify
from .workspace_templates import provider_env_key_for_model, render_workspace_env


console = Console()

_PROJECT_METADATA_KEY = "maestro"


def _load_openclaw_config(home_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    config_path = openclaw_config_path(
        home_dir=home_dir,
        enforce_profile=True,
    )
    payload = load_json(config_path, default={})
    if not isinstance(payload, dict):
        payload = {}
    return payload, config_path


def _restart_openclaw_gateway() -> tuple[bool, str]:
    def _run_gateway(args: list[str], timeout: int) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                prepend_openclaw_profile_args(args, default_profile=FLEET_PROFILE),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return False, "openclaw CLI not found on PATH"
        except Exception as exc:
            return False, str(exc)
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output

    def _status_snapshot(timeout: int = 12) -> tuple[bool, dict[str, Any], str]:
        return fleet_gateway_runtime.gateway_status_snapshot(
            run_cmd=_run_gateway,
            parse_json=parse_json_from_output,
            timeout=timeout,
        )

    actions: list[str] = []

    gw_ok, gw_status, gw_out = _status_snapshot(12)
    if fleet_gateway_runtime.gateway_cli_ready(gw_status):
        return True, gw_out or "Gateway already running"

    restart_ok, restart_output = _run_gateway(["openclaw", "gateway", "restart"], timeout=45)
    if restart_output:
        actions.append(restart_output)

    recheck_ok, recheck_status, recheck_out = _status_snapshot(12)
    if fleet_gateway_runtime.gateway_cli_ready(recheck_status):
        return True, "\n".join(actions) or recheck_out or "Gateway restarted"

    start_ok, start_output = _run_gateway(["openclaw", "gateway", "start"], timeout=45)
    if start_output:
        actions.append(start_output)

    recheck_ok, recheck_status, recheck_out = _status_snapshot(12)
    if fleet_gateway_runtime.gateway_cli_ready(recheck_status):
        return True, "\n".join(actions) or recheck_out or "Gateway started"

    install_ok, install_output = _run_gateway(
        ["openclaw", "gateway", "install", "--force", "--port", str(_fleet_gateway_port())],
        timeout=75,
    )
    if install_output:
        actions.append(install_output)
    if not install_ok:
        return False, "\n".join(item for item in actions if item).strip() or "Failed to restart gateway"

    start2_ok, start2_output = _run_gateway(["openclaw", "gateway", "start"], timeout=45)
    if start2_output:
        actions.append(start2_output)

    recheck2_ok, recheck2_status, recheck2_out = _status_snapshot(12)
    if fleet_gateway_runtime.gateway_cli_ready(recheck2_status):
        return True, "\n".join(item for item in actions if item).strip() or recheck2_out or "Gateway reinstalled and started"
    return False, "\n".join(item for item in actions if item).strip() or recheck2_out or "Failed to restart gateway"


def _resolve_selected_key(
    *,
    config: dict[str, Any],
    provider_env_key: str,
    api_key: str | None,
    skip_remote_validation: bool,
) -> tuple[str, bool]:
    env = config.get("env", {}) if isinstance(config.get("env"), dict) else {}
    selected = str(api_key or "").strip() or str(env.get(provider_env_key, "")).strip()
    if not selected:
        console.print(f"[red]Missing {provider_env_key}. Provide --api-key or set it in OpenClaw config.[/]")
        return "", False
    if not skip_remote_validation:
        ok, detail = _validate_api_key(provider_env_key, selected)
        if not ok:
            console.print(f"[red]{provider_env_key} validation failed: {detail}[/]")
            return "", False
    return selected, True


def _write_workspace_env(
    *,
    workspace_path: str,
    store_path: str,
    provider_env_key: str,
    provider_key: str,
    gemini_key: str,
    agent_role: str,
    project_slug: str | None = None,
):
    workspace = Path(str(workspace_path or "")).expanduser()
    if not str(workspace_path or "").strip():
        return
    workspace.mkdir(parents=True, exist_ok=True)
    payload = render_workspace_env(
        store_path=store_path,
        provider_env_key=provider_env_key,
        provider_key=provider_key,
        gemini_key=gemini_key,
        agent_role=agent_role,
    )
    clean_slug = str(project_slug or "").strip()
    if clean_slug:
        payload = payload.rstrip("\n") + f"\nMAESTRO_PROJECT_SLUG={clean_slug}\n"
    (workspace / ".env").write_text(payload, encoding="utf-8")


def _load_project_json(project_dir: Path) -> dict[str, Any]:
    payload = load_json(project_dir / "project.json", default={})
    return payload if isinstance(payload, dict) else {}


def _project_store_entry(project_dir: Path) -> dict[str, Any]:
    payload = _load_project_json(project_dir)
    maestro_meta = payload.get(_PROJECT_METADATA_KEY) if isinstance(payload.get(_PROJECT_METADATA_KEY), dict) else {}
    if not isinstance(maestro_meta, dict):
        maestro_meta = {}
    project_name = str(payload.get("name", "")).strip() or project_dir.name
    project_slug = slugify(str(payload.get("slug", "")).strip() or project_name or project_dir.name)
    return {
        "project_slug": project_slug,
        "project_name": project_name,
        "project_store_path": str(project_dir.resolve()),
        "project_dir": project_dir.resolve(),
        "assignee": str(maestro_meta.get("assignee", "")).strip(),
        "superintendent": str(maestro_meta.get("superintendent", "")).strip(),
        "telegram_bot_username": str(maestro_meta.get("telegram_bot_username", "")).strip(),
        "telegram_bot_display_name": str(maestro_meta.get("telegram_bot_display_name", "")).strip(),
        "model": str(maestro_meta.get("model", "")).strip(),
    }


def _resolve_project_entry(store_root: Path, requested: str) -> dict[str, Any] | None:
    requested_text = str(requested or "").strip()
    if not requested_text:
        return None
    requested_slug = slugify(requested_text)
    for project_dir in discover_project_dirs(store_root):
        entry = _project_store_entry(project_dir)
        slug = str(entry.get("project_slug", "")).strip()
        name = str(entry.get("project_name", "")).strip()
        if slug == requested_text or slug == requested_slug or name.lower() == requested_text.lower():
            return entry
    return None


def _save_project_metadata(project_dir: Path, **fields: Any) -> None:
    payload = _load_project_json(project_dir)
    maestro_meta = payload.get(_PROJECT_METADATA_KEY) if isinstance(payload.get(_PROJECT_METADATA_KEY), dict) else {}
    if not isinstance(maestro_meta, dict):
        maestro_meta = {}

    changed = False
    for key, raw_value in fields.items():
        value = str(raw_value or "").strip()
        if not value:
            continue
        if maestro_meta.get(key) == value:
            continue
        maestro_meta[key] = value
        changed = True

    if not changed:
        return

    payload[_PROJECT_METADATA_KEY] = maestro_meta
    save_json(project_dir / "project.json", payload)


def run_set_commander_model(
    *,
    model: str,
    api_key: str | None = None,
    skip_remote_validation: bool = False,
    allow_openclaw_override: bool = False,
    store_override: str | None = None,
) -> int:
    selected_model = canonicalize_model(model)
    provider_env_key = provider_env_key_for_model(selected_model)
    if not provider_env_key:
        console.print(f"[red]Unsupported model: {selected_model}[/]")
        return 1

    config, config_path = _load_openclaw_config()
    safe_override, override_message = ensure_openclaw_override_allowed(
        config,
        allow_override=allow_openclaw_override,
    )
    if not safe_override:
        console.print(f"[red]{override_message}[/]")
        return 1

    selected_key, ok = _resolve_selected_key(
        config=config,
        provider_env_key=provider_env_key,
        api_key=api_key,
        skip_remote_validation=skip_remote_validation,
    )
    if not ok:
        return 1

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    commander = next(
        (
            item for item in agent_list
            if isinstance(item, dict) and str(item.get("id", "")).strip() == "maestro-company"
        ),
        None,
    )
    if not isinstance(commander, dict):
        console.print("[red]Commander agent 'maestro-company' not found.[/]")
        return 1

    previous_model = str(commander.get("model", "")).strip()
    commander["model"] = selected_model
    commander["default"] = True
    for item in agent_list:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id", "")).strip()
        if agent_id == "maestro-company":
            continue
        if _is_maestro_managed_agent(agent_id) and bool(item.get("default")):
            item["default"] = False

    if not isinstance(config.get("env"), dict):
        config["env"] = {}
    config["env"][provider_env_key] = selected_key
    save_json(config_path, config)

    store_root = resolve_fleet_store_root(store_override)
    gemini_key = str(config.get("env", {}).get("GEMINI_API_KEY", "")).strip() if isinstance(config.get("env"), dict) else ""
    _write_workspace_env(
        workspace_path=str(commander.get("workspace", "")).strip(),
        store_path=str(store_root),
        provider_env_key=provider_env_key,
        provider_key=selected_key,
        gemini_key=gemini_key,
        agent_role="company",
    )

    restart_ok, restart_detail = _restart_openclaw_gateway()
    console.print(
        Panel(
            "\n".join([
                "Commander model updated",
                f"Before: {previous_model or 'unknown'}",
                f"After: {selected_model}",
                f"Provider key: {provider_env_key}",
                f"Gateway reload: {'OK' if restart_ok else 'FAILED'}",
                restart_detail,
            ]),
            title="maestro-fleet commander set-model",
            border_style="cyan" if restart_ok else "red",
        )
    )
    return 0 if restart_ok else 1


def run_set_project_model(
    *,
    project: str,
    model: str,
    api_key: str | None = None,
    skip_remote_validation: bool = False,
    allow_openclaw_override: bool = False,
    store_override: str | None = None,
) -> int:
    requested = str(project or "").strip()
    if not requested:
        console.print("[red]Project slug/name is required.[/]")
        return 1

    selected_model = canonicalize_model(model)
    provider_env_key = provider_env_key_for_model(selected_model)
    if not provider_env_key:
        console.print(f"[red]Unsupported model: {selected_model}[/]")
        return 1

    store_root = resolve_fleet_store_root(store_override)
    matched = _resolve_project_entry(store_root, requested)
    requested_slug = slugify(requested)
    resolved_slug = str(matched.get("project_slug", "")).strip() if isinstance(matched, dict) else requested_slug
    if not resolved_slug:
        console.print(f"[red]Could not resolve project: {requested}[/]")
        return 1

    config, config_path = _load_openclaw_config()
    safe_override, override_message = ensure_openclaw_override_allowed(
        config,
        allow_override=allow_openclaw_override,
    )
    if not safe_override:
        console.print(f"[red]{override_message}[/]")
        return 1

    selected_key, ok = _resolve_selected_key(
        config=config,
        provider_env_key=provider_env_key,
        api_key=api_key,
        skip_remote_validation=skip_remote_validation,
    )
    if not ok:
        return 1

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    target_agent_id = f"maestro-project-{resolved_slug}"
    project_agent = next(
        (
            item for item in agent_list
            if isinstance(item, dict) and str(item.get("id", "")).strip() == target_agent_id
        ),
        None,
    )
    if not isinstance(project_agent, dict):
        console.print(f"[red]Project agent not found: {target_agent_id}[/]")
        return 1

    previous_model = str(project_agent.get("model", "")).strip()
    project_agent["model"] = selected_model

    if not isinstance(config.get("env"), dict):
        config["env"] = {}
    config["env"][provider_env_key] = selected_key
    save_json(config_path, config)

    project_store_path = str(matched.get("project_store_path", "")).strip() if isinstance(matched, dict) else str((store_root / resolved_slug).resolve())
    gemini_key = str(config.get("env", {}).get("GEMINI_API_KEY", "")).strip() if isinstance(config.get("env"), dict) else ""
    _write_workspace_env(
        workspace_path=str(project_agent.get("workspace", "")).strip(),
        store_path=project_store_path,
        provider_env_key=provider_env_key,
        provider_key=selected_key,
        gemini_key=gemini_key,
        agent_role="project",
        project_slug=resolved_slug,
    )
    if isinstance(matched, dict):
        project_dir = matched.get("project_dir")
        if isinstance(project_dir, Path):
            _save_project_metadata(project_dir, model=selected_model)

    restart_ok, restart_detail = _restart_openclaw_gateway()
    console.print(
        Panel(
            "\n".join([
                "Project model updated",
                f"Project: {resolved_slug}",
                f"Before: {previous_model or 'unknown'}",
                f"After: {selected_model}",
                f"Provider key: {provider_env_key}",
                f"Gateway reload: {'OK' if restart_ok else 'FAILED'}",
                restart_detail,
            ]),
            title="maestro-fleet project set-model",
            border_style="cyan" if restart_ok else "red",
        )
    )
    return 0 if restart_ok else 1


def run_set_project_telegram(
    *,
    project: str,
    telegram_token: str,
    pairing_code: str | None = None,
    skip_remote_validation: bool = False,
    allow_openclaw_override: bool = False,
    store_override: str | None = None,
) -> int:
    requested = str(project or "").strip()
    if not requested:
        console.print("[red]Project slug/name is required.[/]")
        return 1

    token = str(telegram_token or "").strip()
    if not token:
        console.print("[red]Telegram token is required.[/]")
        return 1

    store_root = resolve_fleet_store_root(store_override)
    matched = _resolve_project_entry(store_root, requested)
    requested_slug = slugify(requested)
    resolved_slug = str(matched.get("project_slug", "")).strip() if isinstance(matched, dict) else requested_slug
    if not resolved_slug:
        console.print(f"[red]Could not resolve project: {requested}[/]")
        return 1

    config, config_path = _load_openclaw_config()
    safe_override, override_message = ensure_openclaw_override_allowed(
        config,
        allow_override=allow_openclaw_override,
    )
    if not safe_override:
        console.print(f"[red]{override_message}[/]")
        return 1

    username = ""
    display_name = ""
    if not skip_remote_validation:
        ok, username, display_name, detail = _validate_telegram_token(token)
        if not ok:
            console.print(f"[red]Telegram token validation failed: {detail}[/]")
            return 1

    if not isinstance(config.get("channels"), dict):
        config["channels"] = {}
    channels = config["channels"]
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        telegram = {"enabled": True, "accounts": {}}
        channels["telegram"] = telegram
    if not isinstance(telegram.get("accounts"), dict):
        telegram["accounts"] = {}
    telegram["enabled"] = True

    agent_id = f"maestro-project-{resolved_slug}"
    account = telegram["accounts"].get(agent_id)
    if not isinstance(account, dict):
        account = {}
        telegram["accounts"][agent_id] = account

    account["botToken"] = token
    account["dmPolicy"] = "pairing"
    account["groupPolicy"] = "allowlist"
    account["streamMode"] = "partial"

    binding_changes = ensure_telegram_account_bindings(config)
    save_json(config_path, config)

    if isinstance(matched, dict):
        project_dir = matched.get("project_dir")
        if isinstance(project_dir, Path):
            _save_project_metadata(
                project_dir,
                telegram_bot_username=username,
                telegram_bot_display_name=display_name,
            )

    pairing_result = "not requested"
    pairing_ok = True
    clean_pairing_code = str(pairing_code or "").strip()
    if clean_pairing_code:
        pairing_ok, pairing_result = _approve_telegram_pairing_code(clean_pairing_code)

    restart_ok, restart_detail = _restart_openclaw_gateway()
    ok = restart_ok and pairing_ok
    console.print(
        Panel(
            "\n".join([
                "Project Telegram binding updated",
                f"Project: {resolved_slug}",
                f"Agent: {agent_id}",
                f"Validated bot username: @{username}" if username else "Validated bot username: skipped",
                f"Validated bot display: {display_name}" if display_name else "Validated bot display: skipped",
                (
                    "Config bindings: " + ", ".join(binding_changes)
                    if binding_changes else "Config bindings: no new routing entries needed"
                ),
                f"Pairing: {'OK' if pairing_ok else 'FAILED'} ({pairing_result})",
                f"Gateway reload: {'OK' if restart_ok else 'FAILED'}",
                restart_detail,
            ]),
            title="maestro-fleet project set-telegram",
            border_style="cyan" if ok else "red",
        )
    )
    return 0 if ok else 1
