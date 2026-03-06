"""Doctor read-side checks and workspace sync helpers."""

from __future__ import annotations

import json
import plistlib
import platform
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    fixed: bool = False
    warning: bool = False


def sync_launchagent_env(
    home_dir: Path,
    config_env: dict[str, Any],
    profile: str,
    fix: bool,
    *,
    launchagent_path: Callable[[Path], Path],
    provider_env_keys: tuple[str, ...],
    is_placeholder: Callable[[str | None], bool],
) -> DoctorCheck:
    plist_path = launchagent_path(home_dir)
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
    for key in provider_env_keys:
        raw = config_env.get(key)
        value = str(raw).strip() if isinstance(raw, str) else ""
        if value and not is_placeholder(value):
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


def sync_workspace_tools_md(
    workspace_root: Path | None,
    company_name: str,
    active_provider_env_key: str | None,
    profile: str,
    fix: bool,
    *,
    fleet_profile: str,
    render_tools_md: Callable[..., str],
    render_personal_tools_md: Callable[..., str],
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
        render_tools_md(company_name=company_name, active_provider_env_key=active_provider_env_key)
        if profile == fleet_profile
        else render_personal_tools_md(active_provider_env_key=active_provider_env_key)
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


def sync_workspace_agents_md(
    workspace_root: Path | None,
    profile: str,
    fix: bool,
    *,
    fleet_profile: str,
    render_company_agents_md: Callable[[], str],
    render_personal_agents_md: Callable[[], str],
) -> DoctorCheck:
    if not workspace_root:
        return DoctorCheck(
            name="workspace_agents_md",
            ok=False,
            detail="Company workspace not configured",
            warning=True,
        )

    agents_path = workspace_root / "AGENTS.md"
    desired = render_company_agents_md() if profile == fleet_profile else render_personal_agents_md()
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


def sync_workspace_env_role(
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


def read_workspace_env_value(
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


def tail_text(path: Path, max_bytes: int = 180_000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="ignore")


def rotate_stale_sessions(
    home_dir: Path,
    fix: bool,
    *,
    profile: str,
    fleet_profile: str,
    default_openclaw_profile: str,
    openclaw_state_root: Callable[..., Path],
    load_json: Callable[..., Any],
    save_json: Callable[[Path, Any], None],
    tail_text_func: Callable[[Path], str] = tail_text,
) -> DoctorCheck:
    default_profile = default_openclaw_profile if profile == fleet_profile else ""
    sessions_dir = openclaw_state_root(home_dir=home_dir, default_profile=default_profile) / "agents" / "maestro-company" / "sessions"
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
            tail = tail_text_func(session_file)
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


def gateway_running(
    *,
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
) -> bool:
    ok, out = run_cmd(["openclaw", "gateway", "status", "--json"], 10)
    if ok:
        raw = str(out or "")
        idx = raw.find("{")
        if idx >= 0:
            try:
                payload = json.loads(raw[idx:])
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                service = payload.get("service", {}) if isinstance(payload.get("service"), dict) else {}
                runtime = service.get("runtime", {}) if isinstance(payload.get("runtime"), dict) else {}
                status = str(runtime.get("status", "")).strip().lower()
                if status in {"running", "started", "active"}:
                    return True
    status_ok, status_out = run_cmd(["openclaw", "status"], 10)
    if not status_ok:
        return False
    lowered = str(status_out or "").lower()
    return "gateway service" in lowered and "running" in lowered
