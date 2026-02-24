"""Install-state helpers for Maestro Solo."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maestro_engine.utils import load_json, save_json


INSTALL_STATE_VERSION = 1
PRODUCT_ID = "maestro-solo"
DEFAULT_WORKSPACE_DIR = "workspace-maestro-solo"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def solo_home(home_dir: Path | None = None) -> Path:
    if home_dir is not None:
        return Path(home_dir).expanduser().resolve()
    override = str(os.environ.get("MAESTRO_SOLO_HOME", "")).strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".maestro-solo").resolve()


def install_state_path(home_dir: Path | None = None) -> Path:
    return solo_home(home_dir=home_dir) / "install.json"


def normalize_install_state(state: dict[str, Any] | None) -> dict[str, Any]:
    payload = state if isinstance(state, dict) else {}
    out: dict[str, Any] = {
        "version": int(payload.get("version", INSTALL_STATE_VERSION)),
        "product": PRODUCT_ID,
        "workspace_root": str(payload.get("workspace_root", "")).strip(),
        "store_root": str(payload.get("store_root", "")).strip(),
        "active_project_slug": str(payload.get("active_project_slug", "")).strip(),
        "active_project_name": str(payload.get("active_project_name", "")).strip(),
        "updated_at": str(payload.get("updated_at", "")).strip() or _now_iso(),
    }
    legacy_store = str(payload.get("fleet_store_root", "")).strip()
    if not out["store_root"] and legacy_store:
        out["store_root"] = legacy_store
    for key in ("install_id", "company_name"):
        raw = str(payload.get(key, "")).strip()
        if raw:
            out[key] = raw
    return out


def load_install_state(home_dir: Path | None = None) -> dict[str, Any]:
    payload = load_json(install_state_path(home_dir=home_dir), default={})
    return normalize_install_state(payload if isinstance(payload, dict) else {})


def save_install_state(state: dict[str, Any], home_dir: Path | None = None) -> dict[str, Any]:
    normalized = normalize_install_state(state)
    normalized["updated_at"] = _now_iso()
    save_json(install_state_path(home_dir=home_dir), normalized)
    return normalized


def update_install_state(updates: dict[str, Any], home_dir: Path | None = None) -> dict[str, Any]:
    current = load_install_state(home_dir=home_dir)
    merged = dict(current)
    merged.update(updates or {})
    return save_install_state(merged, home_dir=home_dir)


def record_active_project(
    *,
    project_slug: str,
    project_name: str,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    return update_install_state(
        {
            "active_project_slug": str(project_slug).strip(),
            "active_project_name": str(project_name).strip(),
        },
        home_dir=home_dir,
    )


def resolve_personal_workspace(home_dir: Path | None = None) -> Path | None:
    home = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home().resolve()
    config_path = home / ".openclaw" / "openclaw.json"
    config = load_json(config_path, default={})
    if not isinstance(config, dict):
        return None

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []

    preferred_ids = ("maestro-solo-personal", "maestro-personal")
    for agent_id in preferred_ids:
        selected = next(
            (item for item in agent_list if isinstance(item, dict) and str(item.get("id", "")).strip() == agent_id),
            None,
        )
        if isinstance(selected, dict):
            workspace = str(selected.get("workspace", "")).strip()
            if workspace:
                return Path(workspace).expanduser().resolve()

    default_agent = next(
        (item for item in agent_list if isinstance(item, dict) and bool(item.get("default"))),
        None,
    )
    if isinstance(default_agent, dict):
        workspace = str(default_agent.get("workspace", "")).strip()
        if workspace:
            return Path(workspace).expanduser().resolve()

    return (home / ".openclaw" / DEFAULT_WORKSPACE_DIR).resolve()


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


def resolve_solo_store_root(
    store_override: str | Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    if store_override:
        return Path(store_override).expanduser().resolve()

    state = load_install_state(home_dir=home_dir)
    state_root = str(state.get("store_root", "")).strip()
    if state_root:
        return Path(state_root).expanduser().resolve()

    workspace = resolve_personal_workspace(home_dir=home_dir)
    workspace_store = _read_workspace_store(workspace)
    if workspace_store:
        return workspace_store

    env_store = str(os.environ.get("MAESTRO_STORE", "")).strip()
    if env_store:
        return Path(env_store).expanduser().resolve()

    if workspace:
        return (workspace / "knowledge_store").resolve()

    return Path("knowledge_store").resolve()


def resolve_fleet_store_root(
    store_override: str | Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Compatibility alias used by legacy helper modules."""
    return resolve_solo_store_root(store_override=store_override, home_dir=home_dir)
