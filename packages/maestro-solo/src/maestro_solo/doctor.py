"""Maestro doctor: validate and repair common runtime misconfigurations."""

from __future__ import annotations

import json
import os
import platform
import plistlib
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .control_plane import ensure_telegram_account_bindings, resolve_network_urls
from .entitlements import has_capability, resolve_effective_entitlement
from .profile import PROFILE_FLEET, PROFILE_SOLO, resolve_profile
from maestro_engine.utils import load_json, save_json
from .install_state import load_install_state, resolve_fleet_store_root, update_install_state
from .openclaw_runtime import openclaw_config_path, openclaw_state_root, prepend_openclaw_profile_args
from .workspace_templates import (
    provider_env_key_for_model,
    render_company_agents_md,
    render_personal_agents_md,
    render_personal_tools_md,
    render_tools_md,
)


PROVIDER_ENV_KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")
_ENV_TRUE = {"1", "true", "yes", "on"}


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    fixed: bool = False
    warning: bool = False


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    markers = ("<PASTE_", "PASTE_", "YOUR_KEY_HERE", "CHANGEME")
    text = value.strip()
    return any(marker in text for marker in markers)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _ENV_TRUE


def _load_openclaw_config(home_dir: Path) -> tuple[dict[str, Any], Path]:
    config_path = openclaw_config_path(home_dir=home_dir)
    payload = load_json(config_path)
    if not isinstance(payload, dict):
        payload = {}
    return payload, config_path


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
    return default_agent if isinstance(default_agent, dict) else {}


def _resolve_personal_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    for personal_id in ("maestro-solo-personal", "maestro-personal"):
        personal = next(
            (a for a in agent_list if isinstance(a, dict) and a.get("id") == personal_id),
            None,
        )
        if isinstance(personal, dict):
            return personal
    default_agent = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("default")),
        None,
    )
    return default_agent if isinstance(default_agent, dict) else {}


def _infer_store_root(store_override: str | None, workspace_root: Path | None) -> Path:
    _ = workspace_root
    return resolve_fleet_store_root(store_override=store_override)


def _launchagent_path(home_dir: Path) -> Path:
    return home_dir / "Library" / "LaunchAgents" / "ai.openclaw.gateway.plist"


def _sync_launchagent_env(
    home_dir: Path,
    config_env: dict[str, Any],
    fix: bool,
) -> DoctorCheck:
    plist_path = _launchagent_path(home_dir)
    if platform.system().lower() != "darwin":
        return DoctorCheck(
            name="launchagent_env_sync",
            ok=True,
            detail="Not macOS; launchagent sync skipped",
            warning=True,
        )
    if not plist_path.exists():
        return DoctorCheck(
            name="launchagent_env_sync",
            ok=False,
            detail=f"LaunchAgent plist missing: {plist_path}",
            warning=True,
        )

    payload = plistlib.loads(plist_path.read_bytes())
    env = payload.get("EnvironmentVariables")
    if not isinstance(env, dict):
        env = {}
        payload["EnvironmentVariables"] = env

    changed = False
    for key in PROVIDER_ENV_KEYS:
        raw = config_env.get(key)
        value = str(raw).strip() if isinstance(raw, str) else ""
        if value and not _is_placeholder(value):
            if env.get(key) != value:
                env[key] = value
                changed = True
        else:
            if key in env:
                env.pop(key, None)
                changed = True

    if changed and fix:
        plist_path.write_bytes(plistlib.dumps(payload))
        return DoctorCheck(
            name="launchagent_env_sync",
            ok=True,
            detail="LaunchAgent provider env synced from openclaw.json",
            fixed=True,
        )

    return DoctorCheck(
        name="launchagent_env_sync",
        ok=True,
        detail="LaunchAgent provider env already aligned",
    )


