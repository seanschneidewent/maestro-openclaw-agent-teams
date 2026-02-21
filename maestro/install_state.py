"""Install-state helpers for canonical Maestro runtime resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .utils import load_json, save_json


def install_state_path(home_dir: Path | None = None) -> Path:
    home = (home_dir or Path.home()).resolve()
    return home / ".maestro" / "install.json"


def load_install_state(home_dir: Path | None = None) -> dict[str, Any]:
    path = install_state_path(home_dir)
    payload = load_json(path, default={})
    return payload if isinstance(payload, dict) else {}


def save_install_state(state: dict[str, Any], home_dir: Path | None = None):
    path = install_state_path(home_dir)
    save_json(path, state)


def resolve_company_workspace(home_dir: Path | None = None) -> Path | None:
    home = (home_dir or Path.home()).resolve()
    config_path = home / ".openclaw" / "openclaw.json"
    config = load_json(config_path, default={})
    if not isinstance(config, dict):
        return None

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    company = next(
        (item for item in agent_list if isinstance(item, dict) and item.get("id") == "maestro-company"),
        None,
    )
    if not isinstance(company, dict):
        company = next(
            (item for item in agent_list if isinstance(item, dict) and item.get("default")),
            None,
        )
    if not isinstance(company, dict):
        return None

    raw_workspace = str(company.get("workspace", "")).strip()
    if not raw_workspace:
        return None
    return Path(raw_workspace).expanduser().resolve()


def _read_workspace_store(workspace: Path | None) -> Path | None:
    if workspace is None:
        return None
    env_path = workspace / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        if key.strip() != "MAESTRO_STORE":
            continue
        raw = value.strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (workspace / path).resolve()
        return path.resolve()
    return None


def resolve_fleet_store_root(
    store_override: str | Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Resolve canonical fleet store root for runtime and control-plane flows."""
    if store_override:
        return Path(store_override).expanduser().resolve()

    state = load_install_state(home_dir=home_dir)
    state_root = state.get("fleet_store_root")
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

