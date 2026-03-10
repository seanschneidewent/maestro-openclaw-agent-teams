"""Fleet project provisioning helpers."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ...command_center import discover_project_dirs
from ...control_plane import (
    create_project_node,
    ensure_telegram_account_bindings,
    onboard_project_store,
    project_control_payload,
    resolve_network_urls,
)
from ...fleet_constants import (
    FLEET_GATEWAY_PORT,
    FLEET_PROFILE,
    MODEL_LABELS,
    PROJECT_MODEL_OPTIONS,
)
from ...fleet.runtime import gateway as fleet_gateway_runtime
from ...fleet.shared.subprocesses import parse_json_from_output
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
    render_workspace_env,
    sync_project_workspace_runtime_files,
)


console = Console()

_PROJECT_METADATA_KEY = "maestro"
_RUN_PURCHASE_DEPRECATED_WARNED = False

VERTEX_API_KEY_RE = re.compile(r"^AIza[0-9A-Za-z_-]{24,}$")


def _load_package_run_project_create():
    try:
        module = importlib.import_module("maestro_fleet.provisioning")
        return getattr(module, "run_project_create")
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[3]
        package_src = repo_root / "packages" / "maestro-fleet" / "src"
        if package_src.exists() and str(package_src) not in sys.path:
            sys.path.insert(0, str(package_src))
        module = importlib.import_module("maestro_fleet.provisioning")
        return getattr(module, "run_project_create")


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


def _project_exists(store_root: Path, slug: str) -> bool:
    desired = slugify(slug)
    for project_dir in discover_project_dirs(store_root):
        payload = load_json(project_dir / "project.json", default={})
        if not isinstance(payload, dict):
            payload = {}
        current_slug = slugify(
            str(payload.get("slug", "")).strip()
            or str(payload.get("name", "")).strip()
            or project_dir.name
        )
        if current_slug == desired:
            return True
    return False


def _save_project_metadata(project_store_path: Path, metadata: dict[str, Any]) -> None:
    payload = load_json(project_store_path / "project.json", default={})
    if not isinstance(payload, dict):
        payload = {}
    current = payload.get(_PROJECT_METADATA_KEY) if isinstance(payload.get(_PROJECT_METADATA_KEY), dict) else {}
    if not isinstance(current, dict):
        current = {}
    for key, value in metadata.items():
        clean = str(value).strip() if value is not None else ""
        if clean:
            current[key] = clean
    payload[_PROJECT_METADATA_KEY] = current
    save_json(project_store_path / "project.json", payload)


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
    workspace_env = workspace_env.rstrip("\n") + f"\nMAESTRO_PROJECT_SLUG={project_slug}\n"
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
        _save_project_metadata(project_store_path, metadata)
        sync_project_workspace_runtime_files(
            project_workspace=project_workspace,
            project_slug=project_slug,
            model=model,
            store_root=project_store_path,
            generated_by="maestro purchase",
            resolve_network_urls_fn=resolve_network_urls,
            web_port=_current_command_center_port(),
            dry_run=False,
        )

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
        return {"ok": True, "detail": gw_out or "Gateway already running", "gateway_status_ok": gw_ok}

    restart_ok, restart_out = _run_gateway(["openclaw", "gateway", "restart"], 35)
    actions.append(f"gateway restart: {'ok' if restart_ok else 'failed'}")
    if restart_out:
        actions.append(restart_out)

    recheck_ok, recheck_status, recheck_out = _status_snapshot(12)
    if fleet_gateway_runtime.gateway_cli_ready(recheck_status):
        return {
            "ok": True,
            "detail": "\n".join(item for item in actions if item).strip() or recheck_out or "Gateway restarted",
            "gateway_status_ok": recheck_ok,
        }

    start_ok, start_out = _run_gateway(["openclaw", "gateway", "start"], 35)
    actions.append(f"gateway start: {'ok' if start_ok else 'failed'}")
    if start_out:
        actions.append(start_out)

    recheck_ok, recheck_status, recheck_out = _status_snapshot(12)
    if fleet_gateway_runtime.gateway_cli_ready(recheck_status):
        return {
            "ok": True,
            "detail": "\n".join(item for item in actions if item).strip() or recheck_out or "Gateway started",
            "gateway_status_ok": recheck_ok,
        }

    install_ok, install_out = _run_gateway(
        ["openclaw", "gateway", "install", "--force", "--port", str(FLEET_GATEWAY_PORT)],
        60,
    )
    actions.append(f"gateway install --force: {'ok' if install_ok else 'failed'}")
    if install_out:
        actions.append(install_out)

    start2_ok, start2_out = _run_gateway(["openclaw", "gateway", "start"], 35)
    actions.append(f"gateway start (post-install): {'ok' if start2_ok else 'failed'}")
    if start2_out:
        actions.append(start2_out)

    recheck2_ok, recheck2_status, recheck2_out = _status_snapshot(12)
    if fleet_gateway_runtime.gateway_cli_ready(recheck2_status):
        return {
            "ok": True,
            "detail": "\n".join(item for item in actions if item).strip() or recheck2_out or "Gateway reinstalled and started",
            "gateway_status_ok": recheck2_ok,
        }

    return {
        "ok": False,
        "detail": "\n".join(item for item in actions if item).strip() or recheck2_out or "Failed to restart gateway",
        "gateway_status_ok": recheck2_ok,
    }


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
    package_run_project_create = _load_package_run_project_create()
    had_profile_env = "MAESTRO_OPENCLAW_PROFILE" in os.environ
    if not had_profile_env:
        os.environ["MAESTRO_OPENCLAW_PROFILE"] = "shared"
    try:
        return package_run_project_create(
            project_name=project_name,
            assignee=assignee,
            superintendent=superintendent,
            model=model,
            api_key=api_key,
            telegram_token=telegram_token,
            pairing_code=pairing_code,
            store_override=store_override,
            dry_run=dry_run,
            json_output=json_output,
            non_interactive=non_interactive,
            skip_remote_validation=skip_remote_validation,
            allow_openclaw_override=allow_openclaw_override,
        )
    finally:
        if not had_profile_env:
            os.environ.pop("MAESTRO_OPENCLAW_PROFILE", None)


def run_purchase(*args, **kwargs):
    global _RUN_PURCHASE_DEPRECATED_WARNED
    if not _RUN_PURCHASE_DEPRECATED_WARNED:
        warnings.warn(
            "maestro.fleet.projects.provisioning.run_purchase() is deprecated; use `maestro_fleet.provisioning.run_project_create()` or `maestro-fleet project create`.",
            DeprecationWarning,
            stacklevel=2,
        )
        _RUN_PURCHASE_DEPRECATED_WARNED = True
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
