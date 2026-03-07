"""Fleet project provisioning helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ...control_plane import (
    create_project_node,
    ensure_telegram_account_bindings,
    onboard_project_store,
    project_control_payload,
    resolve_network_urls,
    sync_fleet_registry,
)
from ...fleet_constants import FLEET_PROFILE, MODEL_LABELS
from ...install_state import resolve_fleet_store_root
from ...openclaw_guard import ensure_openclaw_override_allowed
from ...openclaw_profile import (
    openclaw_config_path,
    openclaw_workspace_root,
    prepend_openclaw_profile_args,
    resolve_openclaw_profile,
)
from ...utils import load_json, save_json, slugify
from ...workspace_templates import (
    provider_env_key_for_model,
    render_project_agents_md,
    render_project_tools_md,
    render_workspace_awareness_md,
    render_workspace_env,
    should_remove_generic_project_bootstrap,
    should_refresh_generic_project_file,
)


console = Console()

PROJECT_MODEL_OPTIONS = (
    ("1", "inherit"),
    ("2", "openai/gpt-5.4"),
    ("3", "google/gemini-3-pro-preview"),
    ("4", "anthropic/claude-opus-4-6"),
)

VERTEX_API_KEY_RE = re.compile(r"^AIza[0-9A-Za-z_-]{24,}$")


def _looks_like_vertex_api_key(value: str) -> bool:
    return bool(VERTEX_API_KEY_RE.match(str(value or "").strip()))


def _looks_like_google_access_token(value: str) -> bool:
    token = str(value or "").strip()
    return token.startswith("ya29.") or token.startswith("eyJ")


def _mask_secret(value: str) -> str:
    text = value.strip()
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def _load_openclaw_config(home_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    config_path = openclaw_config_path(
        home_dir=home_dir,
        enforce_profile=True,
    )
    config = load_json(config_path, default={})
    if not isinstance(config, dict):
        config = {}
    return config, config_path


def _fleet_state_dir() -> Path:
    base = (Path.home() / ".maestro" / "fleet").resolve()
    profile = resolve_openclaw_profile(default_profile=FLEET_PROFILE)
    if profile and profile != FLEET_PROFILE:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", profile).strip("._-") or "profile"
        return base / "profiles" / safe
    return base


def _current_command_center_port(default_port: int = 3000) -> int:
    pid_path = _fleet_state_dir() / "serve.pid.json"
    payload = load_json(pid_path, default={})
    if not isinstance(payload, dict):
        payload = {}
    port = int(payload.get("port", 0) or 0)
    if port <= 0:
        port = int(default_port)
    return port


def _current_command_center_url(default_port: int = 3000) -> str:
    port = _current_command_center_port(default_port)
    network = resolve_network_urls(web_port=port, route_path="/command-center")
    return str(network.get("recommended_url", f"http://localhost:{port}/command-center"))


def _resolve_company_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    company = next(
        (item for item in agent_list if isinstance(item, dict) and item.get("id") == "maestro-company"),
        None,
    )
    if isinstance(company, dict):
        return company
    default_agent = next(
        (item for item in agent_list if isinstance(item, dict) and item.get("default")),
        None,
    )
    return default_agent if isinstance(default_agent, dict) else {}


def _validate_api_key(provider_env_key: str, key: str) -> tuple[bool, str]:
    key = key.strip()
    if not key:
        return False, "Key is empty"
    try:
        if provider_env_key == "OPENAI_API_KEY":
            response = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            return response.status_code == 200, f"OpenAI status={response.status_code}"
        if provider_env_key == "ANTHROPIC_API_KEY":
            response = httpx.get(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=10,
            )
            return response.status_code != 401, f"Anthropic status={response.status_code}"
        if provider_env_key == "GEMINI_API_KEY":
            if _looks_like_google_access_token(key):
                token_response = httpx.get(
                    "https://oauth2.googleapis.com/tokeninfo",
                    params={"access_token": key},
                    timeout=10,
                )
                if token_response.status_code == 200:
                    return True, f"Vertex token status={token_response.status_code}"
            response = httpx.get(
                f"https://generativelanguage.googleapis.com/v1/models?key={key}",
                timeout=10,
            )
            if response.status_code == 403 and _looks_like_vertex_api_key(key):
                return True, "Vertex API key accepted (Developer API check returned 403)"
            if response.status_code in {401, 403}:
                vertex_response = httpx.post(
                    (
                        "https://aiplatform.googleapis.com/v1/publishers/google/models/"
                        f"gemini-2.5-flash-lite:generateContent?key={key}"
                    ),
                    json={
                        "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                        "generationConfig": {"maxOutputTokens": 1},
                    },
                    timeout=10,
                )
                if vertex_response.status_code == 200:
                    return True, f"Vertex status={vertex_response.status_code}"
                return False, f"Gemini status={response.status_code}; Vertex status={vertex_response.status_code}"
            return response.status_code == 200, f"Gemini status={response.status_code}"
    except Exception as exc:
        return False, str(exc)
    return False, "Unsupported provider"


def _validate_telegram_token(token: str) -> tuple[bool, str, str, str]:
    try:
        response = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    except Exception as exc:
        return False, "", "", f"Network error: {exc}"

    if response.status_code != 200:
        return False, "", "", f"Telegram status={response.status_code}"
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("ok"):
        return False, "", "", "Telegram API did not return ok=true"
    result = payload.get("result", {})
    username = result.get("username", "") if isinstance(result, dict) else ""
    display_name = result.get("first_name", "") if isinstance(result, dict) else ""
    return True, str(username), str(display_name), "validated"


def _project_exists(registry: dict[str, Any], slug: str) -> bool:
    projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    for item in projects:
        if not isinstance(item, dict):
            continue
        if str(item.get("project_slug", "")).strip().lower() == slug.lower():
            if str(item.get("status", "active")).lower() != "archived":
                return True
    return False


def _company_name(company_agent: dict[str, Any]) -> str:
    raw = str(company_agent.get("name", "")).strip()
    if raw.startswith("Maestro (") and raw.endswith(")"):
        inner = raw[len("Maestro ("):-1].strip()
        return inner or "Company"
    return raw or "Company"


def _update_openclaw_for_project(
    *,
    config: dict[str, Any],
    config_path: Path,
    project_slug: str,
    project_name: str,
    model: str,
    provider_env_key: str | None,
    provider_key: str | None,
    telegram_token: str,
    telegram_bot_username: str,
    telegram_bot_display_name: str,
    assignee: str,
    project_workspace: Path,
    project_store_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    if not isinstance(config.get("env"), dict):
        config["env"] = {}
    env = config["env"]
    if provider_env_key and provider_key:
        env[provider_env_key] = provider_key.strip()

    if not isinstance(config.get("channels"), dict):
        config["channels"] = {}
    channels = config["channels"]
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        telegram = {"enabled": True, "accounts": {}}
        channels["telegram"] = telegram
    if not isinstance(telegram.get("accounts"), dict):
        telegram["accounts"] = {}

    agent_id = f"maestro-project-{project_slug}"
    telegram["accounts"][agent_id] = {
        "botToken": telegram_token.strip(),
        "dmPolicy": "pairing",
        "groupPolicy": "allowlist",
        "streamMode": "partial",
    }
    binding_changes = ensure_telegram_account_bindings(config)

    workspace_env = render_workspace_env(
        store_path=str(project_store_path),
        provider_env_key=provider_env_key,
        provider_key=provider_key,
        gemini_key=env.get("GEMINI_API_KEY") if isinstance(env.get("GEMINI_API_KEY"), str) else None,
        agent_role="project",
    )
    metadata = {
        "project_slug": project_slug,
        "project_name": project_name,
        "assignee": assignee,
        "model": model,
        "provider_env_key": provider_env_key or "",
        "telegram_token_hash": hashlib.sha256(telegram_token.encode()).hexdigest(),
        "telegram_bot_username": telegram_bot_username.strip(),
        "telegram_bot_display_name": telegram_bot_display_name.strip(),
    }

    if not dry_run:
        save_json(config_path, config)
        project_workspace.mkdir(parents=True, exist_ok=True)
        (project_workspace / ".env").write_text(workspace_env, encoding="utf-8")
        urls = resolve_network_urls(
            web_port=_current_command_center_port(),
            route_path=f"/{project_slug}/",
        )
        (project_workspace / "AWARENESS.md").write_text(
            render_workspace_awareness_md(
                model=model,
                preferred_url=str(urls.get("recommended_url", "")).strip(),
                local_url=str(urls.get("localhost_url", "")).strip(),
                tailnet_url=str(urls.get("tailnet_url") or "").strip(),
                store_root=project_store_path,
                surface_label="Workspace",
                generated_by="maestro purchase",
            ),
            encoding="utf-8",
        )
        agents_path = project_workspace / "AGENTS.md"
        current_agents = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        if (not agents_path.exists()) or should_refresh_generic_project_file("AGENTS.md", current_agents):
            agents_path.write_text(render_project_agents_md(), encoding="utf-8")
        tools_path = project_workspace / "TOOLS.md"
        current_tools = tools_path.read_text(encoding="utf-8") if tools_path.exists() else ""
        if (not tools_path.exists()) or should_refresh_generic_project_file("TOOLS.md", current_tools):
            tools_path.write_text(
                render_project_tools_md(provider_env_key_for_model(model)),
                encoding="utf-8",
            )
        bootstrap_path = project_workspace / "BOOTSTRAP.md"
        if bootstrap_path.exists():
            bootstrap_content = bootstrap_path.read_text(encoding="utf-8")
            if should_remove_generic_project_bootstrap(bootstrap_content):
                bootstrap_path.unlink()
        save_json(project_workspace / "project_agent.json", metadata)

    return {
        "agent_id": agent_id,
        "workspace_env_written": not dry_run,
        "metadata_written": not dry_run,
        "binding_changes": binding_changes,
    }


def _approve_pairing_code(pairing_code: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            prepend_openclaw_profile_args(
                ["openclaw", "pairing", "approve", "telegram", pairing_code],
            ),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError:
        return False, "openclaw CLI not found on PATH"
    except Exception as exc:
        return False, str(exc)

    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        return True, output or "Pairing approved"

    lowered = output.lower()
    if "already" in lowered and "approve" in lowered:
        return True, output
    return False, output or f"openclaw pairing approve exited with status {result.returncode}"


def _complete_telegram_pairing(
    *,
    bot_username: str,
    pairing_code: str | None,
    non_interactive: bool,
    dry_run: bool,
) -> dict[str, Any]:
    selected_code = pairing_code.strip() if isinstance(pairing_code, str) else ""

    if not selected_code and non_interactive:
        return {"approved": False, "skipped": True, "reason": "no_pairing_code"}

    if not selected_code:
        bot_ref = f"@{bot_username}" if bot_username else "the project bot"
        console.print(Panel(
            "Telegram Access Pairing\n\n"
            f"1) Open {bot_ref} and send any message\n"
            "2) Copy the pairing code from the bot response\n"
            "3) Paste it below to approve access now",
            title="Telegram Pairing",
            border_style="cyan",
        ))
        selected_code = Prompt.ask("Pairing code (press Enter to skip)", default="").strip()
        if not selected_code:
            return {"approved": False, "skipped": True, "reason": "user_skipped"}

    if dry_run:
        return {"approved": True, "skipped": False, "dry_run": True, "pairing_code": selected_code}

    ok, detail = _approve_pairing_code(selected_code)
    if ok:
        console.print("[green]Telegram access pairing approved.[/]")
    else:
        console.print(f"[yellow]Telegram pairing not approved yet: {detail}[/]")
        console.print(f"[bold white]Run when ready:[/] openclaw pairing approve telegram {selected_code}")

    return {
        "approved": ok,
        "skipped": False,
        "pairing_code": selected_code,
        "detail": detail,
    }


def _restart_openclaw_gateway(*, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True, "detail": "Skipped gateway restart in dry-run mode"}

    try:
        restart = subprocess.run(
            prepend_openclaw_profile_args(
                ["openclaw", "gateway", "restart"],
            ),
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "detail": "openclaw CLI not found on PATH"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}

    output = (restart.stdout or restart.stderr or "").strip()
    if restart.returncode == 0:
        return {"ok": True, "detail": output or "Gateway restarted"}

    start = subprocess.run(
        prepend_openclaw_profile_args(
            ["openclaw", "gateway", "start"],
        ),
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    start_output = (start.stdout or start.stderr or "").strip()
    if start.returncode == 0:
        return {"ok": True, "detail": start_output or "Gateway started"}
    return {"ok": False, "detail": output or start_output or "Failed to restart gateway"}


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
    _, config_path = _load_openclaw_config()
    if not config_path.exists():
        console.print("[red]OpenClaw config not found. Run maestro-setup first.[/]")
        return 1

    config, _ = _load_openclaw_config()
    safe_override, override_message = ensure_openclaw_override_allowed(
        config,
        allow_override=allow_openclaw_override,
    )
    if not safe_override:
        console.print(f"[red]{override_message}[/]")
        return 1
    company = _resolve_company_agent(config)
    company_model = str(company.get("model", "google/gemini-3-pro-preview")).strip()
    store_root = resolve_fleet_store_root(store_override)
    registry = sync_fleet_registry(store_root, dry_run=dry_run)

    if not project_name:
        if non_interactive:
            console.print("[red]Missing --project-name[/]")
            return 1
        project_name = Prompt.ask("Project name").strip()
    if not assignee:
        if non_interactive:
            console.print("[red]Missing --assignee[/]")
            return 1
        assignee = Prompt.ask("Assignee (employee owner)").strip()

    project_name = project_name.strip()
    assignee = assignee.strip()
    if not project_name or not assignee:
        console.print("[red]Project name and assignee are required.[/]")
        return 1

    project_slug = slugify(project_name)
    if _project_exists(registry, project_slug):
        console.print(f"[red]Project slug already exists: {project_slug}[/]")
        return 1

    # Model selection
    selected_model = model.strip() if isinstance(model, str) and model.strip() else ""
    if not selected_model and not non_interactive:
        lines = [f"1. Inherit company default ({company_model})"]
        for choice, model_name in PROJECT_MODEL_OPTIONS[1:]:
            label = MODEL_LABELS.get(model_name, model_name)
            lines.append(f"{choice}. {label}")
        console.print(Panel("\n".join([
            "Select model for this project maestro:",
            *lines,
        ]), title="Model Selection"))
        choice = Prompt.ask("Choice", choices=[item[0] for item in PROJECT_MODEL_OPTIONS], default="1")
        model_choice = next((model_name for key, model_name in PROJECT_MODEL_OPTIONS if key == choice), "inherit")
        selected_model = company_model if model_choice == "inherit" else model_choice
    elif not selected_model:
        selected_model = company_model

    provider_env_key = provider_env_key_for_model(selected_model)
    config_env = config.get("env", {}) if isinstance(config.get("env"), dict) else {}
    selected_api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else ""

    if provider_env_key and not selected_api_key:
        existing = config_env.get(provider_env_key)
        existing_key = existing.strip() if isinstance(existing, str) else ""
        if existing_key and not non_interactive:
            use_existing = Confirm.ask(
                f"Use existing {provider_env_key} from OpenClaw config ({_mask_secret(existing_key)})?",
                default=True,
            )
            if use_existing:
                selected_api_key = existing_key
        elif existing_key:
            selected_api_key = existing_key

    if provider_env_key and not selected_api_key:
        if non_interactive:
            console.print(f"[red]Missing API key for {provider_env_key}[/]")
            return 1
        prompt_label = (
            "Paste GEMINI_API_KEY (Gemini API or Vertex AI key)"
            if provider_env_key == "GEMINI_API_KEY"
            else f"Paste {provider_env_key}"
        )
        selected_api_key = Prompt.ask(prompt_label).strip()

    if provider_env_key and selected_api_key and not skip_remote_validation:
        ok, detail = _validate_api_key(provider_env_key, selected_api_key)
        if not ok:
            if non_interactive:
                console.print(f"[red]API key validation failed: {detail}[/]")
                return 1
            proceed = Confirm.ask(f"API key validation failed ({detail}). Continue anyway?", default=False)
            if not proceed:
                return 1

    # Telegram
    selected_telegram_token = telegram_token.strip() if isinstance(telegram_token, str) and telegram_token.strip() else ""
    if not selected_telegram_token:
        if non_interactive:
            console.print("[red]Missing --telegram-token[/]")
            return 1
        console.print(Panel(
            "Create a dedicated Telegram bot for this Project Maestro:\n"
            "1) Open @BotFather\n"
            "2) /newbot\n"
            "3) Paste token below",
            title="Telegram Bot",
        ))
        selected_telegram_token = Prompt.ask("Project Telegram bot token").strip()

    bot_username = ""
    bot_display_name = ""
    if not skip_remote_validation:
        validation = _validate_telegram_token(selected_telegram_token)
        if len(validation) == 4:
            ok, bot_username, bot_display_name, detail = validation
        else:  # Backward-compat for monkeypatched tests returning legacy tuple.
            ok, bot_username, detail = validation  # type: ignore[misc]
            bot_display_name = bot_username
        if not ok:
            if non_interactive:
                console.print(f"[red]Telegram token validation failed: {detail}[/]")
                return 1
            proceed = Confirm.ask(f"Telegram token validation failed ({detail}). Continue anyway?", default=False)
            if not proceed:
                return 1
        else:
            console.print(f"[green]Telegram verified: @{bot_username}[/]")

    existing_project_root = (store_root / "project.json").exists()
    planned_store_path = store_root.resolve() if existing_project_root else (store_root / project_slug).resolve()

    if existing_project_root:
        result = onboard_project_store(
            store_root=store_root,
            source_path=str(store_root),
            project_name=project_name,
            project_slug=project_slug,
            ingest_input_root=None,
            superintendent=superintendent or assignee,
            assignee=assignee,
            register_agent=True,
            move_source=False,
            agent_model=selected_model,
            dry_run=dry_run,
        )
    else:
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
        console.print(f"[red]Failed to create project maestro: {result}[/]")
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
        else openclaw_workspace_root(
            enforce_profile=True,
        ) / "projects" / project_slug
    )

    # Reload latest config first so we don't clobber project-agent registration.
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
        console.print("[green]OpenClaw gateway restarted with project bot config.[/]")
    else:
        console.print(f"[yellow]Could not restart OpenClaw gateway automatically: {gateway_restart.get('detail', '')}[/]")
        console.print("[bold white]Run:[/] openclaw gateway restart")

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
        console.print_json(json.dumps(output))
        return 0

    console.print(Panel(
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
            f"Ingest command:",
            output["ingest_command"] or "maestro ingest \"/abs/path/to/pdfs\"",
        ]),
        title="maestro-fleet project create",
        border_style="cyan",
    ))
    return 0


def run_purchase(*args, **kwargs):
    return run_project_create(*args, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maestro-purchase",
        description="Provision a new project-specific Maestro agent",
    )
    parser.add_argument("--project-name")
    parser.add_argument("--assignee")
    parser.add_argument("--superintendent")
    parser.add_argument("--model")
    parser.add_argument("--api-key")
    parser.add_argument("--telegram-token")
    parser.add_argument("--pairing-code", help="Optional Telegram pairing code to auto-approve")
    parser.add_argument("--store", help="Override fleet store root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--skip-remote-validation", action="store_true")
    parser.add_argument("--allow-openclaw-override", action="store_true")
    return parser
