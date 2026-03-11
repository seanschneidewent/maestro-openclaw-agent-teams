"""Fleet-native project provisioning entrypoints."""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_PROJECT_MODEL,
    PROJECT_MODEL_OPTIONS,
    canonicalize_model,
    model_label,
)

from .actions import create_project_node, project_control_payload
from .gateway import restart_openclaw_gateway_report
from .openclaw_runtime import ensure_openclaw_profile_env
from .state import resolve_fleet_store_root


_RUN_PURCHASE_DEPRECATED_WARNED = False
_LEGACY_PROVISIONING_MODULE: Any | None = None


def _legacy_provisioning_module() -> Any:
    global _LEGACY_PROVISIONING_MODULE
    if _LEGACY_PROVISIONING_MODULE is not None:
        return _LEGACY_PROVISIONING_MODULE

    try:
        from maestro.fleet.projects import provisioning as legacy_provisioning
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[4]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        try:
            from maestro.fleet.projects import provisioning as legacy_provisioning
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "maestro-fleet project create currently depends on legacy runtime modules in `maestro/`.\n"
                "Install root package too: pip install -e /absolute/path/to/repo"
            ) from exc

    _LEGACY_PROVISIONING_MODULE = legacy_provisioning
    return legacy_provisioning


def _load_openclaw_config(*args, **kwargs):
    return _legacy_provisioning_module()._load_openclaw_config(*args, **kwargs)


def _project_exists(*args, **kwargs):
    return _legacy_provisioning_module()._project_exists(*args, **kwargs)


def _mask_secret(*args, **kwargs):
    return _legacy_provisioning_module()._mask_secret(*args, **kwargs)


def _validate_api_key(*args, **kwargs):
    return _legacy_provisioning_module()._validate_api_key(*args, **kwargs)


def _validate_telegram_token(*args, **kwargs):
    return _legacy_provisioning_module()._validate_telegram_token(*args, **kwargs)


def _update_openclaw_for_project(*args, **kwargs):
    return _legacy_provisioning_module()._update_openclaw_for_project(*args, **kwargs)


def _restart_openclaw_gateway(*args, **kwargs):
    return restart_openclaw_gateway_report(*args, **kwargs)


def _complete_telegram_pairing(*args, **kwargs):
    return _legacy_provisioning_module()._complete_telegram_pairing(*args, **kwargs)


def _current_command_center_url(*args, **kwargs):
    return _legacy_provisioning_module()._current_command_center_url(*args, **kwargs)


