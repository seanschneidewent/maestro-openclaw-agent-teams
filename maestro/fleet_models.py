"""Fleet model-switch helpers for commander and project agents."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from .control_plane import sync_fleet_registry
from .fleet_deploy import _is_maestro_managed_agent, _validate_api_key
from .install_state import resolve_fleet_store_root
from .openclaw_guard import ensure_openclaw_override_allowed
from .openclaw_profile import (
    openclaw_config_path,
    prepend_openclaw_profile_args,
)
from .utils import load_json, save_json, slugify
from .workspace_templates import provider_env_key_for_model, render_workspace_env


console = Console()


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
    try:
        restart = subprocess.run(
            prepend_openclaw_profile_args(["openclaw", "gateway", "restart"]),
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
    except FileNotFoundError:
        return False, "openclaw CLI not found on PATH"
    except Exception as exc:
        return False, str(exc)

    output = (restart.stdout or restart.stderr or "").strip()
    if restart.returncode == 0:
        return True, output or "Gateway restarted"

    start = subprocess.run(
        prepend_openclaw_profile_args(["openclaw", "gateway", "start"]),
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    start_output = (start.stdout or start.stderr or "").strip()
    if start.returncode == 0:
        return True, start_output or "Gateway started"
    return False, output or start_output or "Failed to restart gateway"


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
    (workspace / ".env").write_text(payload, encoding="utf-8")


def run_set_commander_model(
    *,
    model: str,
    api_key: str | None = None,
    skip_remote_validation: bool = False,
    allow_openclaw_override: bool = False,
    store_override: str | None = None,
) -> int:
    selected_model = str(model or "").strip()
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

    selected_model = str(model or "").strip()
    provider_env_key = provider_env_key_for_model(selected_model)
    if not provider_env_key:
        console.print(f"[red]Unsupported model: {selected_model}[/]")
        return 1

    store_root = resolve_fleet_store_root(store_override)
    registry = sync_fleet_registry(store_root)
    projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    requested_slug = slugify(requested)
    matched = next(
        (
            item for item in projects
            if isinstance(item, dict) and (
                str(item.get("project_slug", "")).strip() == requested
                or str(item.get("project_slug", "")).strip() == requested_slug
                or str(item.get("project_name", "")).strip().lower() == requested.lower()
            )
        ),
        None,
    )
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
    )

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
