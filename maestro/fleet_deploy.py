"""Fleet remote deployment workflow."""

from __future__ import annotations

import os
import re
import socket
import shutil
import subprocess
import signal
import shlex
import sys
import time
import json
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .control_plane import ensure_telegram_account_bindings, resolve_network_urls, sync_fleet_registry
from .fleet.runtime import gateway as fleet_gateway_runtime
from .fleet.runtime import server as fleet_server_runtime
from .fleet.platform import windows as fleet_windows_runtime
from .fleet.shared import subprocesses as fleet_subprocesses
from .fleet_constants import (
    DEFAULT_COMMANDER_MODEL,
    DEFAULT_PROJECT_MODEL,
    DEPLOY_STEP_TITLES,
    FLEET_GATEWAY_PORT,
    FLEET_PROFILE,
    FLEET_MODEL_OPTIONS,
    KEY_LABELS,
    KEY_ORDER,
    MODEL_CHOICES,
    canonicalize_model,
    default_model_from_agents,
    format_model_display,
    model_label,
)
from .install_state import resolve_fleet_store_root, save_install_state
from .openclaw_guard import ensure_openclaw_override_allowed
from .openclaw_profile import (
    openclaw_config_path,
    openclaw_workspace_root,
    prepend_openclaw_profile_args,
    resolve_openclaw_profile,
)
from .profile import set_profile
from .fleet.projects.provisioning import run_project_create
from .utils import load_json, save_json, slugify
from .workspace_templates import provider_env_key_for_model


console = Console()

VERTEX_API_KEY_RE = re.compile(r"^AIza[0-9A-Za-z_-]{24,}$")


def _load_package_run_update():
    try:
        module = importlib.import_module("maestro_fleet.update")
        return getattr(module, "run_update")
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[1]
        package_src = repo_root / "packages" / "maestro-fleet" / "src"
        if package_src.exists() and str(package_src) not in sys.path:
            sys.path.insert(0, str(package_src))
        try:
            module = importlib.import_module("maestro_fleet.update")
            return getattr(module, "run_update")
        except ModuleNotFoundError:
            from .update import run_update as legacy_run_update

            return legacy_run_update


run_update = _load_package_run_update()


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


def _fleet_gateway_port() -> int:
    return FLEET_GATEWAY_PORT


def _deploy_step_title(step_number: int) -> str:
    index = max(1, int(step_number)) - 1
    if 0 <= index < len(DEPLOY_STEP_TITLES):
        return DEPLOY_STEP_TITLES[index]
    return f"Step {step_number}"


def _step_header(step: int, total_steps: int, title: str, *, enabled: bool):
    if not enabled:
        return
    console.print()
    filled = max(1, int((float(step) / float(total_steps)) * 30))
    bar = "━" * filled + "─" * max(0, 30 - filled)
    pct = int((float(step) / float(total_steps)) * 100)
    console.print(
        Panel(
            f"[bold cyan]{title}[/]\n[dim]Step {step} of {total_steps}[/]\n[cyan]{bar}[/] [dim]{pct}%[/]",
            border_style="cyan",
        )
    )


def _provider_prompt_label(provider_env_key: str) -> str:
    if provider_env_key == "GEMINI_API_KEY":
        return "GEMINI_API_KEY (Gemini API or Vertex AI key)"
    if provider_env_key == "OPENAI_API_KEY":
        return "OPENAI_API_KEY"
    if provider_env_key == "ANTHROPIC_API_KEY":
        return "ANTHROPIC_API_KEY"
    return provider_env_key


def _collect_provider_key(
    *,
    provider_env_key: str,
    provided_key: str,
    existing_key: str,
    non_interactive: bool,
    skip_remote_validation: bool,
    required: bool,
) -> tuple[str, bool]:
    selected = str(provided_key or "").strip()
    used_existing = False

    if not selected and existing_key:
        if non_interactive:
            selected = existing_key
            used_existing = True
        else:
            use_existing = Confirm.ask(
                f"Use existing {provider_env_key} from OpenClaw config ({_mask_secret(existing_key)})?",
                default=False,
            )
            if use_existing:
                selected = existing_key
                used_existing = True

    prompt_label = _provider_prompt_label(provider_env_key)
    if not selected and not non_interactive:
        if required:
            selected = Prompt.ask(prompt_label).strip()
        else:
            selected = Prompt.ask(prompt_label, default="").strip()
    if not selected:
        if required:
            console.print(f"[red]{provider_env_key} is required to continue.[/]")
            return "", False
        return "", True

    if not skip_remote_validation:
        ok_key, detail_key = _validate_api_key(provider_env_key, selected)
        if not ok_key and used_existing and not non_interactive:
            console.print(
                f"[yellow]Existing {provider_env_key} failed validation ({detail_key}). Enter a different key.[/]"
            )
            replacement = Prompt.ask(prompt_label, default="").strip()
            if replacement:
                selected = replacement
                ok_key, detail_key = _validate_api_key(provider_env_key, selected)
        if not ok_key:
            if non_interactive:
                console.print(f"[red]API key validation failed for {provider_env_key}: {detail_key}[/]")
                return "", False
            proceed = Confirm.ask(
                f"{provider_env_key} validation failed ({detail_key}). Continue anyway?",
                default=False,
            )
            if not proceed:
                if required:
                    return "", False
                return "", True
    return selected, True


