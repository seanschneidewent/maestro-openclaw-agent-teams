"""Safety helpers to avoid unintentionally taking over non-Maestro OpenClaw setups."""

from __future__ import annotations

import os
from typing import Any


_TRUTHY = {"1", "true", "yes", "on"}
_MANAGED_PREFIX = "maestro-project-"
_MANAGED_IDS = {"maestro", "maestro-company", "maestro-personal"}


def _truthy_env(name: str) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    return raw in _TRUTHY


def _default_agent_id(config: dict[str, Any]) -> str:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []

    default = next(
        (
            item for item in agent_list
            if isinstance(item, dict) and bool(item.get("default")) and str(item.get("id", "")).strip()
        ),
        None,
    )
    if isinstance(default, dict):
        return str(default.get("id", "")).strip()

    first = next(
        (
            item for item in agent_list
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ),
        None,
    )
    if isinstance(first, dict):
        return str(first.get("id", "")).strip()
    return ""


def _is_maestro_managed_agent(agent_id: str) -> bool:
    clean = str(agent_id or "").strip()
    if not clean:
        return True
    return clean in _MANAGED_IDS or clean.startswith(_MANAGED_PREFIX)


def ensure_openclaw_override_allowed(
    config: dict[str, Any],
    *,
    allow_override: bool = False,
    env_var: str = "MAESTRO_ALLOW_OPENCLAW_OVERRIDE",
) -> tuple[bool, str]:
    """Fail closed when default OpenClaw agent appears externally managed.

    This protects Fleet flows from silently taking over a machine that appears to
    be managed by another OpenClaw profile/application.
    """
    default_agent_id = _default_agent_id(config)
    if _is_maestro_managed_agent(default_agent_id):
        return True, ""
    if allow_override or _truthy_env(env_var):
        return True, ""
    return (
        False,
        (
            f"OpenClaw default agent '{default_agent_id}' does not look Maestro-managed. "
            f"Refusing to override automatically. Re-run with --allow-openclaw-override or set {env_var}=1."
        ),
    )
