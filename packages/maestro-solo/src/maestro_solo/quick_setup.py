"""Fast-path setup flow for one-command Maestro Solo bootstrap on macOS."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .doctor import run_doctor
from .entitlements import entitlement_label, has_capability, normalize_tier, resolve_effective_entitlement
from .install_flow import resolve_install_runtime
from .install_state import load_install_state, save_install_state
from .openclaw_config_transform import SoloConfigTransformRequest, transform_openclaw_config
from .openclaw_runtime import (
    DEFAULT_MAESTRO_GATEWAY_PORT,
    DEFAULT_MAESTRO_OPENCLAW_PROFILE,
    ensure_safe_openclaw_write_target,
    prepend_openclaw_profile_args,
)
from .solo_license import ensure_local_trial_license
from .workspace_templates import render_personal_agents_md, render_personal_tools_md, render_workspace_env


CYAN = "cyan"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"

console = Console(force_terminal=True if platform.system() == "Windows" else None)

NATIVE_PLUGIN_ID = "maestro-native-tools"
NATIVE_PLUGIN_DENY_TOOLS = ["browser", "web_search", "web_fetch", "canvas", "nodes"]
OPENAI_OAUTH_PLUGIN_ID = "maestro-openai-codex-auth"
OPENAI_OAUTH_PROVIDER_ID = "openai-codex"
LEGACY_SHARED_GATEWAY_PORT = 18789


def _success(text: str):
    console.print(f"  [green]OK[/] {text}")


def _warning(text: str):
    console.print(f"  [yellow]WARN[/] {text}")


def _error(text: str):
    console.print(f"  [red]FAIL[/] {text}")


def _info(text: str):
    console.print(f"  [{CYAN}]INFO[/] {text}")


def _run_command(args: list[str], *, timeout: int = 120, capture: bool = True) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)

    if capture:
        output_parts = []
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(stderr)
        output = "\n".join(output_parts).strip()
    else:
        output = ""
    return result.returncode == 0, output


def _run_command_in_dir(args: list[str], *, cwd: Path, timeout: int = 120, capture: bool = True) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=capture,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
        )
    except Exception as exc:
        return False, str(exc)

    if capture:
        output_parts = []
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(stderr)
        output = "\n".join(output_parts).strip()
    else:
        output = ""
    return result.returncode == 0, output


def _tail_output(output: str, *, lines: int = 25, max_chars: int = 2200) -> str:
    text = str(output or "").strip()
    if not text:
        return ""
    selected = "\n".join(text.splitlines()[-lines:]).strip()
    if len(selected) > max_chars:
        return selected[-max_chars:]
    return selected


def _run_interactive_command(args: list[str], *, timeout: int = 0) -> int:
    try:
        result = subprocess.run(
            args,
            check=False,
            timeout=None if timeout <= 0 else timeout,
        )
        return int(result.returncode)
    except Exception:
        return 1


def _openclaw_oauth_profile_exists(provider_id: str, *, openclaw_root: Path) -> bool:
    provider = str(provider_id or "").strip().lower()
    if not provider:
        return False

    def _entry_has_oauth_token(entry: object, expected_provider: str) -> bool:
        if not isinstance(entry, dict):
            return False
        provider_value = str(entry.get("provider", expected_provider)).strip().lower()
        entry_type = str(entry.get("type", "oauth")).strip().lower()
        if provider_value != expected_provider or entry_type != "oauth":
            return False
        for key in ("access", "refresh", "token"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    agents_root = openclaw_root / "agents"
    if not agents_root.exists():
        return False

    candidate_files: list[Path] = []
    candidate_files.extend(sorted(agents_root.glob("*/agent/auth-profiles.json")))
    candidate_files.extend(sorted(agents_root.glob("*/agent/auth.json")))

    for path in candidate_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        profiles = payload.get("profiles")
        if isinstance(profiles, dict):
            for entry in profiles.values():
                if _entry_has_oauth_token(entry, provider):
                    return True

        direct = payload.get(provider)
        if _entry_has_oauth_token(direct, provider):
            return True

        for entry in payload.values():
            if _entry_has_oauth_token(entry, provider):
                return True

    return False


def _discover_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "workspace_frontend").exists() and (parent / "packages").exists():
            return parent
    return current.parent


def _load_openclaw_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _validate_gemini_key(key: str) -> tuple[bool, str]:
    clean = str(key or "").strip()
    if len(clean) < 20:
        return False, "key_too_short"
    try:
        response = httpx.get(
            f"https://generativelanguage.googleapis.com/v1/models?key={clean}",
            timeout=12,
        )
    except Exception as exc:
        return False, str(exc)
    if response.status_code != 200:
        return False, f"http_{response.status_code}"
    return True, ""


def _validate_telegram_token(token: str) -> tuple[bool, str]:
    clean = str(token or "").strip()
    if not re.match(r"^\d+:[A-Za-z0-9_-]+$", clean):
        return False, "invalid_token_format"
    try:
        response = httpx.get(f"https://api.telegram.org/bot{clean}/getMe", timeout=12)
        payload = response.json()
    except Exception as exc:
        return False, str(exc)
    if response.status_code != 200 or not isinstance(payload, dict) or not payload.get("ok"):
        return False, f"http_{response.status_code}"
    result = payload.get("result")
    if not isinstance(result, dict):
        return False, "malformed_bot_metadata"
    username = str(result.get("username", "")).strip()
    if not username:
        return False, "missing_bot_username"
    return True, username


def _parse_gateway_port(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 65535 else None
    if isinstance(value, str):
        clean = value.strip()
        if clean.isdigit():
            port = int(clean)
            if 1 <= port <= 65535:
                return port
    return None


def _port_is_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False


def _resolve_maestro_gateway_port(config: dict[str, Any]) -> int:
    gateway = config.get("gateway") if isinstance(config.get("gateway"), dict) else {}
    configured = _parse_gateway_port(gateway.get("port"))
    if configured is not None and configured != LEGACY_SHARED_GATEWAY_PORT:
        return configured

    for candidate in range(DEFAULT_MAESTRO_GATEWAY_PORT, DEFAULT_MAESTRO_GATEWAY_PORT + 16):
        if _port_is_available(candidate):
            return candidate

    return DEFAULT_MAESTRO_GATEWAY_PORT


class QuickSetup:
    """Quick setup path: minimum required for a live Maestro Solo runtime."""

    def __init__(self, *, company_name: str = "", replay: bool = False):
        state = load_install_state()
        state_company_name = str(state.get("company_name", "")).strip()
        provided_company_name = str(company_name).strip()
        self.setup_completed = bool(state.get("setup_completed"))
        self.replay_requested = bool(replay)
        self.replay_existing = bool(self.replay_requested and self.setup_completed)
        self.company_name = provided_company_name or state_company_name or "Company"
        self.company_name_from_state = bool(state_company_name)
        self.company_name_provided = bool(provided_company_name)
        self.install_id = str(state.get("install_id", "")).strip() or str(uuid.uuid4())
        self.provider = "openai"
        self.provider_env_key = "OPENAI_API_KEY"
        self.model = "openai-codex/gpt-5.2"
        self.model_auth_method = "openclaw_oauth"

        runtime = resolve_install_runtime(
            workspace_dir="workspace-maestro-solo",
            store_subdir="knowledge_store",
            openclaw_profile_default=DEFAULT_MAESTRO_OPENCLAW_PROFILE,
        )
        self.openclaw_profile = runtime.openclaw_profile
        self.openclaw_root = runtime.openclaw_root
        self.openclaw_config_file = self.openclaw_root / "openclaw.json"

        openclaw_config = _load_openclaw_config(self.openclaw_config_file)
        openclaw_env = openclaw_config.get("env") if isinstance(openclaw_config.get("env"), dict) else {}
        openclaw_channels = openclaw_config.get("channels") if isinstance(openclaw_config.get("channels"), dict) else {}
        telegram_cfg = openclaw_channels.get("telegram") if isinstance(openclaw_channels.get("telegram"), dict) else {}
        telegram_accounts = telegram_cfg.get("accounts") if isinstance(telegram_cfg.get("accounts"), dict) else {}
        personal_telegram_cfg = (
            telegram_accounts.get("maestro-solo-personal")
            if isinstance(telegram_accounts.get("maestro-solo-personal"), dict)
            else {}
        )

        self.gemini_key = str(openclaw_env.get("GEMINI_API_KEY", "")).strip()
        self.telegram_token = str(personal_telegram_cfg.get("botToken", "")).strip()
        self.gateway_port = _resolve_maestro_gateway_port(openclaw_config)
        self.bot_username = ""
        self.tailscale_ip = ""
        self.pending_optional_setup: list[str] = ["ingest_plans"]
        self.workspace = runtime.workspace_root
        self.store_root = runtime.store_root
        self.trial_info: dict[str, Any] = {}
        self.entitlement: dict[str, Any] = resolve_effective_entitlement()
        self.tier = normalize_tier(str(self.entitlement.get("tier", "core")))

    def _openclaw_label(self) -> str:
        return self.openclaw_profile or "default"

    def _openclaw_cmd(self, args: list[str]) -> list[str]:
        return prepend_openclaw_profile_args(["openclaw", *args], profile=self.openclaw_profile)

    def _run_openclaw_command(self, args: list[str], *, timeout: int = 120, capture: bool = True) -> tuple[bool, str]:
        return _run_command(self._openclaw_cmd(args), timeout=timeout, capture=capture)

    def _run_openclaw_interactive(self, args: list[str], *, timeout: int = 0) -> int:
        return _run_interactive_command(self._openclaw_cmd(args), timeout=timeout)

    def _ensure_safe_openclaw_write_target(self) -> bool:
        ok, message = ensure_safe_openclaw_write_target(self.openclaw_root)
        if ok:
            return True
        _error(message)
        return False

    def run(self) -> int:
        if not self._intro():
            return 1
        if not self._company_name_step():
            return 1
        if not self._prerequisites_step():
            return 1
        if not self._openai_oauth_step():
            return 1
        if not self._gemini_required_step():
            return 1
        if not self._telegram_required_step():
            return 1
        if not self._configure_openclaw_and_workspace_step():
            return 1
        if not self._pair_telegram_required_step():
            return 1
        if not self._trial_license_step():
            return 1
        if not self._doctor_fix_step():
            return 1
        if not self._tailscale_optional_step():
            return 1
        self._save_install_state()
        self._summary()
        return 0

    def _intro(self) -> bool:
        console.print()
        console.print(Rule(style=CYAN))
        console.print(Align.center(Text("M A E S T R O", style=f"bold {BRIGHT_CYAN}")))
        console.print(Align.center(Text("Quick Setup (macOS)", style=DIM)))
        console.print(Rule(style=CYAN))
        body = (
            "This flow configures only what is required to get Maestro live:\n"
            "OpenClaw + OpenAI OAuth + Gemini key + Telegram pairing.\n\n"
            "Optional setup stays deferred and Maestro can guide it later."
        )
        if self.replay_existing:
            body += (
                "\n\nReplay mode is active: existing setup is re-validated and "
                "prompts are skipped where possible."
            )
        console.print(Panel(
            body,
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Quick Setup[/]",
            width=72,
        ))
        if platform.system() != "Darwin":
            _error("Quick setup currently supports macOS only.")
            return False
        _info(f"OpenClaw profile: {self._openclaw_label()} ({self.openclaw_root})")
        _info(f"OpenClaw gateway port: {self.gateway_port}")
        return True

    def _company_name_step(self) -> bool:
        console.print()
        if self.setup_completed and self.company_name:
            _success(f"Company: {self.company_name}")
            return True
        if self.company_name_from_state and not self.company_name_provided and self.company_name:
            _success(f"Company: {self.company_name} (saved)")
            self._checkpoint_company_name()
            return True
        default_name = self.company_name
        entered = Prompt.ask(
            f"  [{CYAN}]Company name[/]",
            default=default_name,
            console=console,
        ).strip()
        self.company_name = entered or default_name
        if not self.company_name:
            _error("Company name is required.")
            return False
        self._checkpoint_company_name()
        _success(f"Company: {self.company_name}")
        return True

    def _checkpoint_company_name(self):
        state = load_install_state()
        state.update({
            "version": 1,
            "product": "maestro-solo",
            "install_id": self.install_id,
            "company_name": self.company_name,
            "openclaw_profile": self.openclaw_profile,
            "setup_mode": "quick",
            "setup_completed": bool(state.get("setup_completed", False)),
        })
        save_install_state(state)

    def _prerequisites_step(self) -> bool:
        console.print()
        console.print(Panel(
            "Checking prerequisites and auto-installing missing packages when approved.",
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Prerequisites[/]",
            width=72,
        ))

        if tuple(int(x) for x in platform.python_version_tuple()[:2]) < (3, 11):
            _error(f"Python {platform.python_version()} detected. Python 3.11+ is required.")
            _info("Install Python 3.11+ and re-run quick setup.")
            return False
        _success(f"Python {platform.python_version()}")

        if not self._ensure_homebrew():
            return False
        if not self._ensure_node_and_npm():
            return False
        if not self._ensure_openclaw():
            return False

        _success("Prerequisites complete")
        return True

    def _ensure_homebrew(self) -> bool:
        if shutil.which("brew"):
            _success("Homebrew available")
            return True

        _warning("Homebrew is missing.")
        install_now = Confirm.ask(
            f"  [{CYAN}]Install Homebrew now?[/]",
            default=True,
            console=console,
        )
        if not install_now:
            _error("Homebrew is required for automatic prerequisite install.")
            return False

        rc = _run_interactive_command([
            "/bin/bash",
            "-c",
            "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)",
        ])
        if rc != 0:
            _error("Homebrew install failed.")
            return False

        for brew_path in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
            path = Path(brew_path)
            if path.exists():
                os.environ["PATH"] = f"{path.parent}:{os.environ.get('PATH', '')}"
                break

        if not shutil.which("brew"):
            _error("Homebrew installed but not on PATH. Open a new terminal and rerun.")
            return False

        _success("Homebrew installed")
        return True

    def _ensure_node_and_npm(self) -> bool:
        node_ok = shutil.which("node") is not None
        npm_ok = shutil.which("npm") is not None
        if node_ok and npm_ok:
            ok, node_out = _run_command(["node", "--version"])
            ok_npm, npm_out = _run_command(["npm", "--version"])
            _success(f"Node.js {node_out if ok else 'available'}")
            _success(f"npm {npm_out if ok_npm else 'available'}")
            return True

        _warning("Node.js/npm missing.")
        install_now = Confirm.ask(
            f"  [{CYAN}]Install Node.js now (brew install node)?[/]",
            default=True,
            console=console,
        )
        if not install_now:
            _error("Node.js and npm are required.")
            return False

        rc = _run_interactive_command(["brew", "install", "node"])
        if rc != 0:
            _error("Node.js install failed.")
            return False

        if shutil.which("node") is None or shutil.which("npm") is None:
            _error("Node.js install completed but node/npm not found on PATH.")
            return False

        ok, node_out = _run_command(["node", "--version"])
        ok_npm, npm_out = _run_command(["npm", "--version"])
        _success(f"Node.js {node_out if ok else 'installed'}")
        _success(f"npm {npm_out if ok_npm else 'installed'}")
        return True

    def _ensure_openclaw(self) -> bool:
        if shutil.which("openclaw"):
            ok, out = _run_command(["openclaw", "--version"])
            _success(f"OpenClaw {out if ok else 'available'}")
            return True

        _warning("OpenClaw is missing.")
        install_now = Confirm.ask(
            f"  [{CYAN}]Install OpenClaw now (npm install -g openclaw)?[/]",
            default=True,
            console=console,
        )
        if not install_now:
            _error("OpenClaw is required.")
            return False

        rc = _run_interactive_command(["npm", "install", "-g", "openclaw"])
        if rc != 0:
            _error("OpenClaw install failed.")
            return False

        if shutil.which("openclaw") is None:
            _error("OpenClaw install completed but command not found on PATH.")
            return False

        ok, out = _run_command(["openclaw", "--version"])
        _success(f"OpenClaw {out if ok else 'installed'}")
        return True

    def _openai_oauth_step(self) -> bool:
        console.print()
        console.print(Panel(
            "OpenAI OAuth is required in quick setup.\n"
            "This avoids manual API-key setup and uses your ChatGPT/OpenAI account.",
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]OpenAI OAuth[/]",
            width=72,
        ))

        if _openclaw_oauth_profile_exists(OPENAI_OAUTH_PROVIDER_ID, openclaw_root=self.openclaw_root):
            _success("Existing OpenAI OAuth profile found")
            return True

        if not self._ensure_openai_oauth_provider_plugin():
            _error("OpenAI OAuth provider bootstrap failed.")
            return False

        profile_cmd = " ".join(self._openclaw_cmd(["models", "auth", "login", "--provider", OPENAI_OAUTH_PROVIDER_ID]))
        _info(f"Starting OAuth login: {profile_cmd}")
        rc = self._run_openclaw_interactive(["models", "auth", "login", "--provider", OPENAI_OAUTH_PROVIDER_ID])
        if rc == 0 and _openclaw_oauth_profile_exists(OPENAI_OAUTH_PROVIDER_ID, openclaw_root=self.openclaw_root):
            _success("OpenAI OAuth configured")
            return True

        _warning("OAuth login command did not complete.")
        if _openclaw_oauth_profile_exists(OPENAI_OAUTH_PROVIDER_ID, openclaw_root=self.openclaw_root):
            _success("OpenAI OAuth configured")
            return True
        _info(f"Run this command and then rerun Maestro setup: {profile_cmd}")
        _error("OpenAI OAuth is required and is not configured.")
        return False

    def _locate_extension_source(self, extension_id: str) -> Path | None:
        module_dir = Path(__file__).resolve().parent
        repo_root = _discover_repo_root()
        candidate_dirs = [
            module_dir / "agent",
            repo_root / "agent",
            repo_root,
            module_dir,
        ]

        for base in candidate_dirs:
            candidate = base / "extensions" / extension_id
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def _ensure_openai_oauth_provider_plugin(self) -> bool:
        if not self._ensure_safe_openclaw_write_target():
            return False

        source_dir = self._locate_extension_source(OPENAI_OAUTH_PLUGIN_ID)
        if source_dir is None:
            _warning("Could not locate Maestro OpenAI OAuth plugin files.")
            return False

        config_dir = self.openclaw_root
        extensions_dir = config_dir / "extensions"
        extension_dst = extensions_dir / OPENAI_OAUTH_PLUGIN_ID
        try:
            extension_dst.mkdir(parents=True, exist_ok=True)
            for item in source_dir.iterdir():
                destination = extension_dst / item.name
                if item.is_dir():
                    shutil.copytree(item, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, destination)
        except Exception as exc:
            _warning(f"Failed to stage OpenAI OAuth plugin files: {exc}")
            return False

        package_json = extension_dst / "package.json"
        dependency_marker = extension_dst / "node_modules" / "@mariozechner" / "pi-ai" / "package.json"
        if package_json.exists() and not dependency_marker.exists():
            if shutil.which("npm") is None:
                _warning("npm is required to install OpenAI OAuth plugin dependency.")
                return False
            _info("Installing OpenAI OAuth provider dependency...")
            install_errors: list[str] = []
            for attempt in range(1, 4):
                ok_install, install_out = _run_command_in_dir(
                    ["npm", "install", "--no-audit", "--no-fund", "--loglevel", "warn"],
                    cwd=extension_dst,
                    timeout=600,
                )
                if ok_install and dependency_marker.exists():
                    break

                summary = _tail_output(install_out)
                if summary:
                    install_errors.append(f"attempt {attempt}: {summary}")
                else:
                    install_errors.append(f"attempt {attempt}: npm install exited non-zero with no output")

                if attempt < 3:
                    _warning(f"OpenAI OAuth dependency install attempt {attempt} failed; retrying...")
                    time.sleep(attempt * 2)
            else:
                _warning("OpenAI OAuth dependency install failed after 3 attempts.")
                for err in install_errors:
                    _warning(err)
                _info(f"Manual retry: cd {extension_dst} && npm install --no-audit --no-fund --loglevel verbose")
                return False

        config_file = config_dir / "openclaw.json"
        config: dict[str, Any] = {}
        if config_file.exists():
            try:
                loaded = json.loads(config_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config = loaded
            except Exception:
                config = {}

        plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
        entries = plugins.get("entries") if isinstance(plugins.get("entries"), dict) else {}
        plugin_entry = entries.get(OPENAI_OAUTH_PLUGIN_ID) if isinstance(entries.get(OPENAI_OAUTH_PLUGIN_ID), dict) else {}
        plugin_entry["enabled"] = True
        entries[OPENAI_OAUTH_PLUGIN_ID] = plugin_entry
        plugins["entries"] = entries

        allow = plugins.get("allow")
        if isinstance(allow, list):
            normalized_allow = [str(item).strip() for item in allow if str(item).strip()]
            if OPENAI_OAUTH_PLUGIN_ID not in normalized_allow:
                normalized_allow.append(OPENAI_OAUTH_PLUGIN_ID)
            plugins["allow"] = normalized_allow
        else:
            plugins["allow"] = [OPENAI_OAUTH_PLUGIN_ID]
        config["plugins"] = plugins

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
        except Exception as exc:
            _warning(f"Failed to persist OpenClaw plugin config: {exc}")
            return False

        _success("OpenAI OAuth provider plugin ready")
        return True

    def _gemini_required_step(self) -> bool:
        console.print()
        console.print(Panel(
            "Gemini API key is required for ingest + vision tools.",
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Gemini Key (Required)[/]",
            width=72,
        ))

        if self.gemini_key:
            _info("Validating existing Gemini key from OpenClaw config...")
            ok_existing, detail_existing = _validate_gemini_key(self.gemini_key)
            if ok_existing:
                _success("Existing Gemini key verified")
                return True
            _warning(f"Existing Gemini key is invalid ({detail_existing}).")
            self.gemini_key = ""

        while True:
            key = Prompt.ask(
                f"  [{CYAN}]Paste GEMINI_API_KEY[/]",
                console=console,
            ).strip()
            if len(key) < 20:
                _warning("Key looks too short. Please retry.")
                continue

            _info("Validating Gemini key...")
            ok, detail = _validate_gemini_key(key)
            if not ok:
                _warning(f"Gemini key rejected ({detail}).")
                continue

            self.gemini_key = key
            _success("Gemini key verified")
            return True

    def _telegram_required_step(self) -> bool:
        console.print()
        console.print(Panel(
            "Telegram is required in quick setup so Maestro can run as an aware chat agent.\n"
            "Create a bot via @BotFather and paste the bot token.",
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Telegram (Required)[/]",
            width=72,
        ))

        if self.telegram_token:
            _info("Validating existing Telegram token from OpenClaw config...")
            ok_existing, existing_result = _validate_telegram_token(self.telegram_token)
            if ok_existing:
                self.bot_username = existing_result
                _success(f"Existing Telegram bot verified: @{self.bot_username}")
                return True
            _warning(f"Existing Telegram token is invalid ({existing_result}).")
            self.telegram_token = ""

        while True:
            token = Prompt.ask(f"  [{CYAN}]Paste Telegram bot token[/]", console=console).strip()
            _info("Validating Telegram token...")
            ok, result = _validate_telegram_token(token)
            if not ok:
                _warning(f"Telegram token rejected ({result}).")
                continue

            self.telegram_token = token
            self.bot_username = result
            _success(f"Telegram bot verified: @{self.bot_username}")
            return True

    def _tailscale_optional_step(self) -> bool:
        console.print()
        if shutil.which("tailscale") is None:
            _info("Tailscale not installed; field access setup deferred (optional).")
            _info("Later: brew install --cask tailscale && tailscale up")
            if "tailscale" not in self.pending_optional_setup:
                self.pending_optional_setup.append("tailscale")
            return True

        ok, status = _run_command(["tailscale", "status"], timeout=10)
        if not ok or "logged out" in status.lower():
            _warning("Tailscale not connected.")
            _info("Run `tailscale up` later to enable field access URL.")
            if "tailscale" not in self.pending_optional_setup:
                self.pending_optional_setup.append("tailscale")
            return True

        ok_ip, out_ip = _run_command(["tailscale", "ip", "-4"], timeout=10)
        if not ok_ip:
            _warning("Could not resolve Tailscale IPv4. Deferring field access setup.")
            if "tailscale" not in self.pending_optional_setup:
                self.pending_optional_setup.append("tailscale")
            return True

        self.tailscale_ip = str(out_ip.splitlines()[0]).strip()
        if not self.tailscale_ip:
            if "tailscale" not in self.pending_optional_setup:
                self.pending_optional_setup.append("tailscale")
            return True

        _success(f"Tailscale ready: {self.tailscale_ip}")
        if "tailscale" in self.pending_optional_setup:
            self.pending_optional_setup.remove("tailscale")
        return True

    def _gateway_running(self) -> tuple[bool, str]:
        ok, out = self._run_openclaw_command(["status"], timeout=12)
        if not ok:
            return False, out
        lowered = out.lower()
        return ("gateway service" in lowered and "running" in lowered), out

    def _ensure_gateway_running_for_pairing(self) -> bool:
        def _wait_for_running(attempts: int) -> tuple[bool, str]:
            last = ""
            for _ in range(attempts):
                running_now, status_out = self._gateway_running()
                last = status_out
                if running_now:
                    return True, last
                time.sleep(2)
            return False, last

        _info("Starting OpenClaw gateway...")
        start_rc = self._run_openclaw_interactive(["gateway", "--port", str(self.gateway_port), "start"])
        running, last_status = _wait_for_running(4)
        if running:
            _success("OpenClaw gateway is running")
            return True

        if start_rc != 0:
            _warning("Gateway start returned non-zero; installing gateway service.")
        else:
            _warning("Gateway did not become reachable; installing gateway service.")

        install_rc = self._run_openclaw_interactive(
            ["gateway", "--port", str(self.gateway_port), "install", "--force"]
        )
        if install_rc != 0:
            _warning("Gateway install returned non-zero; continuing with restart attempts.")

        restart_rc = self._run_openclaw_interactive(["gateway", "--port", str(self.gateway_port), "restart"])
        if restart_rc != 0:
            _warning("Gateway restart returned non-zero; trying service start once more.")
            _ = self._run_openclaw_interactive(["gateway", "--port", str(self.gateway_port), "start"])

        running, last_status = _wait_for_running(6)
        if running:
            _success("OpenClaw gateway is running")
            return True

        _error("OpenClaw gateway is not running. Telegram pairing cannot continue.")
        if last_status:
            _info(f"openclaw status: {last_status}")
        retry_cmd = " ".join(
            self._openclaw_cmd(["gateway", "--port", str(self.gateway_port), "install", "--force"])
        )
        restart_cmd = " ".join(self._openclaw_cmd(["gateway", "--port", str(self.gateway_port), "restart"]))
        _info(f"Try: {retry_cmd} && {restart_cmd}")
        return False

    def _configure_openclaw_and_workspace_step(self) -> bool:
        console.print()
        console.print(Panel(
            "Writing OpenClaw agent config and workspace scaffolding.",
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Workspace Bootstrap[/]",
            width=72,
        ))
        if not self._ensure_safe_openclaw_write_target():
            return False
        self._refresh_entitlement()
        pro_skill_enabled = has_capability(self.entitlement, "maestro_skill")
        native_extension_enabled = has_capability(self.entitlement, "maestro_native_tools")
        frontend_enabled = has_capability(self.entitlement, "workspace_frontend")

        config_dir = self.openclaw_root
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "openclaw.json"

        config: dict[str, Any] = {}
        if config_file.exists():
            try:
                loaded = json.loads(config_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config = loaded
            except Exception:
                config = {}

        config = transform_openclaw_config(
            config,
            request=SoloConfigTransformRequest(
                workspace=str(self.workspace),
                model=self.model,
                gemini_key=self.gemini_key,
                telegram_token=self.telegram_token,
                native_plugin_enabled=bool(native_extension_enabled),
                native_plugin_id=NATIVE_PLUGIN_ID,
                native_plugin_deny_tools=tuple(NATIVE_PLUGIN_DENY_TOOLS),
                provider_env_key="OPENAI_API_KEY",
                provider_key="",
                provider_auth_method="openclaw_oauth",
                gateway_port=self.gateway_port,
                clear_env_keys=("OPENAI_API_KEY",),
            ),
        )

        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
        _success(f"OpenClaw config written: {config_file}")

        sessions_dir = config_dir / "agents" / "maestro-solo-personal" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _success("Agent session directory ready")

        self.workspace.mkdir(parents=True, exist_ok=True)
        self.store_root.mkdir(parents=True, exist_ok=True)

        self._seed_workspace_files(pro_enabled=pro_skill_enabled)
        if pro_skill_enabled:
            self._seed_workspace_skill()
        else:
            self._remove_path_if_exists(self.workspace / "skills" / "maestro")
            _warning("Core tier active; Maestro skill install skipped.")

        if native_extension_enabled:
            self._seed_native_extension()
        else:
            self._remove_path_if_exists(self.workspace / ".openclaw" / "extensions" / NATIVE_PLUGIN_ID)
            _warning("Core tier active; native extension install skipped.")

        if frontend_enabled:
            self._maybe_build_workspace_frontend()
        else:
            _info("Core tier active; workspace frontend build skipped.")

        return True

    def _refresh_entitlement(self):
        self.entitlement = resolve_effective_entitlement()
        self.tier = normalize_tier(str(self.entitlement.get("tier", "core")))
        _info(f"Capability tier: {entitlement_label(self.entitlement)}")

    @staticmethod
    def _remove_path_if_exists(path: Path):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    def _seed_workspace_files(self, *, pro_enabled: bool):
        module_dir = Path(__file__).resolve().parent
        repo_root = _discover_repo_root()
        candidate_dirs = [
            module_dir / "agent",
            repo_root / "agent",
            repo_root,
            module_dir,
        ]

        for filename in ("SOUL.md", "AGENTS.md", "IDENTITY.md", "USER.md"):
            src = None
            for base in candidate_dirs:
                candidate = base / filename
                if candidate.exists():
                    src = candidate
                    break
            if src:
                shutil.copy2(src, self.workspace / filename)

        (self.workspace / "AGENTS.md").write_text(
            render_personal_agents_md(pro_enabled=pro_enabled),
            encoding="utf-8",
        )
        (self.workspace / "TOOLS.md").write_text(
            render_personal_tools_md(
                active_provider_env_key=self.provider_env_key,
                pro_enabled=pro_enabled,
            ),
            encoding="utf-8",
        )

        env_content = render_workspace_env(
            store_path="knowledge_store/",
            provider_env_key=self.provider_env_key,
            provider_key="",
            gemini_key=self.gemini_key,
            agent_role="project",
            model_auth_method=self.model_auth_method,
            maestro_tier=self.tier,
        )
        (self.workspace / ".env").write_text(env_content, encoding="utf-8")

    def _seed_workspace_skill(self):
        module_dir = Path(__file__).resolve().parent
        repo_root = _discover_repo_root()
        candidate_dirs = [
            module_dir / "agent",
            repo_root / "agent",
            repo_root,
            module_dir,
        ]

        skill_src: Path | None = None
        for base in candidate_dirs:
            candidate = base / "skills" / "maestro" / "SKILL.md"
            if candidate.exists():
                skill_src = candidate
                break

        if skill_src is None:
            _warning("Could not find Maestro SKILL.md; agent will rely on built-in tool descriptions.")
            return

        skill_dir = self.workspace / "skills" / "maestro"
        skill_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_src, skill_dir / "SKILL.md")
        _success("Maestro SKILL.md synced")

    def _seed_native_extension(self):
        extension_src = self._locate_extension_source(NATIVE_PLUGIN_ID)

        if extension_src is None:
            _warning("Could not find Maestro native extension files.")
            return

        extension_dst = self.workspace / ".openclaw" / "extensions" / NATIVE_PLUGIN_ID
        if extension_dst.exists():
            shutil.rmtree(extension_dst)
        extension_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(extension_src, extension_dst)
        _success("Maestro native tools extension installed")

    def _maybe_build_workspace_frontend(self):
        repo_root = _discover_repo_root()
        frontend_dir = repo_root / "workspace_frontend"
        if not (frontend_dir / "package.json").exists():
            return

        dist_dir = frontend_dir / "dist"
        if dist_dir.exists():
            _success("workspace_frontend/dist already present (build skipped)")
            return

        if shutil.which("npm") is None:
            _warning("npm not available; could not build workspace frontend.")
            return

        _info("Building workspace frontend (dist missing)...")
        install_ok, install_out = _run_command(["npm", "install", "--prefix", str(frontend_dir)], timeout=600)
        if not install_ok:
            _warning(f"npm install failed: {install_out}")
            return
        build_ok, build_out = _run_command(["npm", "run", "build", "--prefix", str(frontend_dir)], timeout=600)
        if not build_ok:
            _warning(f"npm run build failed: {build_out}")
            return
        _success("Workspace frontend built")

    def _pair_telegram_required_step(self) -> bool:
        console.print()
        console.print(Panel(
            "Telegram pairing is required in quick setup.\n"
            f"Send /start (or any message) to @{self.bot_username}, then paste the pairing code.",
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Telegram Pairing (Required)[/]",
            width=72,
        ))

        if self.replay_existing:
            _info("Replay mode: preserving existing Telegram pairing setup.")
            _success("Telegram pairing previously completed (replay mode)")
            return True

        if not self._ensure_gateway_running_for_pairing():
            return False

        while True:
            pairing_code = Prompt.ask(
                f"  [{CYAN}]Paste Telegram pairing code[/]",
                console=console,
            ).strip()
            if not pairing_code:
                _warning("Pairing code is required.")
                continue

            ok, out = self._run_openclaw_command(["pairing", "approve", "telegram", pairing_code], timeout=30)
            if ok:
                _success("Telegram pairing approved")
                return True

            _warning(f"Pairing approval failed: {out}")
            pending_ok, pending_out = self._run_openclaw_command(["pairing", "list", "telegram", "--json"], timeout=20)
            if pending_ok:
                try:
                    pending_payload = json.loads(pending_out)
                except Exception:
                    pending_payload = {}
                requests = pending_payload.get("requests") if isinstance(pending_payload, dict) else []
                if isinstance(requests, list) and not requests:
                    _info(f"No pending Telegram pairing requests found. Send /start to @{self.bot_username} and retry.")
            retry = Confirm.ask(
                f"  [{CYAN}]Retry pairing?[/]",
                default=True,
                console=console,
            )
            if not retry:
                return False

    def _trial_license_step(self) -> bool:
        console.print()
        _info("Checking local trial cache (optional fallback for offline demos)...")
        try:
            trial = ensure_local_trial_license(
                purchase_id=f"trial-{self.install_id[:12]}",
                email="trial@maestro.local",
                plan_id="solo_trial",
                source="quick_setup_trial",
            )
        except Exception as exc:
            _warning(f"Trial license check skipped: {exc}")
            return True
        self.trial_info = trial if isinstance(trial, dict) else {}
        status = trial.get("status", {}) if isinstance(trial, dict) else {}
        if not isinstance(status, dict) or not bool(status.get("valid")):
            _warning("Trial license unavailable. Continuing in core mode.")
            return True
        if bool(trial.get("created")):
            _success(f"Trial license active until {status.get('expires_at', '')}")
        else:
            _success("Existing valid local license found")
        return True

    def _doctor_fix_step(self) -> bool:
        console.print()
        _info("Running doctor --fix verification...")
        code = run_doctor(
            fix=True,
            store_override=str(self.store_root),
            restart_gateway=True,
            json_output=False,
            field_access_required=False,
        )
        if code != 0:
            _error("Doctor checks failed. Resolve the warnings/errors above and rerun setup.")
            return False
        _success("Doctor verification complete")
        return True

    def _save_install_state(self):
        save_install_state(
            {
                "version": 1,
                "product": "maestro-solo",
                "install_id": self.install_id,
                "company_name": self.company_name,
                "openclaw_profile": self.openclaw_profile,
                "workspace_root": str(self.workspace),
                "store_root": str(self.store_root),
                "active_project_slug": "",
                "active_project_name": "",
                "setup_mode": "quick",
                "setup_completed": True,
                "pending_optional_setup": list(dict.fromkeys(self.pending_optional_setup)),
                "tier": self.tier,
                "entitlement_source": str(self.entitlement.get("source", "")),
            }
        )

    def _summary(self):
        console.print()
        local_url = "http://localhost:3000/workspace" if self.tier == "pro" else "http://localhost:3000/"
        tailnet_url = (
            f"http://{self.tailscale_ip}:3000/workspace"
            if (self.tailscale_ip and self.tier == "pro")
            else (f"http://{self.tailscale_ip}:3000/" if self.tailscale_ip else "Not configured")
        )

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("Company", self.company_name)
        table.add_row("Tier", self.tier)
        table.add_row("Agent", "maestro-solo-personal")
        table.add_row("OpenClaw Profile", self._openclaw_label())
        table.add_row("Model", self.model)
        table.add_row("Auth", "OpenAI OAuth via OpenClaw")
        table.add_row("Telegram", f"@{self.bot_username}")
        if self.tier == "pro":
            table.add_row("Workspace", str(self.workspace))
        table.add_row("Store", str(self.store_root))
        table.add_row("Local URL", local_url)
        table.add_row("Field URL", tailnet_url)
        if self.pending_optional_setup:
            table.add_row("Deferred", ", ".join(self.pending_optional_setup))

        console.print(Panel(
            table,
            border_style="green",
            title="[bold green]Quick Setup Complete[/]",
            width=84,
        ))

        next_step_body = (
            "Start live runtime now:\n"
            "  [bold white]maestro-solo up --tui[/]\n\n"
            "Then open:\n"
            f"  [bold white]{local_url}[/]"
        )
        if self.tier != "pro":
            next_step_body += (
                "\n\nUpgrade to Pro when ready:\n"
                "  [bold white]maestro-solo purchase --email you@example.com --plan solo_monthly --mode live[/]"
            )

        console.print(Panel(
            next_step_body,
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Next Step[/]",
            width=84,
        ))


def run_quick_setup(*, company_name: str = "", replay: bool = False) -> int:
    runner = QuickSetup(company_name=company_name, replay=replay)
    return runner.run()
