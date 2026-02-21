"""Project Maestro purchase/provisioning CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from .control_plane import (
    build_purchase_status,
    create_project_node,
    project_control_payload,
    resolve_network_urls,
    sync_fleet_registry,
)
from .install_state import resolve_fleet_store_root
from .license import LicenseError, generate_project_key, validate_project_key
from .utils import load_json, save_json, slugify
from .workspace_templates import provider_env_key_for_model, render_workspace_env


console = Console()

MODEL_CHOICES = {
    "1": ("inherit", None),
    "2": ("openai/gpt-5.2", "OPENAI_API_KEY"),
    "3": ("google/gemini-3-pro-preview", "GEMINI_API_KEY"),
    "4": ("anthropic/claude-opus-4-6", "ANTHROPIC_API_KEY"),
}

DEFAULT_PROJECT_NODE_PRICE_USD = 49


def _mask_secret(value: str) -> str:
    text = value.strip()
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def _load_openclaw_config(home_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    home = (home_dir or Path.home()).resolve()
    config_path = home / ".openclaw" / "openclaw.json"
    config = load_json(config_path, default={})
    if not isinstance(config, dict):
        config = {}
    return config, config_path


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
            response = httpx.get(
                f"https://generativelanguage.googleapis.com/v1/models?key={key}",
                timeout=10,
            )
            return response.status_code == 200, f"Gemini status={response.status_code}"
    except Exception as exc:
        return False, str(exc)
    return False, "Unsupported provider"


def _validate_telegram_token(token: str) -> tuple[bool, str, str]:
    try:
        response = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    except Exception as exc:
        return False, "", f"Network error: {exc}"

    if response.status_code != 200:
        return False, "", f"Telegram status={response.status_code}"
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("ok"):
        return False, "", "Telegram API did not return ok=true"
    result = payload.get("result", {})
    username = result.get("username", "") if isinstance(result, dict) else ""
    return True, str(username), "validated"


def _project_exists(registry: dict[str, Any], slug: str) -> bool:
    projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    for item in projects:
        if not isinstance(item, dict):
            continue
        if str(item.get("project_slug", "")).strip().lower() == slug.lower():
            if str(item.get("status", "active")).lower() != "archived":
                return True
    return False


def _billing_state_path(home_dir: Path | None = None) -> Path:
    home = (home_dir or Path.home()).resolve()
    return home / ".maestro" / "billing.json"


def _load_billing_state(home_dir: Path | None = None) -> dict[str, Any]:
    payload = load_json(_billing_state_path(home_dir), default={})
    return payload if isinstance(payload, dict) else {}


def _save_billing_state(state: dict[str, Any], home_dir: Path | None = None):
    save_json(_billing_state_path(home_dir), state)


def _company_name(company_agent: dict[str, Any]) -> str:
    raw = str(company_agent.get("name", "")).strip()
    if raw.startswith("Maestro (") and raw.endswith(")"):
        inner = raw[len("Maestro ("):-1].strip()
        return inner or "Company"
    return raw or "Company"


def _derive_company_id(company_agent: dict[str, Any]) -> str:
    seed = _company_name(company_agent).encode("utf-8")
    return f"CMP{hashlib.sha1(seed).hexdigest()[:8].upper()}"


def _derive_project_id(project_slug: str) -> str:
    return f"PRJ{hashlib.sha1(project_slug.encode('utf-8')).hexdigest()[:8].upper()}"


def _ensure_card_on_file(*, non_interactive: bool, dry_run: bool) -> tuple[dict[str, Any], bool]:
    state = _load_billing_state()
    if state.get("card_on_file") is True:
        return state, True

    if non_interactive:
        return state, False

    console.print(Panel(
        "No billing card found for this Company Maestro.\n"
        "Add a card to purchase and activate additional project nodes.",
        title="Billing",
        border_style="yellow",
    ))
    should_add = Confirm.ask("Add card now?", default=True)
    if not should_add:
        return state, False

    attempts = 0
    max_attempts = 5
    cardholder = ""
    last4 = ""
    expiry = ""
    while attempts < max_attempts:
        attempts += 1
        cardholder = Prompt.ask("Cardholder name").strip()
        last4 = Prompt.ask("Card last 4 digits").strip()
        expiry = Prompt.ask("Card expiry (MM/YY)").strip()

        if len(last4) != 4 or not last4.isdigit():
            console.print("[red]Card last 4 must be exactly four digits.[/]")
            retry = Confirm.ask("Try card entry again?", default=True)
            if retry:
                continue
            return state, False

        if not re.match(r"^(0[1-9]|1[0-2])/[0-9]{2}$", expiry):
            console.print("[red]Expiry must look like MM/YY (example: 08/29).[/]")
            retry = Confirm.ask("Try card entry again?", default=True)
            if retry:
                continue
            return state, False
        break
    else:
        console.print("[red]Too many invalid attempts while setting billing card.[/]")
        return state, False

    updated = {
        **state,
        "card_on_file": True,
        "cardholder": cardholder or "Unknown",
        "card_last4": last4,
        "card_expiry": expiry,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not dry_run:
        _save_billing_state(updated)
    return updated, True


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

    workspace_env = render_workspace_env(
        store_path=str(project_store_path),
        provider_env_key=provider_env_key,
        provider_key=provider_key,
        gemini_key=env.get("GEMINI_API_KEY") if isinstance(env.get("GEMINI_API_KEY"), str) else None,
    )
    metadata = {
        "project_slug": project_slug,
        "project_name": project_name,
        "assignee": assignee,
        "model": model,
        "provider_env_key": provider_env_key or "",
        "telegram_token_hash": hashlib.sha256(telegram_token.encode()).hexdigest(),
    }

    if not dry_run:
        save_json(config_path, config)
        project_workspace.mkdir(parents=True, exist_ok=True)
        (project_workspace / ".env").write_text(workspace_env, encoding="utf-8")
        save_json(project_workspace / "project_agent.json", metadata)

    return {
        "agent_id": agent_id,
        "workspace_env_written": not dry_run,
        "metadata_written": not dry_run,
    }


def _approve_pairing_code(pairing_code: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["openclaw", "pairing", "approve", "telegram", pairing_code],
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
            ["openclaw", "gateway", "restart"],
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
        ["openclaw", "gateway", "start"],
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    start_output = (start.stdout or start.stderr or "").strip()
    if start.returncode == 0:
        return {"ok": True, "detail": start_output or "Gateway started"}
    return {"ok": False, "detail": output or start_output or "Failed to restart gateway"}


def run_purchase(
    *,
    project_name: str | None = None,
    assignee: str | None = None,
    superintendent: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    telegram_token: str | None = None,
    pairing_code: str | None = None,
    maestro_license_key: str | None = None,
    store_override: str | None = None,
    dry_run: bool = False,
    json_output: bool = False,
    non_interactive: bool = False,
    skip_remote_validation: bool = False,
) -> int:
    _, config_path = _load_openclaw_config()
    if not config_path.exists():
        console.print("[red]OpenClaw config not found. Run maestro-setup first.[/]")
        return 1

    config, _ = _load_openclaw_config()
    company = _resolve_company_agent(config)
    company_model = str(company.get("model", "google/gemini-3-pro-preview")).strip()
    store_root = resolve_fleet_store_root(store_override)
    registry = sync_fleet_registry(store_root, dry_run=dry_run)
    purchase_status = build_purchase_status(store_root, registry=registry)

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
        console.print(Panel(
            "Select model for this project maestro:\n"
            f"1. Inherit company default ({company_model})\n"
            "2. OpenAI GPT-5.2\n"
            "3. Google Gemini 3 Pro\n"
            "4. Anthropic Claude Opus 4.6",
            title="Model Selection",
        ))
        choice = Prompt.ask("Choice", choices=["1", "2", "3", "4"], default="1")
        model_choice, _ = MODEL_CHOICES[choice]
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
        selected_api_key = Prompt.ask(f"Paste {provider_env_key}").strip()

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
    if not skip_remote_validation:
        ok, bot_username, detail = _validate_telegram_token(selected_telegram_token)
        if not ok:
            if non_interactive:
                console.print(f"[red]Telegram token validation failed: {detail}[/]")
                return 1
            proceed = Confirm.ask(f"Telegram token validation failed ({detail}). Continue anyway?", default=False)
            if not proceed:
                return 1
        else:
            console.print(f"[green]Telegram verified: @{bot_username}[/]")

    # Licensing gate
    requires_paid = bool(purchase_status.get("requires_paid_license"))
    selected_license = maestro_license_key.strip() if isinstance(maestro_license_key, str) else ""
    license_result: dict[str, Any] | None = None
    planned_store_path = (store_root / project_slug).resolve()
    if requires_paid:
        billing_state, has_card = _ensure_card_on_file(non_interactive=non_interactive, dry_run=dry_run)
        if not has_card:
            console.print(
                "[red]Paid project slot requires a card on file before Maestro license activation.[/]"
            )
            return 1

        if not non_interactive:
            last4 = billing_state.get("card_last4")
            if isinstance(last4, str) and last4.strip():
                console.print(f"[green]Card on file confirmed (•••• {last4}).[/]")
            approved = Confirm.ask(
                f"Buy and activate a new Maestro node for ${DEFAULT_PROJECT_NODE_PRICE_USD}?",
                default=True,
            )
            if not approved:
                console.print("[yellow]Purchase cancelled.[/]")
                return 1

        # Manual override kept for internal/dev fallback.
        if not selected_license:
            company_id = _derive_company_id(company)
            project_id = _derive_project_id(project_slug)
            selected_license = generate_project_key(
                company_id=company_id,
                project_id=project_id,
                project_slug=project_slug,
                knowledge_store_path=str(planned_store_path),
            )
        try:
            license_result = validate_project_key(
                selected_license,
                project_slug=project_slug,
                knowledge_store_path=str(planned_store_path),
            )
        except LicenseError as exc:
            console.print(f"[red]License validation failed: {exc}[/]")
            return 1

    result = create_project_node(
        store_root=store_root,
        project_name=project_name,
        project_slug=project_slug,
        ingest_input_root=None,
        superintendent=superintendent or assignee,
        assignee=assignee,
        register_agent=True,
        agent_model=selected_model,
        dry_run=dry_run,
    )
    if not result.get("ok"):
        console.print(f"[red]Failed to create project maestro: {result}[/]")
        return 1

    project_entry = result.get("project", {}) if isinstance(result.get("project"), dict) else {}
    project_store_path = Path(str(project_entry.get("project_store_path", planned_store_path))).resolve()
    agent_registration = result.get("agent_registration", {}) if isinstance(result.get("agent_registration"), dict) else {}
    workspace_path = Path(str(agent_registration.get("workspace", ""))).expanduser() if agent_registration.get("workspace") else Path.home() / ".openclaw" / "workspace-maestro" / "projects" / project_slug

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
    network = resolve_network_urls(web_port=3000)

    output = {
        "ok": True,
        "dry_run": dry_run,
        "project_slug": project_slug,
        "project_name": project_name,
        "assignee": assignee,
        "store_root": str(store_root),
        "project_store_path": str(project_store_path),
        "model": selected_model,
        "provider_env_key": provider_env_key,
        "maestro_license_required": requires_paid,
        "maestro_license_activated": bool(license_result),
        "openclaw_update": openclaw_update,
        "gateway_restart": gateway_restart,
        "telegram_pairing": pairing_result,
        "ingest_command": control.get("ingest", {}).get("command") if isinstance(control.get("ingest"), dict) else "",
        "command_center_url": network["recommended_url"],
        "purchase_command": "maestro-purchase",
    }

    if json_output:
        console.print_json(json.dumps(output))
        return 0

    tier = "paid" if requires_paid else "free"
    console.print(Panel(
        "\n".join([
            f"Project Maestro provisioned ({tier} slot)",
            f"Project: {project_name} ({project_slug})",
            f"Assignee: {assignee}",
            f"Store: {project_store_path}",
            f"Model: {selected_model}",
            f"Maestro License: {'Auto-activated' if bool(license_result) else 'Not required (free slot)'}",
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
        title="maestro-purchase",
        border_style="cyan",
    ))
    return 0


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
    parser.add_argument(
        "--maestro-license-key",
        "--project-license-key",
        dest="maestro_license_key",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--store", help="Override fleet store root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--skip-remote-validation", action="store_true")
    return parser


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    code = run_purchase(
        project_name=args.project_name,
        assignee=args.assignee,
        superintendent=args.superintendent,
        model=args.model,
        api_key=args.api_key,
        telegram_token=args.telegram_token,
        pairing_code=args.pairing_code,
        maestro_license_key=args.maestro_license_key,
        store_override=args.store,
        dry_run=bool(args.dry_run),
        json_output=bool(args.json),
        non_interactive=bool(args.non_interactive),
        skip_remote_validation=bool(args.skip_remote_validation),
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