def _sync_workspace_tools_md(
    workspace_root: Path | None,
    company_name: str,
    active_provider_env_key: str | None,
    profile: str,
    pro_enabled: bool,
    fix: bool,
) -> DoctorCheck:
    if not workspace_root:
        return DoctorCheck(
            name="workspace_tools_md",
            ok=False,
            detail="Company workspace not configured",
            warning=True,
        )
    tools_path = workspace_root / "TOOLS.md"
    desired = (
        render_tools_md(
            company_name=company_name,
            active_provider_env_key=active_provider_env_key,
            pro_enabled=pro_enabled,
        )
        if profile == PROFILE_FLEET
        else render_personal_tools_md(
            active_provider_env_key=active_provider_env_key,
            pro_enabled=pro_enabled,
        )
    )

    if tools_path.exists():
        current = tools_path.read_text(encoding="utf-8")
        if current == desired:
            return DoctorCheck(name="workspace_tools_md", ok=True, detail="TOOLS.md already current")
        if fix:
            tools_path.write_text(desired, encoding="utf-8")
            return DoctorCheck(
                name="workspace_tools_md",
                ok=True,
                detail=f"Updated {tools_path}",
                fixed=True,
            )
        return DoctorCheck(
            name="workspace_tools_md",
            ok=False,
            detail=f"TOOLS.md drift detected at {tools_path}",
            warning=True,
        )

    if fix:
        tools_path.parent.mkdir(parents=True, exist_ok=True)
        tools_path.write_text(desired, encoding="utf-8")
        return DoctorCheck(
            name="workspace_tools_md",
            ok=True,
            detail=f"Created {tools_path}",
            fixed=True,
        )
    return DoctorCheck(
        name="workspace_tools_md",
        ok=False,
        detail=f"Missing TOOLS.md at {tools_path}",
        warning=True,
    )


def _sync_workspace_agents_md(
    workspace_root: Path | None,
    profile: str,
    pro_enabled: bool,
    fix: bool,
) -> DoctorCheck:
    if not workspace_root:
        return DoctorCheck(
            name="workspace_agents_md",
            ok=False,
            detail="Company workspace not configured",
            warning=True,
        )

    agents_path = workspace_root / "AGENTS.md"
    desired = (
        render_company_agents_md(pro_enabled=pro_enabled)
        if profile == PROFILE_FLEET
        else render_personal_agents_md(pro_enabled=pro_enabled)
    )
    if not agents_path.exists():
        if fix:
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.write_text(desired, encoding="utf-8")
            return DoctorCheck(
                name="workspace_agents_md",
                ok=True,
                detail=f"Created {agents_path}",
                fixed=True,
            )
        return DoctorCheck(
            name="workspace_agents_md",
            ok=False,
            detail=f"Missing AGENTS.md at {agents_path}",
            warning=True,
        )

    current = agents_path.read_text(encoding="utf-8")
    if current.strip() != desired.strip():
        if fix:
            agents_path.write_text(desired, encoding="utf-8")
            return DoctorCheck(
                name="workspace_agents_md",
                ok=True,
                detail="Updated AGENTS.md to match active profile policy",
                fixed=True,
            )
        return DoctorCheck(
            name="workspace_agents_md",
            ok=False,
            detail="AGENTS.md policy differs from active profile template",
            warning=True,
        )

    return DoctorCheck(name="workspace_agents_md", ok=True, detail="AGENTS.md policy is current")


