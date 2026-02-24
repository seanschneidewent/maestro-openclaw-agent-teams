"""Solo profile helpers."""

from __future__ import annotations

from typing import Any


PROFILE_SOLO = "solo"
PROFILE_FLEET = "fleet"


def resolve_profile(*, home_dir=None, install_state: dict[str, Any] | None = None, openclaw_config: dict[str, Any] | None = None) -> str:
    _ = home_dir
    _ = install_state
    _ = openclaw_config
    return PROFILE_SOLO


def fleet_enabled(*, home_dir=None, install_state: dict[str, Any] | None = None, openclaw_config: dict[str, Any] | None = None) -> bool:
    _ = home_dir
    _ = install_state
    _ = openclaw_config
    return False
