"""Fleet remote deployment workflow."""

from __future__ import annotations

import os
import re
import socket
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from .control_plane import ensure_telegram_account_bindings, resolve_network_urls, sync_fleet_registry
from .doctor import run_doctor
from .install_state import resolve_fleet_store_root, save_install_state
from .openclaw_guard import ensure_openclaw_override_allowed
from .profile import set_profile
from .purchase import run_purchase
from .update import run_update
from .utils import load_json, save_json, slugify
from .workspace_templates import provider_env_key_for_model


console = Console()

VERTEX_API_KEY_RE = re.compile(r"^AIza[0-9A-Za-z_-]{24,}$")


def _looks_like_vertex_api_key(value: str) -> bool:
    return bool(VERTEX_API_KEY_RE.match(str(value or "").strip()))


def _looks_like_google_access_token(value: str) -> bool:
    token = str(value or "").strip()
    return token.startswith("ya29.") or token.startswith("eyJ")


def _mask_secret(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


@dataclass
class PrereqResult:
    ok: bool
    failures: list[str]
    warnings: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_openclaw_config(home_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    home = (home_dir or Path.home()).resolve()
    config_path = home / ".openclaw" / "openclaw.json"
    payload = load_json(config_path, default={})
    if not isinstance(payload, dict):
        payload = {}
    return payload, config_path


def _ensure_openclaw_config_exists(home_dir: Path | None = None) -> Path:
    home = (home_dir or Path.home()).resolve()
    config_path = home / ".openclaw" / "openclaw.json"
    if not config_path.exists():
        save_json(config_path, {})
    return config_path


def _resolve_company_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []

    company = next(
        (
            item for item in agent_list
            if isinstance(item, dict) and str(item.get("id", "")).strip() == "maestro-company"
        ),
        None,
    )
    if isinstance(company, dict):
        return company
    default = next(
        (
            item for item in agent_list
            if isinstance(item, dict) and bool(item.get("default")) and str(item.get("id", "")).strip()
        ),
        None,
    )
    return default if isinstance(default, dict) else {}


def _is_maestro_managed_agent(agent_id: str) -> bool:
    clean = str(agent_id or "").strip()
    return (
        not clean
        or clean in {"maestro", "maestro-company", "maestro-personal"}
        or clean.startswith("maestro-project-")
    )


def _run_cmd(args: list[str], timeout: int = 12) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _check_prereqs(*, require_tailscale: bool) -> PrereqResult:
    failures: list[str] = []
    warnings: list[str] = []

    if sys.version_info < (3, 11):
        failures.append(f"Python 3.11+ required (found {sys.version.split()[0]})")

    for tool in ("node", "npm", "openclaw"):
        if shutil.which(tool) is None:
            failures.append(f"Missing required tool: {tool}")

    tailscale_ok = shutil.which("tailscale") is not None
    if require_tailscale and not tailscale_ok:
        failures.append("Tailscale is required (`--require-tailscale`) but not installed")
    if not tailscale_ok:
        warnings.append("Tailscale not installed; tailnet access will be unavailable")
    elif require_tailscale:
        ok, out = _run_cmd(["tailscale", "ip", "-4"], timeout=8)
        if not ok or not out.strip():
            failures.append("Tailscale installed but no IPv4 tailnet address detected (run `tailscale up`)")
    else:
        ok, out = _run_cmd(["tailscale", "ip", "-4"], timeout=8)
        if not ok or not out.strip():
            warnings.append("Tailscale not connected; deployment will still be local-network only")

    return PrereqResult(ok=not failures, failures=failures, warnings=warnings)


def _validate_api_key(provider_env_key: str, key: str) -> tuple[bool, str]:
    token = str(key or "").strip()
    if not token:
        return False, "Key is empty"
    try:
        if provider_env_key == "OPENAI_API_KEY":
            response = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            return response.status_code == 200, f"OpenAI status={response.status_code}"
        if provider_env_key == "GEMINI_API_KEY":
            if _looks_like_google_access_token(token):
                token_response = httpx.get(
                    "https://oauth2.googleapis.com/tokeninfo",
                    params={"access_token": token},
                    timeout=10,
                )
                if token_response.status_code == 200:
                    return True, f"Vertex token status={token_response.status_code}"
            response = httpx.get(
                f"https://generativelanguage.googleapis.com/v1/models?key={token}",
                timeout=10,
            )
            if response.status_code == 403 and _looks_like_vertex_api_key(token):
                return True, "Vertex API key accepted (Developer API check returned 403)"
            if response.status_code in {401, 403}:
                vertex_response = httpx.post(
                    (
                        "https://aiplatform.googleapis.com/v1/publishers/google/models/"
                        f"gemini-2.5-flash-lite:generateContent?key={token}"
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
        if provider_env_key == "ANTHROPIC_API_KEY":
            response = httpx.get(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": token, "anthropic-version": "2023-06-01"},
                timeout=10,
            )
            return response.status_code != 401, f"Anthropic status={response.status_code}"
    except Exception as exc:
        return False, str(exc)
    return False, "Unsupported provider"


def _validate_telegram_token(token: str) -> tuple[bool, str, str, str]:
    text = str(token or "").strip()
    if not text:
        return False, "", "", "Token is empty"
    try:
        response = httpx.get(f"https://api.telegram.org/bot{text}/getMe", timeout=10)
    except Exception as exc:
        return False, "", "", f"Network error: {exc}"
    if response.status_code != 200:
        return False, "", "", f"Telegram status={response.status_code}"
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("ok"):
        return False, "", "", "Telegram API did not return ok=true"
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return False, "", "", "Telegram API returned malformed result"
    username = str(result.get("username", "")).strip()
    display_name = str(result.get("first_name", "")).strip()
    return True, username, display_name, "validated"


def _resolve_company_token(config: dict[str, Any]) -> str:
    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
    accounts = telegram.get("accounts") if isinstance(telegram.get("accounts"), dict) else {}
    company = accounts.get("maestro-company") if isinstance(accounts.get("maestro-company"), dict) else {}
    account_token = str(company.get("botToken", "")).strip() if isinstance(company, dict) else ""
    if account_token:
        return account_token
    return str(telegram.get("botToken", "")).strip() if isinstance(telegram, dict) else ""


def _configure_company_openclaw(
    *,
    model: str,
    api_key: str | None,
    telegram_token: str,
    allow_openclaw_override: bool,
) -> dict[str, Any]:
    config, config_path = _load_openclaw_config()
    safe_override, override_message = ensure_openclaw_override_allowed(
        config,
        allow_override=allow_openclaw_override,
    )
    if not safe_override:
        raise RuntimeError(override_message)

    if not isinstance(config.get("gateway"), dict):
        config["gateway"] = {}
    config["gateway"]["mode"] = "local"

    if not isinstance(config.get("env"), dict):
        config["env"] = {}
    provider_env_key = provider_env_key_for_model(model)
    if provider_env_key and isinstance(api_key, str) and api_key.strip():
        config["env"][provider_env_key] = api_key.strip()

    if not isinstance(config.get("agents"), dict):
        config["agents"] = {}
    if not isinstance(config["agents"].get("list"), list):
        config["agents"]["list"] = []
    agents = config["agents"]["list"]
    existing = next(
        (
            item for item in agents
            if isinstance(item, dict) and str(item.get("id", "")).strip() == "maestro-company"
        ),
        None,
    )

    default_workspace = (Path.home() / ".openclaw" / "workspace-maestro").resolve()
    existing_workspace = ""
    if isinstance(existing, dict):
        existing_workspace = str(existing.get("workspace", "")).strip()
    workspace_root = (
        Path(existing_workspace).expanduser().resolve()
        if existing_workspace else default_workspace
    )
    workspace_root.mkdir(parents=True, exist_ok=True)

    desired = {
        "id": "maestro-company",
        "name": "The Commander",
        "default": True,
        "model": model,
        "workspace": str(workspace_root),
    }
    if isinstance(existing, dict):
        for key, value in desired.items():
            existing[key] = value
    else:
        agents.append(desired)

    for item in agents:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id", "")).strip()
        if agent_id == "maestro-company":
            item["default"] = True
            continue
        if _is_maestro_managed_agent(agent_id) and bool(item.get("default")):
            item["default"] = False

    if not isinstance(config.get("channels"), dict):
        config["channels"] = {}
    channels = config["channels"]
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        telegram = {}
        channels["telegram"] = telegram
    telegram["enabled"] = True
    if not str(telegram.get("botToken", "")).strip():
        telegram["botToken"] = telegram_token
    accounts = telegram.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        telegram["accounts"] = accounts
    accounts["maestro-company"] = {
        "botToken": telegram_token,
        "dmPolicy": "pairing",
        "groupPolicy": "allowlist",
        "streamMode": "partial",
    }
    binding_changes = ensure_telegram_account_bindings(config)

    save_json(config_path, config)
    return {
        "config_path": str(config_path),
        "workspace_root": str(workspace_root),
        "provider_env_key": provider_env_key or "",
        "binding_changes": binding_changes,
    }


def _fleet_state_dir() -> Path:
    path = (Path.home() / ".maestro" / "fleet").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, int(port))) == 0


def _resolve_deploy_port(preferred_port: int, max_attempts: int = 20) -> tuple[int, bool]:
    requested = int(preferred_port)
    if requested <= 0:
        requested = 3000
    if not _port_listening(requested):
        return requested, False
    for offset in range(1, int(max_attempts) + 1):
        candidate = requested + offset
        if not _port_listening(candidate):
            return candidate, True
    return 0, True


def _start_detached_server(*, port: int, store_root: Path, host: str) -> dict[str, Any]:
    state_dir = _fleet_state_dir()
    pid_path = state_dir / "serve.pid.json"
    log_path = state_dir / "serve.log"
    requested_port = int(port)

    if pid_path.exists():
        payload = load_json(pid_path, default={})
        running_pid = int(payload.get("pid", 0)) if isinstance(payload, dict) else 0
        if _pid_running(running_pid):
            running_port = int(payload.get("port", 0)) if isinstance(payload, dict) else 0
            return {
                "ok": True,
                "already_running": True,
                "pid": running_pid,
                "port": running_port or requested_port,
                "port_mismatch": bool(running_port and running_port != requested_port),
                "pid_path": str(pid_path),
                "log_path": str(log_path),
            }
        pid_path.unlink(missing_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "maestro.cli",
        "serve",
        "--port",
        str(int(port)),
        "--store",
        str(store_root),
        "--host",
        str(host),
    ]
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{_now_iso()}] starting detached server: {' '.join(cmd)}\n")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    time.sleep(1.0)
    if proc.poll() is not None:
        return {"ok": False, "detail": "maestro serve exited immediately", "log_path": str(log_path)}

    save_json(
        pid_path,
        {
            "pid": int(proc.pid),
            "started_at": _now_iso(),
            "port": int(port),
            "host": str(host),
            "store_root": str(store_root),
            "command": cmd,
        },
    )
    return {
        "ok": True,
        "already_running": False,
        "pid": int(proc.pid),
        "port": int(port),
        "port_mismatch": False,
        "pid_path": str(pid_path),
        "log_path": str(log_path),
    }


def _verify_command_center_http(port: int, timeout_seconds: int = 25) -> bool:
    end = time.time() + float(timeout_seconds)
    while time.time() < end:
        try:
            response = httpx.get(f"http://127.0.0.1:{int(port)}/api/command-center/state", timeout=2.5)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def run_deploy(
    *,
    company_name: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    telegram_token: str | None = None,
    project_name: str | None = None,
    assignee: str | None = None,
    superintendent: str | None = None,
    project_telegram_token: str | None = None,
    store_override: str | None = None,
    port: int = 3000,
    host: str = "0.0.0.0",
    non_interactive: bool = False,
    skip_remote_validation: bool = False,
    local_license_mode: bool = False,
    require_tailscale: bool = False,
    allow_openclaw_override: bool = False,
    start_services: bool = True,
) -> int:
    console.print("[bold cyan]Maestro Fleet Deploy[/]")
    console.print("One-session deployment for remote customer handoff.")

    prereq = _check_prereqs(require_tailscale=require_tailscale)
    if prereq.warnings:
        for warning in prereq.warnings:
            console.print(f"[yellow]- {warning}[/]")
    if not prereq.ok:
        for failure in prereq.failures:
            console.print(f"[red]- {failure}[/]")
        return 1

    set_profile("fleet", fleet=True)
    _ensure_openclaw_config_exists()

    update_code = run_update(restart_gateway=False, dry_run=False)
    if update_code != 0:
        return update_code

    config, _ = _load_openclaw_config()
    current_company = _resolve_company_agent(config)
    default_model = str(current_company.get("model", "openai/gpt-5.2")).strip() or "openai/gpt-5.2"
    selected_model = str(model or "").strip() or default_model
    provider_env_key = provider_env_key_for_model(selected_model)
    env = config.get("env", {}) if isinstance(config.get("env"), dict) else {}
    existing_provider_key = str(env.get(provider_env_key, "")).strip() if provider_env_key else ""
    prompt_label = (
        "Default GEMINI_API_KEY for Company Maestro (Gemini API or Vertex AI key)"
        if provider_env_key == "GEMINI_API_KEY"
        else f"Default {provider_env_key} for Company Maestro"
    )

    chosen_company_name = str(company_name or "").strip()
    if not chosen_company_name:
        if non_interactive:
            chosen_company_name = "Company"
        else:
            chosen_company_name = Prompt.ask("Company name", default="Company").strip() or "Company"

    selected_api_key = str(api_key or "").strip()
    used_existing_api_key = False
    if provider_env_key and not selected_api_key:
        if existing_provider_key and not non_interactive:
            use_existing = Confirm.ask(
                f"Use existing {provider_env_key} from OpenClaw config ({_mask_secret(existing_provider_key)})?",
                default=False,
            )
            if use_existing:
                selected_api_key = existing_provider_key
                used_existing_api_key = True
        elif existing_provider_key:
            selected_api_key = existing_provider_key
            used_existing_api_key = True
    if provider_env_key and not selected_api_key and non_interactive:
        console.print(f"[red]Missing API key for {provider_env_key}[/]")
        return 1
    if provider_env_key and not selected_api_key:
        selected_api_key = Prompt.ask(prompt_label).strip()
        if not selected_api_key:
            console.print(f"[red]{provider_env_key} is required to continue.[/]")
            return 1
    if provider_env_key and selected_api_key and not skip_remote_validation:
        ok_key, detail_key = _validate_api_key(provider_env_key, selected_api_key)
        if not ok_key and used_existing_api_key:
            console.print(
                f"[yellow]Existing {provider_env_key} failed validation ({detail_key}). Enter a different key.[/]"
            )
            replacement = Prompt.ask(prompt_label).strip()
            if replacement:
                selected_api_key = replacement
                used_existing_api_key = False
                ok_key, detail_key = _validate_api_key(provider_env_key, selected_api_key)
            else:
                console.print(f"[red]{provider_env_key} is required to continue.[/]")
                return 1
        if not ok_key:
            if non_interactive:
                console.print(f"[red]API key validation failed: {detail_key}[/]")
                return 1
            proceed = Confirm.ask(f"API key validation failed ({detail_key}). Continue anyway?", default=False)
            if not proceed:
                return 1

    selected_company_telegram = str(telegram_token or "").strip() or _resolve_company_token(config)
    if not selected_company_telegram and non_interactive:
        console.print("[red]Missing --telegram-token for Company Maestro[/]")
        return 1
    if not selected_company_telegram:
        selected_company_telegram = Prompt.ask("Company Maestro Telegram bot token").strip()
    ok_tg, tg_username, tg_display, tg_detail = (True, "", "", "skipped")
    if not skip_remote_validation:
        ok_tg, tg_username, tg_display, tg_detail = _validate_telegram_token(selected_company_telegram)
        if not ok_tg:
            if non_interactive:
                console.print(f"[red]Company Telegram token validation failed: {tg_detail}[/]")
                return 1
            proceed = Confirm.ask(f"Company Telegram validation failed ({tg_detail}). Continue anyway?", default=False)
            if not proceed:
                return 1

    try:
        company_cfg = _configure_company_openclaw(
            model=selected_model,
            api_key=selected_api_key,
            telegram_token=selected_company_telegram,
            allow_openclaw_override=allow_openclaw_override,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    store_root = resolve_fleet_store_root(store_override)
    store_root.mkdir(parents=True, exist_ok=True)

    save_install_state(
        {
            "version": 2,
            "profile": "fleet",
            "fleet_enabled": True,
            "workspace_root": company_cfg["workspace_root"],
            "store_root": str(store_root),
            "fleet_store_root": str(store_root),
            "company_name": chosen_company_name,
            "updated_at": _now_iso(),
        }
    )

    create_project = bool(project_name or assignee or project_telegram_token)
    if not create_project and not non_interactive:
        create_project = Confirm.ask("Provision an initial project Maestro now?", default=True)
    if create_project:
        chosen_project_name = str(project_name or "").strip()
        chosen_assignee = str(assignee or "").strip()
        if not chosen_project_name:
            if non_interactive:
                console.print("[red]Missing --project-name for initial project provisioning[/]")
                return 1
            chosen_project_name = Prompt.ask("Initial project name").strip()
        if not chosen_assignee:
            if non_interactive:
                console.print("[red]Missing --assignee for initial project provisioning[/]")
                return 1
            chosen_assignee = Prompt.ask("Initial project assignee").strip()

        selected_project_telegram = str(project_telegram_token or "").strip()
        if not selected_project_telegram and non_interactive:
            console.print("[red]Missing --project-telegram-token for initial project provisioning[/]")
            return 1
        if not selected_project_telegram:
            selected_project_telegram = Prompt.ask("Initial project Telegram bot token").strip()

        purchase_code = run_purchase(
            project_name=chosen_project_name,
            assignee=chosen_assignee,
            superintendent=superintendent,
            model=selected_model,
            api_key=selected_api_key,
            telegram_token=selected_project_telegram,
            store_override=str(store_root),
            dry_run=False,
            json_output=False,
            non_interactive=True,
            skip_remote_validation=bool(skip_remote_validation),
            local_license_mode=bool(local_license_mode),
            allow_openclaw_override=bool(allow_openclaw_override),
        )
        if purchase_code != 0:
            return purchase_code
        project_slug = slugify(chosen_project_name)
    else:
        project_slug = ""

    doctor_code = run_doctor(
        fix=True,
        store_override=str(store_root),
        restart_gateway=True,
        json_output=False,
    )
    if doctor_code != 0:
        return doctor_code

    requested_port = int(port)
    effective_port = requested_port
    detached = {"ok": True, "already_running": False, "pid": 0, "pid_path": "", "log_path": ""}
    if start_services:
        resolved_port, shifted_port = _resolve_deploy_port(requested_port)
        if resolved_port <= 0:
            console.print(f"[red]No available port found near {requested_port} for Fleet web server.[/]")
            return 1
        effective_port = int(resolved_port)
        if shifted_port and effective_port != requested_port:
            console.print(
                f"[yellow]Port {requested_port} is already in use; using {effective_port} for Fleet server.[/]"
            )
        detached = _start_detached_server(port=effective_port, store_root=store_root, host=str(host))
        if not detached.get("ok"):
            console.print(f"[red]Failed to start detached Fleet server: {detached.get('detail', 'unknown error')}[/]")
            return 1
        detached_port = int(detached.get("port", 0)) if isinstance(detached.get("port"), int | float | str) else 0
        if detached_port and detached_port != effective_port:
            effective_port = detached_port
            console.print(
                f"[yellow]Reusing existing Fleet server on port {effective_port} from PID state.[/]"
            )
        if not _verify_command_center_http(effective_port):
            console.print(
                "[red]Fleet server process started but command-center health check did not pass in time.[/]\n"
                f"[yellow]Check logs: {detached.get('log_path', '')}[/]"
            )
            return 1

    final_config, _ = _load_openclaw_config()
    channels = final_config.get("channels", {}) if isinstance(final_config.get("channels"), dict) else {}
    telegram = channels.get("telegram", {}) if isinstance(channels.get("telegram"), dict) else {}
    accounts = telegram.get("accounts", {}) if isinstance(telegram.get("accounts"), dict) else {}
    company_account = accounts.get("maestro-company", {}) if isinstance(accounts.get("maestro-company"), dict) else {}
    company_username = str(company_account.get("username", "")).strip() or tg_username
    project_username = ""
    if project_slug:
        registry = sync_fleet_registry(store_root)
        projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
        project_entry = next(
            (
                item for item in projects
                if isinstance(item, dict) and str(item.get("project_slug", "")).strip() == project_slug
            ),
            None,
        )
        if isinstance(project_entry, dict):
            project_username = str(project_entry.get("telegram_bot_username", "")).strip().lstrip("@")

    route = "/command-center"
    network = resolve_network_urls(web_port=effective_port, route_path=route)
    command_center_url = str(network.get("recommended_url", f"http://localhost:{effective_port}{route}"))
    local_url = str(network.get("localhost_url", f"http://localhost:{effective_port}{route}"))
    tailnet_url = str(network.get("tailnet_url", "")).strip()

    summary_lines = [
        f"Company: {chosen_company_name}",
        f"Profile: fleet",
        f"Store Root: {store_root}",
        f"Workspace Root: {company_cfg['workspace_root']}",
        f"Model: {selected_model}",
        "License Mode: local/offline",
        f"Command Center: {command_center_url}",
        f"Command Center (local): {local_url}",
    ]
    if tailnet_url:
        summary_lines.append(f"Command Center (tailnet): {tailnet_url}")
    if start_services:
        if detached.get("already_running"):
            summary_lines.append(f"Server Process: already running (pid {detached.get('pid')})")
        else:
            summary_lines.append(f"Server Process: started (pid {detached.get('pid')})")
        summary_lines.append(f"Server PID File: {detached.get('pid_path')}")
        summary_lines.append(f"Server Log: {detached.get('log_path')}")
    summary_lines.append(f"Text the Commander: @{company_username}" if company_username else "Text the Commander: configured")
    if project_slug:
        if project_username:
            summary_lines.append(f"Text initial project Maestro: @{project_username}")
        else:
            summary_lines.append(f"Initial project Maestro slug: {project_slug}")

    console.print()
    console.print(Panel("\n".join(summary_lines), title="Fleet Deployment Summary", border_style="cyan"))
    return 0