def _prompt_model_selection(*, title: str, default_model: str, non_interactive: bool) -> str:
    if non_interactive:
        return canonicalize_model(default_model, fallback=DEFAULT_COMMANDER_MODEL)
    default_choice = next(
        (
            choice
            for choice, model, _label in FLEET_MODEL_OPTIONS
            if canonicalize_model(model) == canonicalize_model(default_model, fallback=DEFAULT_COMMANDER_MODEL)
        ),
        "2",
    )
    table = Table(show_header=False, box=None, padding=(0, 1))
    for choice, model, _label in FLEET_MODEL_OPTIONS:
        label = model_label(model)
        suffix = " (default)" if choice == default_choice else ""
        table.add_row(f"[cyan]{choice}[/]", f"{label}{suffix}")
    console.print(Panel(table, title=title, border_style="cyan"))
    choice = Prompt.ask("Choice", choices=[item[0] for item in FLEET_MODEL_OPTIONS], default=default_choice)
    return canonicalize_model(MODEL_CHOICES.get(choice, default_model), fallback=DEFAULT_COMMANDER_MODEL)


@dataclass
class PrereqResult:
    ok: bool
    failures: list[str]
    warnings: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_openclaw_config(home_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    config_path = openclaw_config_path(
        home_dir=home_dir,
        enforce_profile=True,
    )
    payload = load_json(config_path, default={})
    if not isinstance(payload, dict):
        payload = {}
    return payload, config_path


def _ensure_openclaw_config_exists(home_dir: Path | None = None) -> Path:
    config_path = openclaw_config_path(
        home_dir=home_dir,
        enforce_profile=True,
    )
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
    return fleet_subprocesses.run_profiled_cmd(
        args,
        timeout=timeout,
        prepend_profile_args=lambda cmd: prepend_openclaw_profile_args(cmd, default_profile=FLEET_PROFILE),
    )


def _run_cmd_raw(args: list[str], timeout: int = 12, *, clear_profile_env: bool = False) -> tuple[bool, str]:
    return fleet_subprocesses.run_cmd_raw(
        args,
        timeout=timeout,
        clear_profile_env=clear_profile_env,
    )


def _run_doctor_for_deploy(
    *,
    store_root: Path,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "maestro_fleet",
        "doctor",
        "--fix",
        "--store",
        str(store_root),
    ]
    env = os.environ.copy()
    env.setdefault("MAESTRO_OPENCLAW_PROFILE", FLEET_PROFILE)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=True,
    )
    deadline = time.time() + float(timeout_seconds)
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.2)

    timed_out = proc.poll() is None
    if timed_out:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass

    try:
        stdout, stderr = proc.communicate(timeout=3)
    except Exception:
        stdout, stderr = "", ""

    stdout = str(stdout or "").strip()
    stderr = str(stderr or "").strip()
    output = "\n".join(part for part in [stdout, stderr] if part).strip()
    if timed_out:
        return {"code": 124, "timed_out": True, "output": output}
    return {"code": int(proc.returncode or 0), "timed_out": False, "output": output}


def _parse_json_from_output(text: str) -> dict[str, Any]:
    return fleet_subprocesses.parse_json_from_output(text)


def _gateway_service_running(gateway_status: dict[str, Any]) -> bool:
    return fleet_gateway_runtime.gateway_service_running(gateway_status)


def _gateway_cli_ready(gateway_status: dict[str, Any]) -> bool:
    return fleet_gateway_runtime.gateway_cli_ready(
        gateway_status,
        service_running=_gateway_service_running,
    )


def _gateway_listener_pids(gateway_status: dict[str, Any]) -> list[int]:
    return fleet_gateway_runtime.gateway_listener_pids(gateway_status)


def _terminate_pid(pid: int) -> bool:
    try:
        target = int(pid)
    except Exception:
        return False
    if target <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(target), "/F"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(target, signal.SIGTERM)
    except Exception:
        return False
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            os.kill(target, 0)
        except OSError:
            return True
        time.sleep(0.1)
    try:
        os.kill(target, signal.SIGKILL)
    except Exception:
        return False
    return True


def _evict_gateway_listener_pids(gateway_status: dict[str, Any], *, only_pids: set[int] | None = None) -> list[int]:
    return fleet_gateway_runtime.evict_gateway_listener_pids(
        gateway_status,
        terminate_pid=_terminate_pid,
        only_pids=only_pids,
        listener_pids=_gateway_listener_pids,
    )


def _check_shared_gateway_collision(*, target_gateway_port: int) -> dict[str, Any]:
    shared_ok, shared_out = _run_cmd_raw(
        ["openclaw", "gateway", "status", "--json"],
        timeout=12,
        clear_profile_env=True,
    )
    shared_status = _parse_json_from_output(shared_out)

    shared_running = _gateway_service_running(shared_status)
    shared_port = int(target_gateway_port)
    blocked = bool(shared_running)
    return {
        "blocked": blocked,
        "shared_running": shared_running,
        "fleet_running": False,
        "shared_port": shared_port,
        "fleet_port": int(target_gateway_port),
        "shared_status_ok": shared_ok,
        "fleet_status_ok": True,
    }


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


def _approve_telegram_pairing_code(pairing_code: str) -> tuple[bool, str]:
    code = str(pairing_code or "").strip()
    if not code:
        return False, "No pairing code supplied"
    ok, out = _run_cmd(["openclaw", "pairing", "approve", "telegram", code], timeout=25)
    if ok:
        return True, out or "Pairing approved"
    lowered = str(out or "").lower()
    if "already" in lowered and "approve" in lowered:
        return True, out
    return False, out or "Failed to approve pairing code"