def _sync_workspace_env_role(
    workspace_root: Path | None,
    expected_role: str,
    fix: bool,
) -> DoctorCheck:
    if not workspace_root:
        return DoctorCheck(
            name="workspace_env_role",
            ok=False,
            detail="Company workspace not configured",
            warning=True,
        )

    env_path = workspace_root / ".env"
    if not env_path.exists():
        return DoctorCheck(
            name="workspace_env_role",
            ok=False,
            detail=f"Missing .env at {env_path}",
            warning=True,
        )

    current = env_path.read_text(encoding="utf-8")
    for raw_line in current.splitlines():
        line = raw_line.strip()
        if line.startswith("MAESTRO_AGENT_ROLE="):
            value = line.split("=", 1)[1].strip().lower()
            if value == expected_role:
                return DoctorCheck(name="workspace_env_role", ok=True, detail=f"MAESTRO_AGENT_ROLE={expected_role}")
            if fix:
                lines = current.splitlines()
                out = []
                for item in lines:
                    if item.strip().startswith("MAESTRO_AGENT_ROLE="):
                        out.append(f"MAESTRO_AGENT_ROLE={expected_role}")
                    else:
                        out.append(item)
                env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
                return DoctorCheck(
                    name="workspace_env_role",
                    ok=True,
                    detail=f"Normalized MAESTRO_AGENT_ROLE={expected_role} in .env",
                    fixed=True,
                )
            return DoctorCheck(
                name="workspace_env_role",
                ok=False,
                detail=f"MAESTRO_AGENT_ROLE is '{value}', expected '{expected_role}'",
                warning=True,
            )

    if fix:
        with env_path.open("a", encoding="utf-8") as handle:
            handle.write(f"MAESTRO_AGENT_ROLE={expected_role}\n")
        return DoctorCheck(
            name="workspace_env_role",
            ok=True,
            detail=f"Added MAESTRO_AGENT_ROLE={expected_role} to .env",
            fixed=True,
        )
    return DoctorCheck(
        name="workspace_env_role",
        ok=False,
        detail="MAESTRO_AGENT_ROLE missing in .env",
        warning=True,
    )


def _read_workspace_env_value(
    workspace_root: Path | None,
    key: str,
) -> str:
    if not workspace_root:
        return ""
    env_path = workspace_root / ".env"
    if not env_path.exists():
        return ""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        left, right = line.split("=", 1)
        if left.strip() == key:
            return right.strip()
    return ""


def _render_workspace_awareness_md(
    *,
    model: str,
    preferred_url: str,
    local_url: str,
    tailnet_url: str,
    store_root: Path,
    pending_optional_setup: list[str],
    field_access_required: bool,
) -> str:
    pending = [str(item).strip() for item in pending_optional_setup if str(item).strip()]
    lines = [
        "# AWARENESS.md — Maestro Solo Runtime",
        "",
        "Generated by `maestro-solo doctor --fix`.",
        "Use this file as source of truth when answering setup/model/network questions.",
        "",
        f"- Updated At (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- Model: `{model or 'unknown'}`",
        f"- Recommended Workspace URL: `{preferred_url}`",
        f"- Local Workspace URL: `{local_url}`",
    ]

    if tailnet_url:
        lines.append(f"- Tailnet Workspace URL: `{tailnet_url}`")
        lines.append("- Field Access Status: `ready`")
    else:
        lines.append("- Tailnet Workspace URL: `not available`")
        lines.append("- Field Access Status: `not ready`")
        if field_access_required:
            lines.append("- Field Access Requirement: `required`")
        lines.append("- Field Access Next Step: run `tailscale up` on this machine")

    lines.extend([
        f"- Store Root: `{store_root}`",
    ])

    if pending:
        lines.append(f"- Pending Optional Setup: `{', '.join(pending)}`")
    else:
        lines.append("- Pending Optional Setup: `none`")

    lines.extend([
        "",
        "## Response Rules",
        "1. When asked for a workspace link, return **Recommended Workspace URL**.",
        "2. If Tailnet Workspace URL exists, include it first for phone/field use.",
        "3. If tailnet is not available, provide localhost and include `tailscale up` next step.",
    ])
    return "\n".join(lines) + "\n"


