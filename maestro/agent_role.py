"""Agent role helpers.

Centralizes runtime role detection used to enforce control-plane/data-plane
boundaries between Company Maestro and Project Maestro agents.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


ROLE_COMPANY = "company"
ROLE_PROJECT = "project"
_ROLE_KEY = "MAESTRO_AGENT_ROLE"


def normalize_agent_role(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if cleaned in (ROLE_COMPANY, ROLE_PROJECT):
        return cleaned
    return None


def _read_env_value(path: Path, key: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    needle = f"{key}="
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(needle):
            return line.split("=", 1)[1].strip()
    return None


def resolve_agent_role(
    workspace_root: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = environ if environ is not None else os.environ

    direct = normalize_agent_role(env.get(_ROLE_KEY))
    if direct:
        return direct

    candidates: list[Path] = []
    if workspace_root:
        candidates.append(Path(workspace_root).expanduser().resolve() / ".env")

    workspace_env = env.get("MAESTRO_WORKSPACE")
    if workspace_env:
        candidates.append(Path(workspace_env).expanduser().resolve() / ".env")

    candidates.append(Path(".env").resolve())

    seen: set[Path] = set()
    for env_file in candidates:
        if env_file in seen:
            continue
        seen.add(env_file)
        value = _read_env_value(env_file, _ROLE_KEY)
        role = normalize_agent_role(value)
        if role:
            return role
    return None


def is_company_role(
    workspace_root: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    return resolve_agent_role(workspace_root=workspace_root, environ=environ) == ROLE_COMPANY

