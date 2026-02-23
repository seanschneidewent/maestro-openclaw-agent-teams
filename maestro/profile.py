"""Runtime profile helpers (Solo vs Fleet)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .install_state import (
    PROFILE_FLEET,
    PROFILE_SOLO,
    load_install_state,
    normalize_install_state,
    save_install_state,
)
from .utils import load_json


def normalize_profile(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if cleaned in (PROFILE_SOLO, PROFILE_FLEET):
        return cleaned
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def _load_openclaw_config(home_dir: Path | None = None) -> dict[str, Any]:
    home = (home_dir or Path.home()).resolve()
    path = home / ".openclaw" / "openclaw.json"
    payload = load_json(path, default={})
    return payload if isinstance(payload, dict) else {}


def infer_profile_from_openclaw_config(config: dict[str, Any]) -> str:
    if not isinstance(config, dict):
        return PROFILE_SOLO

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []

    agent_ids = {
        str(agent.get("id", "")).strip()
        for agent in agent_list
        if isinstance(agent, dict) and str(agent.get("id", "")).strip()
    }

    if "maestro-company" in agent_ids:
        return PROFILE_FLEET
    if any(agent_id.startswith("maestro-project-") for agent_id in agent_ids):
        return PROFILE_FLEET
    # Backward-compat: legacy single-agent installs used `maestro` as the
    # commander identity and should retain Fleet semantics on update.
    if "maestro" in agent_ids:
        return PROFILE_FLEET
    if "maestro-personal" in agent_ids:
        return PROFILE_SOLO

    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
    accounts = telegram.get("accounts") if isinstance(telegram.get("accounts"), dict) else {}
    if any(str(key).strip().startswith("maestro-project-") for key in accounts.keys()):
        return PROFILE_FLEET
    if "maestro-company" in accounts:
        return PROFILE_FLEET

    return PROFILE_SOLO


def resolve_profile(
    *,
    home_dir: Path | None = None,
    install_state: dict[str, Any] | None = None,
    openclaw_config: dict[str, Any] | None = None,
) -> str:
    state = install_state if isinstance(install_state, dict) else load_install_state(home_dir=home_dir)
    explicit = normalize_profile(state.get("profile"))
    fleet_flag = _coerce_bool(state.get("fleet_enabled"))

    if explicit:
        if fleet_flag is True and explicit != PROFILE_FLEET:
            return PROFILE_FLEET
        return explicit

    if fleet_flag is True:
        return PROFILE_FLEET
    if fleet_flag is False:
        return PROFILE_SOLO

    config = openclaw_config if isinstance(openclaw_config, dict) else _load_openclaw_config(home_dir=home_dir)
    return infer_profile_from_openclaw_config(config)


def fleet_enabled(
    *,
    home_dir: Path | None = None,
    install_state: dict[str, Any] | None = None,
    openclaw_config: dict[str, Any] | None = None,
) -> bool:
    state = install_state if isinstance(install_state, dict) else load_install_state(home_dir=home_dir)
    fleet_flag = _coerce_bool(state.get("fleet_enabled"))
    if fleet_flag is not None:
        return fleet_flag
    return resolve_profile(
        home_dir=home_dir,
        install_state=state,
        openclaw_config=openclaw_config,
    ) == PROFILE_FLEET


def get_profile_state(home_dir: Path | None = None) -> dict[str, Any]:
    state = normalize_install_state(load_install_state(home_dir=home_dir))
    profile = resolve_profile(home_dir=home_dir, install_state=state)
    enabled = fleet_enabled(home_dir=home_dir, install_state=state)
    state["profile"] = profile
    state["fleet_enabled"] = enabled
    return state


def set_profile(
    profile: str,
    *,
    home_dir: Path | None = None,
    fleet: bool | None = None,
    workspace_root: str | None = None,
    store_root: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    if not normalized:
        raise ValueError(f"Unsupported profile '{profile}'")

    state = get_profile_state(home_dir=home_dir)
    state["profile"] = normalized
    state["fleet_enabled"] = (normalized == PROFILE_FLEET) if fleet is None else bool(fleet)
    if isinstance(workspace_root, str) and workspace_root.strip():
        state["workspace_root"] = workspace_root.strip()
    if isinstance(store_root, str) and store_root.strip():
        state["store_root"] = store_root.strip()
        state["fleet_store_root"] = state["store_root"]

    save_install_state(state, home_dir=home_dir)
    return get_profile_state(home_dir=home_dir)
