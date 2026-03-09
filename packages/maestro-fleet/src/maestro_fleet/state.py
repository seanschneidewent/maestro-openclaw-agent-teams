"""Fleet-native state resolution helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .openclaw_runtime import (
    DEFAULT_FLEET_OPENCLAW_PROFILE,
    openclaw_config_path,
)


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return payload


def install_state_path(home_dir: Path | None = None) -> Path:
    home = (home_dir or Path.home()).resolve()
    return home / ".maestro" / "install.json"


def load_install_state(home_dir: Path | None = None) -> dict[str, Any]:
    path = install_state_path(home_dir)
    payload = _load_json(path, default={})
    return payload if isinstance(payload, dict) else {}


def load_openclaw_config(home_dir: Path | None = None) -> dict[str, Any]:
    config_path = openclaw_config_path(
        home_dir=home_dir,
        default_profile=DEFAULT_FLEET_OPENCLAW_PROFILE,
        enforce_profile=True,
    )
    payload = _load_json(config_path, default={})
    return payload if isinstance(payload, dict) else {}


def openclaw_agents(config: dict[str, Any] | None = None, *, home_dir: Path | None = None) -> list[dict[str, Any]]:
    payload = config if isinstance(config, dict) else load_openclaw_config(home_dir=home_dir)
    agents = payload.get("agents") if isinstance(payload.get("agents"), dict) else {}
    agent_list = agents.get("list") if isinstance(agents, dict) and isinstance(agents.get("list"), list) else []
    return [item for item in agent_list if isinstance(item, dict)]


def resolve_commander_agent(home_dir: Path | None = None) -> tuple[str, str]:
    agents = openclaw_agents(home_dir=home_dir)

    selected: dict[str, Any] | None = None
    for item in agents:
        if str(item.get("id", "")).strip() == "maestro-company":
            selected = item
            break
    if selected is None:
        for item in agents:
            if bool(item.get("default")):
                selected = item
                break
    if selected is None and agents:
        selected = agents[0]
    if selected is None:
        return "maestro-company", ""
    return (
        str(selected.get("id", "")).strip() or "maestro-company",
        str(selected.get("workspace", "")).strip(),
    )


def resolve_company_workspace(home_dir: Path | None = None) -> Path | None:
    _agent_id, workspace = resolve_commander_agent(home_dir=home_dir)
    if not workspace:
        return None
    return Path(workspace).expanduser().resolve()


def load_workspace_env(workspace: Path | None) -> dict[str, str]:
    if workspace is None:
        return {}
    env_path = workspace / ".env"
    if not env_path.exists():
        return {}
    payload: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def resolve_workspace_store(workspace: Path | None) -> Path | None:
    env = load_workspace_env(workspace)
    raw = str(env.get("MAESTRO_STORE", "")).strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if workspace is not None and not path.is_absolute():
        path = (workspace / path).resolve()
    return path.resolve()


def _read_workspace_store(workspace: Path | None) -> Path | None:
    try:
        return resolve_workspace_store(workspace)
    except Exception:
        return None


def resolve_workspace_role(workspace: Path | None) -> str:
    env = load_workspace_env(workspace)
    return str(env.get("MAESTRO_AGENT_ROLE", "")).strip().lower()


def resolve_workspace_project_slug(workspace: Path | None) -> str:
    env = load_workspace_env(workspace)
    return str(env.get("MAESTRO_PROJECT_SLUG", "")).strip()


def resolve_fleet_store_root(
    store_override: str | Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    if store_override:
        return Path(store_override).expanduser().resolve()

    state = load_install_state(home_dir=home_dir)
    state_root = state.get("store_root") or state.get("fleet_store_root")
    if isinstance(state_root, str) and state_root.strip():
        return Path(state_root).expanduser().resolve()

    workspace = resolve_company_workspace(home_dir=home_dir)
    workspace_store = _read_workspace_store(workspace)
    if workspace_store:
        return workspace_store

    env_store = os.environ.get("MAESTRO_STORE", "").strip()
    if env_store:
        return Path(env_store).expanduser().resolve()

    if workspace:
        return (workspace / "knowledge_store").resolve()
    return Path("knowledge_store").resolve()


__all__ = [
    "install_state_path",
    "load_install_state",
    "load_openclaw_config",
    "load_workspace_env",
    "openclaw_agents",
    "resolve_commander_agent",
    "resolve_company_workspace",
    "resolve_fleet_store_root",
    "resolve_workspace_project_slug",
    "resolve_workspace_role",
    "resolve_workspace_store",
]