def run_project_create(
    *,
    project_name: str | None = None,
    assignee: str | None = None,
    superintendent: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    telegram_token: str | None = None,
    pairing_code: str | None = None,
    store_override: str | None = None,
    dry_run: bool = False,
    json_output: bool = False,
    non_interactive: bool = False,
    skip_remote_validation: bool = False,
    allow_openclaw_override: bool = False,
) -> int:
    ensure_openclaw_profile_env()
    legacy = _legacy_provisioning_module()

    _, config_path = _load_openclaw_config()
    if not config_path.exists():
        legacy.console.print("[red]OpenClaw config not found. Run maestro-setup first.[/]")
        return 1

    config, _ = _load_openclaw_config()
    safe_override, override_message = legacy.ensure_openclaw_override_allowed(
        config,
        allow_override=allow_openclaw_override,
    )
    if not safe_override:
        legacy.console.print(f"[red]{override_message}[/]")
        return 1

    company = legacy._resolve_company_agent(config)
    company_model = canonicalize_model(company.get("model"), fallback=DEFAULT_PROJECT_MODEL)
    store_root = resolve_fleet_store_root(store_override)

    if not project_name:
        if non_interactive:
            legacy.console.print("[red]Missing --project-name[/]")
            return 1
        project_name = legacy.Prompt.ask("Project name").strip()
    if not assignee:
        if non_interactive:
            legacy.console.print("[red]Missing --assignee[/]")
            return 1
        assignee = legacy.Prompt.ask("Assignee (employee owner)").strip()

    project_name = project_name.strip()
    assignee = assignee.strip()
    if not project_name or not assignee:
        legacy.console.print("[red]Project name and assignee are required.[/]")
        return 1

    project_slug = legacy.slugify(project_name)
    if (store_root / "project.json").exists():
        legacy.console.print(
            "[red]Fleet store root cannot be a single-project store.[/]"
        )
        legacy.console.print(
            "[bold white]Next step:[/] Point the commander workspace `MAESTRO_STORE` at the parent directory that contains project folders, then retry `maestro-fleet project create`."
        )
        return 1
    if _project_exists(store_root, project_slug):
        legacy.console.print(f"[red]Project slug already exists: {project_slug}[/]")
        return 1

    selected_model = canonicalize_model(model)
    if not selected_model and not non_interactive:
        lines = [f"1. Inherit company default ({company_model})"]
        for choice, model_name in PROJECT_MODEL_OPTIONS[1:]:
            label = model_label(model_name)
            lines.append(f"{choice}. {label}")
        legacy.console.print(legacy.Panel("\n".join([
            "Select model for this project maestro:",
            *lines,
        ]), title="Model Selection"))
        choice = legacy.Prompt.ask("Choice", choices=[item[0] for item in PROJECT_MODEL_OPTIONS], default="1")
        model_choice = next((model_name for key, model_name in PROJECT_MODEL_OPTIONS if key == choice), "inherit")
        selected_model = company_model if model_choice == "inherit" else canonicalize_model(model_choice, fallback=company_model)
    elif not selected_model:
        selected_model = company_model

    provider_env_key = legacy.provider_env_key_for_model(selected_model)
    config_env = config.get("env", {}) if isinstance(config.get("env"), dict) else {}
    selected_api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else ""

    if provider_env_key and not selected_api_key:
        existing = config_env.get(provider_env_key)
        existing_key = existing.strip() if isinstance(existing, str) else ""
        if existing_key and not non_interactive:
            use_existing = legacy.Confirm.ask(
                f"Use existing {provider_env_key} from OpenClaw config ({_mask_secret(existing_key)})?",
                default=True,
            )
            if use_existing:
                selected_api_key = existing_key
        elif existing_key:
            selected_api_key = existing_key

    if provider_env_key and not selected_api_key:
        if non_interactive:
            legacy.console.print(f"[red]Missing API key for {provider_env_key}[/]")
            return 1
        prompt_label = (
            "Paste GEMINI_API_KEY (Gemini API or Vertex AI key)"
            if provider_env_key == "GEMINI_API_KEY"
            else f"Paste {provider_env_key}"
        )
        selected_api_key = legacy.Prompt.ask(prompt_label).strip()

    if provider_env_key and selected_api_key and not skip_remote_validation:
        ok, detail = _validate_api_key(provider_env_key, selected_api_key)
        if not ok:
            if non_interactive:
                legacy.console.print(f"[red]API key validation failed: {detail}[/]")
                return 1
            proceed = legacy.Confirm.ask(f"API key validation failed ({detail}). Continue anyway?", default=False)
            if not proceed:
                return 1

    selected_telegram_token = telegram_token.strip() if isinstance(telegram_token, str) and telegram_token.strip() else ""
    if not selected_telegram_token:
        if non_interactive:
            legacy.console.print("[red]Missing --telegram-token[/]")
            return 1
        legacy.console.print(legacy.Panel(
            "Create a dedicated Telegram bot for this Project Maestro:\n"
            "1) Open @BotFather\n"
            "2) /newbot\n"
            "3) Paste token below",
            title="Telegram Bot",
        ))
        selected_telegram_token = legacy.Prompt.ask("Project Telegram bot token").strip()

    bot_username = ""
    bot_display_name = ""
    if not skip_remote_validation:
        validation = _validate_telegram_token(selected_telegram_token)
        if len(validation) == 4:
            ok, bot_username, bot_display_name, detail = validation
        else:
            ok, bot_username, detail = validation  # type: ignore[misc]
            bot_display_name = bot_username
        if not ok:
            if non_interactive:
                legacy.console.print(f"[red]Telegram token validation failed: {detail}[/]")
                return 1
            proceed = legacy.Confirm.ask(f"Telegram token validation failed ({detail}). Continue anyway?", default=False)
            if not proceed:
                return 1
        else:
            legacy.console.print(f"[green]Telegram verified: @{bot_username}[/]")

    planned_store_path = (store_root / project_slug).resolve()
    result = create_project_node(
        store_root=store_root,
        project_name=project_name,
        project_slug=project_slug,
        ingest_input_root=None,
        superintendent=superintendent or assignee,
        assignee=assignee,
        telegram_bot_username=bot_username,
        telegram_bot_display_name=bot_display_name,
        register_agent=True,
        agent_model=selected_model,
        dry_run=dry_run,
    )
    if not result.get("ok"):
        legacy.console.print(f"[red]Failed to create project maestro: {result}[/]")
        return 1

    project_entry = (
        result.get("final_registry_entry", {})
        if isinstance(result.get("final_registry_entry"), dict)
        else result.get("project", {})
        if isinstance(result.get("project"), dict)
        else {}
    )
    project_store_path = Path(str(project_entry.get("project_store_path", planned_store_path))).resolve()
    agent_registration = result.get("agent_registration", {}) if isinstance(result.get("agent_registration"), dict) else {}
    workspace_path = (
        Path(str(agent_registration.get("workspace", ""))).expanduser()
        if agent_registration.get("workspace")
        else legacy.openclaw_workspace_root(
            enforce_profile=True,
        ) / "projects" / project_slug
    )

    config, _ = _load_openclaw_config()
    openclaw_update = _update_openclaw_for_project(
        config=config,
        config_path=config_path,
        project_slug=project_slug,
        project_name=project_name,
        model=selected_model,
        provider_env_key=provider_env_key,
        provider_key=selected_api_key,
        telegram_token=selected_telegram_token,
        telegram_bot_username=bot_username,
        telegram_bot_display_name=bot_display_name,
        assignee=assignee,
        project_workspace=workspace_path,
        project_store_path=project_store_path,
        dry_run=dry_run,
    )
    gateway_restart = _restart_openclaw_gateway(dry_run=dry_run)
    if gateway_restart.get("ok"):
        legacy.console.print("[green]OpenClaw gateway restarted with project bot config.[/]")
    else:
        legacy.console.print(f"[yellow]Could not restart OpenClaw gateway automatically: {gateway_restart.get('detail', '')}[/]")
        legacy.console.print("[bold white]Run:[/] openclaw gateway restart")

    pairing_result = _complete_telegram_pairing(
        bot_username=bot_username,
        pairing_code=pairing_code,
        non_interactive=non_interactive,
        dry_run=dry_run,
    )

    control = project_control_payload(store_root, project_slug=project_slug)
    output = {
        "ok": True,
        "dry_run": dry_run,
        "project_slug": project_slug,
        "project_name": project_name,
        "assignee": assignee,
        "telegram_bot_username": bot_username,
        "telegram_bot_display_name": bot_display_name,
        "store_root": str(store_root),
        "project_store_path": str(project_store_path),
        "model": selected_model,
        "provider_env_key": provider_env_key,
        "openclaw_update": openclaw_update,
        "gateway_restart": gateway_restart,
        "telegram_pairing": pairing_result,
        "ingest_command": control.get("ingest", {}).get("command") if isinstance(control.get("ingest"), dict) else "",
        "command_center_url": _current_command_center_url(),
        "project_create_command": "maestro-fleet project create",
    }

    if json_output:
        legacy.console.print_json(json.dumps(output))
        return 0

    legacy.console.print(legacy.Panel(
        "\n".join([
            "Project Maestro provisioned",
            f"Project: {project_name} ({project_slug})",
            f"Assignee: {assignee}",
            f"Store: {project_store_path}",
            f"Model: {selected_model}",
            f"Gateway Reload: {'OK' if gateway_restart.get('ok') else 'Needs manual restart'}",
            (
                f"Telegram Pairing: {'Approved' if pairing_result.get('approved') else 'Pending'}"
                if isinstance(pairing_result, dict) else "Telegram Pairing: Pending"
            ),
            f"Command Center: {output['command_center_url']}",
            "",
            "Ingest command:",
            output["ingest_command"] or "maestro ingest \"/abs/path/to/pdfs\"",
        ]),
        title="maestro-fleet project create",
        border_style="cyan",
    ))
    return 0


def run_purchase(*args, **kwargs):
    global _RUN_PURCHASE_DEPRECATED_WARNED
    if not _RUN_PURCHASE_DEPRECATED_WARNED:
        warnings.warn(
            "maestro_fleet.provisioning.run_purchase() is deprecated; use run_project_create() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        _RUN_PURCHASE_DEPRECATED_WARNED = True
    return run_project_create(*args, **kwargs)


__all__ = ["run_project_create", "run_purchase"]