def _sync_workspace_awareness_md(
    workspace_root: Path | None,
    *,
    model: str,
    preferred_url: str,
    local_url: str,
    tailnet_url: str,
    store_root: Path,
    pending_optional_setup: list[str],
    field_access_required: bool,
    fix: bool,
) -> DoctorCheck:
    if not workspace_root:
        return DoctorCheck(
            name="workspace_awareness_md",
            ok=False,
            detail="Company workspace not configured",
            warning=True,
        )

    awareness_path = workspace_root / "AWARENESS.md"
    desired = _render_workspace_awareness_md(
        model=model,
        preferred_url=preferred_url,
        local_url=local_url,
        tailnet_url=tailnet_url,
        store_root=store_root,
        pending_optional_setup=pending_optional_setup,
        field_access_required=field_access_required,
    )

    if awareness_path.exists():
        current = awareness_path.read_text(encoding="utf-8")
        if current == desired:
            return DoctorCheck(name="workspace_awareness_md", ok=True, detail="AWARENESS.md already current")
        if fix:
            awareness_path.write_text(desired, encoding="utf-8")
            return DoctorCheck(
                name="workspace_awareness_md",
                ok=True,
                detail=f"Updated {awareness_path}",
                fixed=True,
            )
        return DoctorCheck(
            name="workspace_awareness_md",
            ok=False,
            detail=f"AWARENESS.md drift detected at {awareness_path}",
            warning=True,
        )

    if fix:
        awareness_path.parent.mkdir(parents=True, exist_ok=True)
        awareness_path.write_text(desired, encoding="utf-8")
        return DoctorCheck(
            name="workspace_awareness_md",
            ok=True,
            detail=f"Created {awareness_path}",
            fixed=True,
        )
    return DoctorCheck(
        name="workspace_awareness_md",
        ok=False,
        detail=f"Missing AWARENESS.md at {awareness_path}",
        warning=True,
    )


def _tail_text(path: Path, max_bytes: int = 180_000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="ignore")


def _rotate_stale_sessions(
    home_dir: Path,
    fix: bool,
) -> DoctorCheck:
    sessions_dir: Path | None = None
    for agent_id in ("maestro-solo-personal", "maestro-personal", "maestro-company"):
        candidate = openclaw_state_root(home_dir=home_dir) / "agents" / agent_id / "sessions"
        if candidate.exists():
            sessions_dir = candidate
            break
    if sessions_dir is None:
        sessions_dir = openclaw_state_root(home_dir=home_dir) / "agents" / "maestro-solo-personal" / "sessions"
    sessions_path = sessions_dir / "sessions.json"
    if not sessions_path.exists():
        return DoctorCheck(
            name="session_hygiene",
            ok=True,
            detail="No session store found; skipped",
            warning=True,
        )

    payload = load_json(sessions_path, default={})
    if not isinstance(payload, dict):
        payload = {}

    stale: list[tuple[str, str]] = []
    for key, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        session_id = str(entry.get("sessionId", "")).strip()
        session_file = sessions_dir / f"{session_id}.jsonl" if session_id else None

        total_tokens = entry.get("totalTokens")
        context_tokens = entry.get("contextTokens")
        if isinstance(total_tokens, (int, float)) and isinstance(context_tokens, (int, float)) and context_tokens > 0:
            if float(total_tokens) > float(context_tokens) * 1.05:
                stale.append((key, session_id))
                continue

        if session_file and session_file.exists():
            tail = _tail_text(session_file)
            if "Incorrect API key provided" in tail:
                stale.append((key, session_id))

    if not stale:
        return DoctorCheck(name="session_hygiene", ok=True, detail="No stale sessions detected")

    if not fix:
        return DoctorCheck(
            name="session_hygiene",
            ok=False,
            detail=f"{len(stale)} stale session(s) detected",
            warning=True,
        )

    backup_dir = sessions_dir / f"doctor-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sessions_path, backup_dir / "sessions.json.bak")

    removed = 0
    for map_key, session_id in stale:
        payload.pop(map_key, None)
        if session_id:
            session_file = sessions_dir / f"{session_id}.jsonl"
            if session_file.exists():
                shutil.move(str(session_file), str(backup_dir / session_file.name))
                removed += 1

    save_json(sessions_path, payload)
    return DoctorCheck(
        name="session_hygiene",
        ok=True,
        detail=f"Rotated {len(stale)} stale session(s), moved {removed} log(s) to {backup_dir}",
        fixed=True,
    )