def _complete_commander_pairing(
    *,
    commander_username: str,
    pairing_code: str | None,
    non_interactive: bool,
) -> dict[str, Any]:
    selected = str(pairing_code or "").strip()
    if not selected and non_interactive:
        return {"approved": False, "skipped": True, "reason": "no_pairing_code"}

    if not selected:
        bot_ref = f"@{commander_username}" if commander_username else "the Commander bot"
        console.print(
            Panel(
                "Commander Telegram Pairing\n\n"
                f"1) DM {bot_ref} and send any message\n"
                "2) Copy the pairing code from the reply\n"
                "3) Paste it below to approve access now\n\n"
                "Tip: keep this terminal open during pairing.",
                title="Telegram Pairing",
                border_style="cyan",
            )
        )
        selected = Prompt.ask("Commander pairing code (press Enter to skip)", default="").strip()
        if not selected:
            return {"approved": False, "skipped": True, "reason": "user_skipped"}

    ok, detail = _approve_telegram_pairing_code(selected)
    if ok:
        console.print("[green]Commander Telegram pairing approved.[/]")
    else:
        console.print(f"[yellow]Commander pairing not approved yet: {detail}[/]")
        console.print(
            f"[bold white]Run when ready:[/] openclaw --profile maestro-fleet pairing approve telegram {selected}"
        )
    return {"approved": ok, "skipped": False, "pairing_code": selected, "detail": detail}


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
    provider_keys: dict[str, str] | None = None,
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
    gateway = config["gateway"]
    config["gateway"]["mode"] = "local"
    remote = gateway.get("remote") if isinstance(gateway.get("remote"), dict) else {}
    remote["url"] = f"ws://127.0.0.1:{_fleet_gateway_port()}"
    gateway["remote"] = remote

    if not isinstance(config.get("env"), dict):
        config["env"] = {}
    if isinstance(provider_keys, dict):
        for key in KEY_ORDER:
            value = str(provider_keys.get(key, "")).strip()
            if value:
                config["env"][key] = value
    model = canonicalize_model(model, fallback=DEFAULT_COMMANDER_MODEL)
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

    default_workspace = openclaw_workspace_root(
        enforce_profile=True,
    ).resolve()
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
    default_account = accounts.get("default")
    if (
        isinstance(default_account, dict)
        and str(default_account.get("botToken", "")).strip() == telegram_token
    ):
        accounts.pop("default", None)
    telegram.pop("botToken", None)
    binding_changes = ensure_telegram_account_bindings(config)

    save_json(config_path, config)
    return {
        "config_path": str(config_path),
        "workspace_root": str(workspace_root),
        "provider_env_key": provider_env_key or "",
        "binding_changes": binding_changes,
    }


def _fleet_state_dir() -> Path:
    base = (Path.home() / ".maestro" / "fleet").resolve()
    profile = resolve_openclaw_profile(default_profile=FLEET_PROFILE)
    if profile and profile != FLEET_PROFILE:
        # Keep default profile paths stable while isolating test/alternate profiles.
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", profile).strip("._-") or "profile"
        path = base / "profiles" / safe
    else:
        path = base
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_windows() -> bool:
    return os.name == "nt"


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_process_command(pid: int) -> str:
    return fleet_server_runtime.read_process_command(pid, is_windows=(os.name == "nt"))


def _listener_pids(port: int) -> list[int]:
    return fleet_server_runtime.listener_pids(port, is_windows=(os.name == "nt"))


def _is_fleet_server_process(
    pid: int,
    *,
    port: int | None = None,
    store_root: Path | None = None,
    host: str | None = None,
) -> bool:
    return fleet_server_runtime.is_fleet_server_process(
        pid,
        port=port,
        store_root=store_root,
        host=host,
        read_command=_read_process_command,
    )