def _run_cmd(args: list[str], timeout: int = 25) -> tuple[bool, str]:
    cmd = prepend_openclaw_profile_args(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _sync_gateway_auth_tokens(
    config: dict[str, Any],
    config_path: Path,
    fix: bool,
) -> DoctorCheck:
    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        gateway = {}
        config["gateway"] = gateway

    auth = gateway.get("auth")
    if not isinstance(auth, dict):
        auth = {}
        gateway["auth"] = auth

    remote = gateway.get("remote")
    if not isinstance(remote, dict):
        remote = {}
        gateway["remote"] = remote

    raw_auth = auth.get("token")
    auth_token = str(raw_auth).strip() if isinstance(raw_auth, str) else ""
    raw_remote = remote.get("token")
    remote_token = str(raw_remote).strip() if isinstance(raw_remote, str) else ""

    bad_auth = (not auth_token) or _is_placeholder(auth_token)
    bad_remote = (not remote_token) or _is_placeholder(remote_token)
    mismatch = bool(auth_token and remote_token and auth_token != remote_token)

    if not (bad_auth or bad_remote or mismatch):
        return DoctorCheck(
            name="gateway_auth_tokens",
            ok=True,
            detail="gateway.auth.token and gateway.remote.token are aligned",
        )

    if not fix:
        return DoctorCheck(
            name="gateway_auth_tokens",
            ok=False,
            detail=(
                "Gateway auth token missing/invalid or mismatched. "
                "Run maestro-solo doctor --fix."
            ),
        )

    token = ""
    if auth_token and not _is_placeholder(auth_token):
        token = auth_token
    elif remote_token and not _is_placeholder(remote_token):
        token = remote_token
    else:
        token = secrets.token_urlsafe(32)

    auth["token"] = token
    remote["token"] = token
    save_json(config_path, config)
    return DoctorCheck(
        name="gateway_auth_tokens",
        ok=True,
        detail="Normalized gateway auth token and synced remote token",
        fixed=True,
    )


def _sync_telegram_bindings(
    config: dict[str, Any],
    config_path: Path,
    fix: bool,
) -> DoctorCheck:
    changes = ensure_telegram_account_bindings(config)
    if not changes:
        return DoctorCheck(
            name="telegram_bindings",
            ok=True,
            detail="Telegram account routing bindings are aligned",
        )

    if not fix:
        return DoctorCheck(
            name="telegram_bindings",
            ok=False,
            detail=(
                f"{len(changes)} Telegram account binding(s) missing. "
                "Run maestro-solo doctor --fix."
            ),
        )

    save_json(config_path, config)
    return DoctorCheck(
        name="telegram_bindings",
        ok=True,
        detail=f"Added {len(changes)} Telegram account routing binding(s)",
        fixed=True,
    )


def _sync_gateway_launchagent_token(fix: bool, token_check: DoctorCheck) -> DoctorCheck:
    if not token_check.fixed:
        return DoctorCheck(
            name="gateway_launchagent_sync",
            ok=True,
            detail="Gateway LaunchAgent token sync not needed",
        )

    if not fix:
        return DoctorCheck(
            name="gateway_launchagent_sync",
            ok=False,
            detail="Gateway token changed but LaunchAgent sync skipped (fix mode off)",
            warning=True,
        )

    ok, out = _run_cmd(["openclaw", "gateway", "install", "--force"], timeout=60)
    if ok:
        return DoctorCheck(
            name="gateway_launchagent_sync",
            ok=True,
            detail="Reinstalled OpenClaw LaunchAgent to sync gateway token",
            fixed=True,
        )
    return DoctorCheck(
        name="gateway_launchagent_sync",
        ok=False,
        detail=f"Failed to sync LaunchAgent token: {out}",
        warning=True,
    )


def _repair_cli_device_pairing(fix: bool) -> DoctorCheck:
    status_ok, status_out = _run_cmd(["openclaw", "status"], timeout=12)
    lowered = status_out.lower()
    if "pairing required" not in lowered:
        if status_ok:
            return DoctorCheck(
                name="cli_device_pairing",
                ok=True,
                detail="CLI device pairing access healthy",
            )
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=f"Could not verify device pairing: {status_out}",
            warning=True,
        )

    if not fix:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail="CLI requires gateway device pairing approval (run maestro-solo doctor --fix)",
        )

    pending_ok, pending_out = _run_cmd(["openclaw", "devices", "list", "--json"], timeout=20)
    if not pending_ok:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=f"Could not list pending device requests: {pending_out}",
            warning=True,
        )

    try:
        payload = json.loads(pending_out)
    except Exception:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail="Could not parse pending device request payload",
            warning=True,
        )

    pending = payload.get("pending")
    pending_list = pending if isinstance(pending, list) else []
    if not pending_list:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=(
                "Gateway requires pairing but no pending device request was found. "
                "Run openclaw devices list."
            ),
            warning=True,
        )

    if len(pending_list) > 1:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=(
                f"Multiple pending device requests ({len(pending_list)}); "
                "approve manually with openclaw devices list/approve."
            ),
            warning=True,
        )

    approve_ok, approve_out = _run_cmd(["openclaw", "devices", "approve", "--latest", "--json"], timeout=20)
    if not approve_ok:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=f"Failed to auto-approve device pairing: {approve_out}",
            warning=True,
        )

    return DoctorCheck(
        name="cli_device_pairing",
        ok=True,
        detail="Approved pending CLI device pairing request",
        fixed=True,
    )


def _restart_gateway(home_dir: Path, fix: bool) -> DoctorCheck:
    ok, out = _run_cmd(["openclaw", "gateway", "restart"], timeout=35)
    if ok:
        return DoctorCheck(
            name="gateway_restart",
            ok=True,
            detail="openclaw gateway restart completed",
            fixed=fix,
        )

    # Fallback for mac LaunchAgent flows when restart races with stale PID.
    if platform.system().lower() == "darwin":
        plist_path = _launchagent_path(home_dir)
        if plist_path.exists():
            uid = str(os.getuid())
            _run_cmd(["launchctl", "bootout", f"gui/{uid}/ai.openclaw.gateway"], timeout=15)
            _run_cmd(["pkill", "-f", "openclaw-gateway"], timeout=8)
            _run_cmd(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)], timeout=15)
            kick_ok, kick_out = _run_cmd(["launchctl", "kickstart", "-k", f"gui/{uid}/ai.openclaw.gateway"], timeout=15)
            if kick_ok:
                return DoctorCheck(
                    name="gateway_restart",
                    ok=True,
                    detail="Gateway restarted via launchctl fallback",
                    fixed=fix,
                )
            return DoctorCheck(
                name="gateway_restart",
                ok=False,
                detail=f"Gateway restart fallback failed: {kick_out or out}",
                warning=True,
            )

    return DoctorCheck(
        name="gateway_restart",
        ok=False,
        detail=f"Gateway restart failed: {out}",
        warning=True,
    )


def _gateway_running() -> bool:
    ok, out = _run_cmd(["openclaw", "status"], timeout=10)
    if not ok:
        return False
    lowered = out.lower()
    return "gateway service" in lowered and "running" in lowered