def _terminate_process(pid: int, *, timeout_seconds: float = 8.0) -> bool:
    if pid <= 0 or not _pid_running(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return not _pid_running(pid)
    end = time.time() + float(timeout_seconds)
    while time.time() < end:
        if not _pid_running(pid):
            return True
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return not _pid_running(pid)
    time.sleep(0.5)
    return not _pid_running(pid)


def _managed_listener_pids(*, port: int, store_root: Path, host: str) -> list[int]:
    return fleet_server_runtime.managed_listener_pids(
        port=port,
        store_root=store_root,
        host=host,
        listener_pids_fn=_listener_pids,
        is_fleet_server_process_fn=lambda pid, process_port, process_store, process_host: _is_fleet_server_process(
            pid,
            port=process_port,
            store_root=process_store,
            host=process_host,
        ),
    )


def _save_detached_server_state(
    *,
    pid_path: Path,
    pid: int,
    port: int,
    host: str,
    store_root: Path,
    command: list[str] | None = None,
):
    fleet_server_runtime.save_detached_server_state(
        pid_path=pid_path,
        pid=pid,
        port=port,
        host=host,
        store_root=store_root,
        command=command,
        now_iso=_now_iso,
        save_json_fn=save_json,
    )


def _port_listening(port: int, host: str = "127.0.0.1") -> bool:
    return fleet_server_runtime.port_listening(port, host)


def _resolve_deploy_port(
    preferred_port: int,
    max_attempts: int = 20,
    *,
    store_root: Path | None = None,
    host: str = "127.0.0.1",
) -> tuple[int, bool]:
    return fleet_server_runtime.resolve_deploy_port(
        preferred_port,
        port_listening_fn=_port_listening,
        managed_listener_pids_fn=lambda port_value, store_value, host_value: _managed_listener_pids(
            port=port_value,
            store_root=store_value,
            host=host_value,
        ),
        store_root=store_root,
        host=host,
        max_attempts=max_attempts,
    )


def _start_detached_server(*, port: int, store_root: Path, host: str) -> dict[str, Any]:
    return fleet_server_runtime.start_detached_server(
        port=port,
        store_root=store_root,
        host=host,
        state_dir=_fleet_state_dir(),
        now_iso=_now_iso,
        load_json_fn=load_json,
        save_json_fn=save_json,
        pid_running_fn=_pid_running,
        terminate_process_fn=_terminate_process,
        managed_listener_pids_fn=lambda port_value, store_value, host_value: _managed_listener_pids(
            port=port_value,
            store_root=store_value,
            host=host_value,
        ),
        listener_pids_fn=_listener_pids,
        is_fleet_server_process_fn=lambda pid, process_port, process_store, process_host: _is_fleet_server_process(
            pid,
            port=process_port,
            store_root=process_store,
            host=process_host,
        ),
        is_windows=_is_windows(),
        start_windows_task_server_fn=lambda port_value, store_value, host_value, pid_path, log_path, command: _start_windows_task_server(
            port=port_value,
            store_root=store_value,
            host=host_value,
            pid_path=pid_path,
            log_path=log_path,
            command=command,
        ),
    )


def _fleet_server_task_name() -> str:
    profile = resolve_openclaw_profile(default_profile=FLEET_PROFILE)
    return fleet_windows_runtime.fleet_server_task_name(profile=str(profile or FLEET_PROFILE))


def _ps_single_quote(value: str) -> str:
    return fleet_windows_runtime.ps_single_quote(value)


def _run_windows_powershell(script: str, *, timeout: int = 45) -> tuple[bool, str]:
    return fleet_windows_runtime.run_windows_powershell(script, timeout=timeout)


def _write_windows_server_task_script(*, script_path: Path, log_path: Path, port: int, store_root: Path, host: str):
    fleet_windows_runtime.write_windows_server_task_script(
        script_path=script_path,
        log_path=log_path,
        port=port,
        store_root=store_root,
        host=host,
        profile=FLEET_PROFILE,
        now_iso=_now_iso,
    )


def _ensure_windows_server_task(*, task_name: str, script_path: Path) -> tuple[bool, str]:
    return fleet_windows_runtime.ensure_windows_server_task(
        task_name=task_name,
        script_path=script_path,
        run_cmd=lambda args, timeout_value: _run_cmd(args, timeout=timeout_value),
    )


def _start_windows_server_task_runner(*, task_name: str) -> tuple[bool, str]:
    return fleet_windows_runtime.start_windows_server_task_runner(
        task_name=task_name,
        run_cmd=lambda args, timeout_value: _run_cmd(args, timeout=timeout_value),
    )


def _start_windows_task_server(
    *,
    port: int,
    store_root: Path,
    host: str,
    pid_path: Path,
    log_path: Path,
    command: list[str] | None = None,
) -> dict[str, Any]:
    task_name = _fleet_server_task_name()
    state_dir = _fleet_state_dir()
    script_path = state_dir / "run-fleet-server.ps1"
    _write_windows_server_task_script(
        script_path=script_path,
        log_path=log_path,
        port=int(port),
        store_root=store_root,
        host=host,
    )
    install_ok, install_out = _ensure_windows_server_task(task_name=task_name, script_path=script_path)
    if not install_ok:
        return {
            "ok": False,
            "detail": f"Failed to register Fleet server task: {install_out}",
            "log_path": str(log_path),
            "pid_path": str(pid_path),
            "task_name": task_name,
        }
    start_ok, start_out = _start_windows_server_task_runner(task_name=task_name)
    deadline = time.time() + 12.0
    listeners: list[int] = []
    while time.time() < deadline:
        listeners = _managed_listener_pids(port=int(port), store_root=store_root, host=host)
        if listeners:
            break
        time.sleep(0.25)
    if not listeners:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            tail = "\n".join(lines[-12:]).strip()
        except Exception:
            tail = ""
        detail = f"Fleet server task did not become healthy: {start_out or install_out}".strip()
        if tail:
            detail = f"{detail}\n{tail}"
        return {
            "ok": False,
            "detail": detail,
            "log_path": str(log_path),
            "pid_path": str(pid_path),
            "task_name": task_name,
        }
    primary_pid = int(listeners[0])
    for extra_pid in listeners[1:]:
        _terminate_process(int(extra_pid))
    _save_detached_server_state(
        pid_path=pid_path,
        pid=primary_pid,
        port=int(port),
        host=host,
        store_root=store_root,
        command=command or [],
    )
    return {
        "ok": True,
        "already_running": False,
        "pid": primary_pid,
        "port": int(port),
        "port_mismatch": False,
        "pid_path": str(pid_path),
        "log_path": str(log_path),
        "task_name": task_name,
        "task_installed": True,
        "task_start_detail": start_out,
        "start_ok": start_ok,
    }


def _verify_command_center_http(port: int, timeout_seconds: int = 60) -> bool:
    return fleet_server_runtime.verify_command_center_http(port, timeout_seconds)


def _gateway_status_snapshot(timeout: int = 12) -> tuple[bool, dict[str, Any], str]:
    return fleet_gateway_runtime.gateway_status_snapshot(
        run_cmd=lambda args, timeout_value: _run_cmd(args, timeout=timeout_value),
        parse_json=_parse_json_from_output,
        timeout=timeout,
    )


def _repair_gateway_device_token_mismatch() -> dict[str, Any]:
    return fleet_gateway_runtime.repair_gateway_device_token_mismatch(
        run_cmd=lambda args, timeout_value: _run_cmd(args, timeout=timeout_value),
        status_snapshot=_gateway_status_snapshot,
        listener_pids=_gateway_listener_pids,
        evict_listener_pids=lambda status, only_pids=None: _evict_gateway_listener_pids(status, only_pids=only_pids),
        fleet_gateway_port=_fleet_gateway_port,
    )


def _gateway_running_from_status(status_out: str) -> bool:
    lowered = str(status_out or "").lower()
    return "gateway service" in lowered and "running" in lowered


def _ensure_gateway_running_for_pairing() -> dict[str, Any]:
    return fleet_gateway_runtime.ensure_gateway_running_for_pairing(
        run_cmd=lambda args, timeout_value: _run_cmd(args, timeout=timeout_value),
        status_snapshot=_gateway_status_snapshot,
        cli_ready=_gateway_cli_ready,
        evict_listener_pids=lambda status, only_pids=None: _evict_gateway_listener_pids(status, only_pids=only_pids),
        fleet_gateway_port=_fleet_gateway_port,
    )


def _commissioning_report(
    *,
    store_root: Path,
    web_port: int,
    require_tailscale: bool,
    expected_project_slug: str,
    services_started: bool,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    config, _ = _load_openclaw_config()
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    commander = next(
        (
            item for item in agent_list
            if isinstance(item, dict) and str(item.get("id", "")).strip() == "maestro-company"
        ),
        None,
    )
    checks.append({
        "name": "commander_agent",
        "ok": isinstance(commander, dict),
        "level": "critical",
        "detail": "maestro-company present" if isinstance(commander, dict) else "maestro-company agent missing",
        "fix": "maestro-fleet deploy",
    })
    checks.append({
        "name": "commander_default",
        "ok": bool(commander.get("default")) if isinstance(commander, dict) else False,
        "level": "critical",
        "detail": "maestro-company is default agent" if isinstance(commander, dict) and bool(commander.get("default")) else "maestro-company is not default",
        "fix": "maestro-fleet commander set-model --model anthropic/claude-opus-4-6",
    })

    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram", {}) if isinstance(channels.get("telegram"), dict) else {}
    accounts = telegram.get("accounts", {}) if isinstance(telegram.get("accounts"), dict) else {}
    has_commander_binding = isinstance(accounts.get("maestro-company"), dict)
    checks.append({
        "name": "commander_telegram_account",
        "ok": has_commander_binding,
        "level": "critical",
        "detail": "Commander Telegram account configured" if has_commander_binding else "Commander Telegram account missing",
        "fix": "maestro-fleet deploy",
    })

    gw_ok, gw_out = _run_cmd(["openclaw", "gateway", "status", "--json"], timeout=12)
    gw_status = _parse_json_from_output(gw_out)
    openclaw_running = _gateway_service_running(gw_status)
    checks.append({
        "name": "openclaw_gateway",
        "ok": openclaw_running,
        "level": "warning",
        "detail": gw_out or "openclaw gateway status unavailable",
        "fix": "openclaw gateway restart",
    })

    command_center_ok = True
    if services_started:
        command_center_ok = _verify_command_center_http(int(web_port), timeout_seconds=6)
    checks.append({
        "name": "command_center_api",
        "ok": bool(command_center_ok),
        "level": "critical" if services_started else "warning",
        "detail": (
            f"http://127.0.0.1:{int(web_port)}/api/command-center/state reachable"
            if command_center_ok else f"http://127.0.0.1:{int(web_port)}/api/command-center/state unavailable"
        ),
        "fix": "maestro-fleet up --tui",
    })

    registry = sync_fleet_registry(store_root)
    projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    active_projects = [
        item for item in projects
        if isinstance(item, dict) and str(item.get("status", "active")).strip().lower() != "archived"
    ]
    slug_counts: dict[str, int] = {}
    for item in active_projects:
        slug = str(item.get("project_slug", "")).strip()
        if not slug:
            continue
        slug_counts[slug] = slug_counts.get(slug, 0) + 1
    duplicate_slugs = sorted(slug for slug, count in slug_counts.items() if count > 1)
    checks.append({
        "name": "registry_projects",
        "ok": True,
        "level": "warning",
        "detail": f"{len(active_projects)} active project maestro(s) registered",
        "fix": "maestro-fleet project create --project-name \"...\" --assignee \"...\"",
    })
    checks.append({
        "name": "registry_unique_project_slugs",
        "ok": len(duplicate_slugs) == 0,
        "level": "critical",
        "detail": (
            "All active registry project slugs are unique"
            if not duplicate_slugs else f"Duplicate registry project slugs: {', '.join(duplicate_slugs)}"
        ),
        "fix": "Consolidate duplicate project stores so each project slug maps to one knowledge_store directory",
    })
    if expected_project_slug:
        expected_exists = any(
            str(item.get("project_slug", "")).strip() == expected_project_slug
            for item in active_projects if isinstance(item, dict)
        )
        checks.append({
            "name": "initial_project_registered",
            "ok": expected_exists,
            "level": "critical",
            "detail": (
                f"Initial project '{expected_project_slug}' registered"
                if expected_exists else f"Initial project '{expected_project_slug}' missing from registry"
            ),
            "fix": "maestro-fleet project create --project-name \"...\" --assignee \"...\"",
        })

    tailscale_ok = True
    tailscale_detail = "Tailscale check not required"
    if require_tailscale:
        tailscale_cmd_ok, tailscale_out = _run_cmd(["tailscale", "ip", "-4"], timeout=8)
        tailscale_ok = bool(tailscale_cmd_ok and str(tailscale_out).strip())
        tailscale_detail = str(tailscale_out).strip() or "No tailnet IPv4 detected"
    checks.append({
        "name": "tailscale_access",
        "ok": tailscale_ok,
        "level": "critical" if require_tailscale else "warning",
        "detail": tailscale_detail,
        "fix": "tailscale up",
    })

    critical_failures = [item for item in checks if item.get("level") == "critical" and not bool(item.get("ok"))]
    return {
        "ok": len(critical_failures) == 0,
        "checks": checks,
        "critical_failures": critical_failures,
    }


def _print_commissioning_report(report: dict[str, Any]):
    checks = report.get("checks", []) if isinstance(report, dict) else []
    lines: list[str] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        dot = "[green]PASS[/]" if bool(item.get("ok")) else "[red]FAIL[/]"
        level = str(item.get("level", "")).strip().lower()
        name = str(item.get("name", "")).strip()
        detail = str(item.get("detail", "")).strip()
        fix = str(item.get("fix", "")).strip()
        lines.append(f"{dot}  {name} ({level})")
        if detail:
            lines.append(f"[dim]      {detail}[/]")
        if not bool(item.get("ok")) and fix:
            lines.append(f"[yellow]      fix: {fix}[/]")
    title = "Commander Commissioning: READY" if bool(report.get("ok")) else "Commander Commissioning: ACTION REQUIRED"
    border = "green" if bool(report.get("ok")) else "red"
    console.print(Panel("\n".join(lines) if lines else "No checks executed.", title=title, border_style=border))


def run_deploy(
    *,
    company_name: str | None = None,
    model: str | None = None,
    commander_model: str | None = None,
    project_model: str | None = None,
    api_key: str | None = None,
    gemini_api_key: str | None = None,
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    telegram_token: str | None = None,
    commander_pairing_code: str | None = None,
    project_name: str | None = None,
    assignee: str | None = None,
    superintendent: str | None = None,
    project_telegram_token: str | None = None,
    provision_initial_project: bool = False,
    store_override: str | None = None,
    port: int = 3000,
    host: str = "0.0.0.0",
    non_interactive: bool = False,
    skip_remote_validation: bool = False,
    require_tailscale: bool = False,
    allow_openclaw_override: bool = False,
    start_services: bool = True,
) -> int:
    console.print("[bold cyan]Maestro Fleet Deploy[/]")
    console.print("One-session deployment for remote customer handoff.")
    console.print("[dim]Goal: leave this machine fully operational before disconnecting.[/]")
    interactive_setup = not bool(non_interactive)
    total_steps = len(DEPLOY_STEP_TITLES)

    # FLEET_STEP_1_PREREQS
    _step_header(1, total_steps, _deploy_step_title(1), enabled=interactive_setup)
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

    collision = _check_shared_gateway_collision(target_gateway_port=_fleet_gateway_port())
    if collision.get("blocked"):
        shared_port = int(collision.get("shared_port", 18789))
        console.print(
            "[red]Unsupported topology: same-user OpenClaw + Fleet on one machine.[/]\n"
            f"[yellow]Detected an active shared OpenClaw gateway on port {shared_port}.[/]\n"
            "[yellow]Fleet deploy is intentionally blocked to prevent cross-routing and token bleed.[/]\n"
            "[bold white]Supported options:[/]\n"
            "  1) Use a fresh machine for Fleet, or\n"
            "  2) Use a separate OS user account dedicated to Fleet\n"
            "[bold white]Temporary local test workaround (same user, unsupported):[/]\n"
            "  - Stop shared gateway: openclaw gateway stop\n"
            "  - Run Fleet deploy\n"
            "  - Re-enable shared gateway only after Fleet work: openclaw gateway start"
        )
        return 1

    update_code = run_update(restart_gateway=False, dry_run=False)
    if update_code != 0:
        return update_code

    # FLEET_STEP_2_MODELS
    _step_header(2, total_steps, _deploy_step_title(2), enabled=interactive_setup)
    config, _ = _load_openclaw_config()
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    default_model = default_model_from_agents(agent_list, fallback=DEFAULT_COMMANDER_MODEL)
    selected_model = canonicalize_model(commander_model or model or default_model, fallback=DEFAULT_COMMANDER_MODEL)
    if interactive_setup and not str(commander_model or model or "").strip():
        selected_model = _prompt_model_selection(
            title="Commander Model",
            default_model=selected_model,
            non_interactive=non_interactive,
        )
    selected_project_model = canonicalize_model(project_model or selected_model, fallback=DEFAULT_PROJECT_MODEL)
    if interactive_setup and not str(project_model or "").strip():
        selected_project_model = _prompt_model_selection(
            title="Default Project Maestro Model",
            default_model=selected_project_model,
            non_interactive=non_interactive,
        )
    provider_env_key = provider_env_key_for_model(selected_model)
    if not provider_env_key:
        console.print(f"[red]Unsupported commander model: {selected_model}[/]")
        return 1

    # FLEET_STEP_3_COMPANY_PROFILE
    _step_header(3, total_steps, _deploy_step_title(3), enabled=interactive_setup)
    env = config.get("env", {}) if isinstance(config.get("env"), dict) else {}
    chosen_company_name = str(company_name or "").strip()
    if not chosen_company_name:
        if non_interactive:
            chosen_company_name = "Company"
        else:
            chosen_company_name = Prompt.ask("Company name", default="Company").strip() or "Company"

    # FLEET_STEP_4_PROVIDER_KEYS
    _step_header(4, total_steps, _deploy_step_title(4), enabled=interactive_setup)
    provider_inputs = {
        "GEMINI_API_KEY": str(gemini_api_key or "").strip(),
        "OPENAI_API_KEY": str(openai_api_key or "").strip(),
        "ANTHROPIC_API_KEY": str(anthropic_api_key or "").strip(),
    }
    legacy_key = str(api_key or "").strip()
    if legacy_key and provider_env_key and not provider_inputs.get(provider_env_key):
        provider_inputs[provider_env_key] = legacy_key

    for env_key in KEY_ORDER:
        provided_value = str(provider_inputs.get(env_key, "")).strip()
        existing_value = str(env.get(env_key, "")).strip()
        required = env_key == "GEMINI_API_KEY" and interactive_setup
        selected_key, ok = _collect_provider_key(
            provider_env_key=env_key,
            provided_key=provided_value,
            existing_key=existing_value,
            non_interactive=non_interactive,
            skip_remote_validation=skip_remote_validation,
            required=required,
        )
        if not ok:
            return 1
        provider_inputs[env_key] = selected_key

    selected_api_key = str(provider_inputs.get(provider_env_key, "")).strip()
    if not selected_api_key:
        console.print(f"[red]Missing key for commander model provider: {provider_env_key}[/]")
        return 1

    # FLEET_STEP_5_COMMANDER_TELEGRAM
    _step_header(5, total_steps, _deploy_step_title(5), enabled=interactive_setup)
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
            provider_keys=provider_inputs,
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
            "commander_model": selected_model,
            "project_model": selected_project_model,
            "updated_at": _now_iso(),
        }
    )

    # FLEET_STEP_6_INITIAL_PROJECT
    _step_header(6, total_steps, _deploy_step_title(6), enabled=interactive_setup)
    initial_project_args_present = bool(project_name or assignee or project_telegram_token)
    create_project = bool(provision_initial_project)
    if initial_project_args_present and not create_project:
        console.print(
            "[yellow]Initial project arguments were provided, but deploy defaults to commander-only mode.[/]\n"
            "[yellow]Re-run with --provision-initial-project to create a project maestro during install.[/]"
        )
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

        project_provider_env_key = provider_env_key_for_model(selected_project_model)
        project_api_key = str(provider_inputs.get(project_provider_env_key or "", "")).strip()
        if project_provider_env_key and not project_api_key:
            console.print(
                f"[red]Missing {project_provider_env_key} required for project model {selected_project_model}[/]"
            )
            return 1

        purchase_code = run_project_create(
            project_name=chosen_project_name,
            assignee=chosen_assignee,
            superintendent=superintendent,
            model=selected_project_model,
            api_key=project_api_key,
            telegram_token=selected_project_telegram,
            store_override=str(store_root),
            dry_run=False,
            json_output=False,
            non_interactive=True,
            skip_remote_validation=bool(skip_remote_validation),
            allow_openclaw_override=bool(allow_openclaw_override),
        )
        if purchase_code != 0:
            return purchase_code
        project_slug = slugify(chosen_project_name)
    else:
        project_slug = ""
        if interactive_setup:
            console.print(
                "[dim]Skipping initial project provisioning. "
                "Create project maestros later with `maestro-fleet project create`.[/]"
            )

    # FLEET_STEP_7_DOCTOR_RUNTIME
    _step_header(7, total_steps, _deploy_step_title(7), enabled=interactive_setup)
    doctor_result = _run_doctor_for_deploy(store_root=store_root)
    doctor_output = str(doctor_result.get("output") or "").strip()
    if doctor_output:
        # Doctor output can include bracketed filesystem paths (e.g. [/Users/...]),
        # which Rich may interpret as markup tags. Render as plain text.
        console.print(doctor_output, markup=False)
    doctor_code = int(doctor_result.get("code", 1))
    if bool(doctor_result.get("timed_out")):
        console.print(
            "[yellow]Doctor timed out during deploy; continuing with gateway/runtime checks.[/]"
        )
    elif doctor_code != 0:
        return doctor_code
    if interactive_setup:
        console.print(
            "[dim]Doctor URL is pre-runtime. Use the final Fleet Deployment Summary URL for access.[/]"
        )

    gateway_repair = _repair_gateway_device_token_mismatch()
    if gateway_repair.get("mismatch_detected"):
        if gateway_repair.get("repaired"):
            console.print("[green]Gateway device-token mismatch detected and repaired.[/]")
        else:
            console.print(
                "[yellow]Gateway device-token mismatch detected and auto-repair did not fully resolve.[/]\n"
                f"[yellow]Run: openclaw --profile maestro-fleet gateway install --force --port {_fleet_gateway_port()} && "
                "openclaw --profile maestro-fleet gateway restart[/]"
            )

    gateway_for_pairing = _ensure_gateway_running_for_pairing()
    if gateway_for_pairing.get("ok"):
        if not gateway_for_pairing.get("already_running"):
            console.print("[green]Gateway confirmed running for Telegram pairing.[/]")
        pairing_result = _complete_commander_pairing(
            commander_username=tg_username,
            pairing_code=commander_pairing_code,
            non_interactive=bool(non_interactive),
        )
    else:
        action_lines = gateway_for_pairing.get("actions", [])
        action_text = "\n".join(f"- {line}" for line in action_lines if isinstance(line, str) and line.strip())
        console.print(
            "[yellow]Gateway is not running after auto-retry; skipping Telegram pairing approval for now.[/]\n"
            "[yellow]Run: openclaw --profile maestro-fleet gateway restart[/]"
        )
        if action_text:
            console.print(f"[dim]Gateway recovery attempts:\n{action_text}[/]")
        pairing_result = {
            "approved": False,
            "skipped": True,
            "reason": "gateway_not_running",
            "detail": str(gateway_for_pairing.get("detail") or gateway_for_pairing.get("restart_detail") or "").strip(),
        }

    requested_port = int(port)
    effective_port = requested_port
    detached = {"ok": True, "already_running": False, "pid": 0, "pid_path": "", "log_path": ""}
    if start_services:
        resolved_port, shifted_port = _resolve_deploy_port(
            requested_port,
            store_root=store_root,
            host=str(host),
        )
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
                "[yellow]Fleet server process started but command-center health check did not pass in time.[/]\n"
                f"[yellow]Check logs: {detached.get('log_path', '')}[/]"
            )

    # FLEET_STEP_8_COMMISSIONING
    _step_header(8, total_steps, _deploy_step_title(8), enabled=interactive_setup)
    commissioning = _commissioning_report(
        store_root=store_root,
        web_port=effective_port,
        require_tailscale=bool(require_tailscale),
        expected_project_slug=project_slug,
        services_started=bool(start_services),
    )
    _print_commissioning_report(commissioning)
    commissioning_ready = bool(commissioning.get("ok"))

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
    tailnet_url = str(network.get("tailnet_url") or "").strip()

    summary_lines = [
        f"Company: {chosen_company_name}",
        f"Profile: fleet",
        f"Store Root: {store_root}",
        f"Workspace Root: {company_cfg['workspace_root']}",
        f"Commander Model: {format_model_display(selected_model)}",
        f"Project Model: {format_model_display(selected_project_model)}",
        "Project Provisioning: direct",
        f"Command Center: {command_center_url}",
        f"Command Center (local): {local_url}",
    ]
    for key_name in KEY_ORDER:
        summary_lines.append(
            f"{KEY_LABELS.get(key_name, key_name)}: {'configured' if provider_inputs.get(key_name) else 'missing'}"
        )
    if tailnet_url:
        summary_lines.append(f"Command Center (tailnet): {tailnet_url}")
    if start_services:
        if detached.get("already_running"):
            summary_lines.append(f"Server Process: already running (pid {detached.get('pid')})")
        else:
            summary_lines.append(f"Server Process: started (pid {detached.get('pid')})")
        summary_lines.append(f"Server PID File: {detached.get('pid_path')}")
        summary_lines.append(f"Server Log: {detached.get('log_path')}")
    summary_lines.append("Runtime TUI: maestro-fleet up --tui")
    summary_lines.append(f"Text the Commander: @{company_username}" if company_username else "Text the Commander: configured")
    summary_lines.append(
        f"Commander Telegram Pairing: {'Approved' if pairing_result.get('approved') else 'Pending'}"
        if isinstance(pairing_result, dict) else "Commander Telegram Pairing: Pending"
    )
    if isinstance(pairing_result, dict) and not pairing_result.get("approved"):
        code_hint = str(pairing_result.get("pairing_code", "")).strip()
        if code_hint:
            summary_lines.append(
                f"Approve pairing now: openclaw --profile maestro-fleet pairing approve telegram {code_hint}"
            )
        else:
            summary_lines.append("Approve pairing now: openclaw --profile maestro-fleet pairing approve telegram <CODE>")
    if gateway_repair.get("mismatch_detected"):
        summary_lines.append(
            "Gateway Auth Recovery: repaired"
            if gateway_repair.get("repaired") else "Gateway Auth Recovery: manual follow-up required"
        )
    summary_lines.append(
        "Gateway Ready for Pairing: yes" if gateway_for_pairing.get("ok") else "Gateway Ready for Pairing: no"
    )
    summary_lines.append("Gateway Status: openclaw --profile maestro-fleet gateway status --json")
    if project_slug:
        if project_username:
            summary_lines.append(f"Text initial project Maestro: @{project_username}")
        else:
            summary_lines.append(f"Initial project Maestro slug: {project_slug}")
    else:
        summary_lines.append("Initial project Maestro: not provisioned")
        summary_lines.append("Create one later: maestro-fleet project create --project-name \"...\" --assignee \"...\"")
    summary_lines.append(
        "Commander Commissioning: READY"
        if commissioning_ready else "Commander Commissioning: ACTION REQUIRED"
    )

    console.print()
    console.print(
        Panel(
            "\n".join(summary_lines),
            title="Fleet Deployment Summary",
            border_style="cyan" if commissioning_ready else "yellow",
        )
    )
    return 0