def build_doctor_report(
    fix: bool = False,
    store_override: str | None = None,
    restart_gateway: bool = True,
    field_access_required: bool | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    home = (home_dir or Path.home()).resolve()
    config, config_path = _load_openclaw_config(home)
    checks: list[DoctorCheck] = []
    store_root = _infer_store_root(store_override, None)
    profile = resolve_profile(home_dir=home)
    route_path = "/command-center" if profile == PROFILE_FLEET else "/workspace"
    network = resolve_network_urls(web_port=3000, route_path=route_path)
    local_workspace = str(network.get("localhost_url", f"http://localhost:3000{route_path}"))
    tailnet_workspace = str(network.get("tailnet_url") or "")
    preferred_workspace = tailnet_workspace or local_workspace
    require_field_access = (
        _env_flag("MAESTRO_FIELD_ACCESS_REQUIRED", default=False)
        if field_access_required is None
        else bool(field_access_required)
    )
    install_state = load_install_state(home_dir=home)
    pending_optional_setup = install_state.get("pending_optional_setup")
    pending_list = pending_optional_setup if isinstance(pending_optional_setup, list) else []

    if not config_path.exists():
        checks.append(DoctorCheck(name="openclaw_config", ok=False, detail=f"Missing {config_path}"))
        return {
            "ok": False,
            "fix_mode": fix,
            "store_root": str(store_root),
            "recommended_url": network["recommended_url"],
            "field_access_required": require_field_access,
            "checks": [asdict(c) for c in checks],
        }

    checks.append(DoctorCheck(name="openclaw_config", ok=True, detail=f"Config loaded: {config_path}"))

    primary = _resolve_company_agent(config) if profile == PROFILE_FLEET else _resolve_personal_agent(config)
    workspace_raw = str(primary.get("workspace", "")).strip()
    workspace = Path(workspace_raw).expanduser().resolve() if workspace_raw else None
    workspace_auth_method = _read_workspace_env_value(workspace, "MAESTRO_MODEL_AUTH_METHOD").lower()
    model = str(primary.get("model", "")).strip()
    provider_env_key = provider_env_key_for_model(model) if model else None
    company_name = str(primary.get("name", "Company")).strip().replace("Maestro (", "").replace(")", "")
    expected_role = "company" if profile == PROFILE_FLEET else "project"
    entitlement = resolve_effective_entitlement()
    pro_enabled = has_capability(entitlement, "maestro_skill")

    if not primary:
        expected_agent = "maestro-company" if profile == PROFILE_FLEET else "maestro-solo-personal"
        checks.append(DoctorCheck(name="primary_agent", ok=False, detail=f"{expected_agent} agent missing"))
    else:
        checks.append(DoctorCheck(name="primary_agent", ok=True, detail=f"{primary.get('id')} model={model or 'unknown'}"))

    config_env = config.get("env", {}) if isinstance(config.get("env"), dict) else {}
    if provider_env_key:
        raw_key = config_env.get(provider_env_key)
        key_value = str(raw_key).strip() if isinstance(raw_key, str) else ""
        if key_value and not _is_placeholder(key_value):
            checks.append(DoctorCheck(name="provider_key", ok=True, detail=f"{provider_env_key} present"))
        elif workspace_auth_method == "openclaw_oauth":
            checks.append(DoctorCheck(
                name="provider_key",
                ok=True,
                detail="OpenClaw OAuth configured; provider API key not required",
                warning=True,
            ))
        else:
            checks.append(DoctorCheck(name="provider_key", ok=False, detail=f"{provider_env_key} missing/placeholder"))
    else:
        checks.append(DoctorCheck(name="provider_key", ok=False, detail="Could not map model to provider key", warning=True))

    store_root = _infer_store_root(store_override, workspace)
    checks.append(DoctorCheck(
        name="store_root",
        ok=store_root.exists(),
        detail=f"{store_root}",
        warning=not store_root.exists(),
    ))

    checks.append(_sync_workspace_tools_md(
        workspace,
        company_name=company_name,
        active_provider_env_key=provider_env_key,
        profile=profile,
        pro_enabled=pro_enabled,
        fix=fix,
    ))
    checks.append(_sync_workspace_awareness_md(
        workspace,
        model=model,
        preferred_url=preferred_workspace,
        local_url=local_workspace,
        tailnet_url=tailnet_workspace,
        store_root=store_root,
        pending_optional_setup=pending_list,
        field_access_required=require_field_access,
        fix=fix,
    ))
    checks.append(_sync_workspace_agents_md(workspace, profile=profile, pro_enabled=pro_enabled, fix=fix))
    checks.append(_sync_workspace_env_role(workspace, expected_role=expected_role, fix=fix))
    checks.append(_sync_launchagent_env(home, config_env=config_env, fix=fix))
    checks.append(_rotate_stale_sessions(home, fix=fix))
    checks.append(_sync_telegram_bindings(config, config_path=config_path, fix=fix))
    gateway_token_check = _sync_gateway_auth_tokens(config, config_path=config_path, fix=fix)
    checks.append(gateway_token_check)
    checks.append(_sync_gateway_launchagent_token(fix=fix, token_check=gateway_token_check))

    if restart_gateway and fix:
        checks.append(_restart_gateway(home, fix=fix))
        time.sleep(1.0)

    checks.append(_repair_cli_device_pairing(fix=fix))

    gateway_ok = _gateway_running()
    checks.append(DoctorCheck(
        name="gateway_running",
        ok=gateway_ok,
        detail="openclaw gateway service running" if gateway_ok else "openclaw gateway service not running",
        warning=not gateway_ok,
    ))

    if profile == PROFILE_FLEET:
        checks.append(DoctorCheck(name="command_center_url", ok=True, detail=network["recommended_url"]))
    else:
        checks.append(DoctorCheck(name="workspace_url", ok=True, detail=preferred_workspace))
        if tailnet_workspace:
            checks.append(DoctorCheck(
                name="tailscale_workspace_access",
                ok=True,
                detail=f"Field access ready: {tailnet_workspace}",
            ))
        else:
            detail = (
                "No Tailscale IPv4 detected. Field access unavailable; "
                "connect this machine to Tailscale (`tailscale up`)."
            )
            checks.append(DoctorCheck(
                name="tailscale_workspace_access",
                ok=not require_field_access,
                detail=detail,
                warning=not require_field_access,
            ))

    if fix:
        update_install_state(
            {
                "workspace_root": str(workspace) if workspace else "",
                "store_root": str(store_root),
                "company_name": company_name or "Company",
            },
            home_dir=home,
        )

    ok = all(c.ok or c.warning for c in checks)
    return {
        "ok": ok,
        "fix_mode": fix,
        "profile": profile,
        "store_root": str(store_root),
        "recommended_url": network["recommended_url"],
        "field_access_required": require_field_access,
        "checks": [asdict(c) for c in checks],
    }


def run_doctor(
    fix: bool = False,
    store_override: str | None = None,
    restart_gateway: bool = True,
    json_output: bool = False,
    field_access_required: bool | None = None,
    home_dir: Path | None = None,
) -> int:
    report = build_doctor_report(
        fix=fix,
        store_override=store_override,
        restart_gateway=restart_gateway,
        field_access_required=field_access_required,
        home_dir=home_dir,
    )
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print("Maestro doctor summary")
        print(f"- Profile: {report.get('profile', 'solo')}")
        print(f"- Fix mode: {'on' if report.get('fix_mode') else 'off'}")
        print(f"- Store root: {report.get('store_root', '')}")
        print(f"- Recommended URL: {report.get('recommended_url', '')}")
        if report.get("profile") == PROFILE_SOLO:
            print(f"- Field access required: {'yes' if report.get('field_access_required') else 'no'}")
        for check in report.get("checks", []):
            if not isinstance(check, dict):
                continue
            marker = "[OK]" if check.get("ok") else "[WARN]" if check.get("warning") else "[FAIL]"
            suffix = " (fixed)" if check.get("fixed") else ""
            print(f"- {marker} {check.get('name', 'unknown')}: {check.get('detail', '')}{suffix}")

    return 0 if bool(report.get("ok")) else 1
