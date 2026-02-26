"""Shared OpenClaw profile/path helpers for Maestro Solo."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


DEFAULT_MAESTRO_OPENCLAW_PROFILE = "maestro-solo"
_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROFILE_OFF_VALUES = {"default", "none", "off", "shared"}
_TRUTHY = {"1", "true", "yes", "on"}


def shared_openclaw_allowed() -> bool:
    raw = str(os.environ.get("MAESTRO_ALLOW_SHARED_OPENCLAW", "")).strip().lower()
    return raw in _TRUTHY


def shared_openclaw_write_allowed() -> bool:
    raw = str(os.environ.get("MAESTRO_ALLOW_SHARED_OPENCLAW_WRITE", "")).strip().lower()
    return raw in _TRUTHY


def _normalize_profile(raw: str) -> str:
    clean = str(raw or "").strip()
    if not clean:
        return ""
    lowered = clean.lower()
    if lowered in _PROFILE_OFF_VALUES:
        return ""
    if not _PROFILE_PATTERN.fullmatch(clean):
        return ""
    return clean


def _read_install_state_profile() -> str:
    raw_home = str(os.environ.get("MAESTRO_SOLO_HOME", "")).strip()
    solo_home = Path(raw_home).expanduser().resolve() if raw_home else (Path.home() / ".maestro-solo").resolve()
    install_path = solo_home / "install.json"
    if not install_path.exists():
        return ""
    try:
        payload = json.loads(install_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return _normalize_profile(str(payload.get("openclaw_profile", "")).strip())


def resolve_openclaw_profile(*, default: str = DEFAULT_MAESTRO_OPENCLAW_PROFILE) -> str:
    raw_env = os.environ.get("MAESTRO_OPENCLAW_PROFILE")
    if raw_env is not None:
        env_clean = str(raw_env).strip()
        from_env = _normalize_profile(env_clean)
        if from_env:
            return from_env
        if (not env_clean or env_clean.lower() in _PROFILE_OFF_VALUES) and shared_openclaw_allowed():
            return ""

    from_state = _read_install_state_profile()
    if from_state:
        return from_state

    normalized_default = _normalize_profile(default)
    if normalized_default:
        return normalized_default
    if shared_openclaw_allowed():
        return ""
    return DEFAULT_MAESTRO_OPENCLAW_PROFILE


def openclaw_state_root(*, home_dir: Path | None = None, profile: str | None = None) -> Path:
    home = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home().resolve()
    resolved = resolve_openclaw_profile() if profile is None else _normalize_profile(profile)
    if resolved:
        return home / f".openclaw-{resolved}"
    if not shared_openclaw_allowed():
        return home / f".openclaw-{DEFAULT_MAESTRO_OPENCLAW_PROFILE}"
    return home / ".openclaw"


def openclaw_config_path(*, home_dir: Path | None = None, profile: str | None = None) -> Path:
    return openclaw_state_root(home_dir=home_dir, profile=profile) / "openclaw.json"


def is_shared_openclaw_root(path: Path, *, home_dir: Path | None = None) -> bool:
    home = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home().resolve()
    shared_root = (home / ".openclaw").resolve()
    return Path(path).expanduser().resolve() == shared_root


def ensure_safe_openclaw_write_target(
    path: Path,
    *,
    home_dir: Path | None = None,
    allow_shared_write: bool | None = None,
) -> tuple[bool, str]:
    target = Path(path).expanduser().resolve()
    if not is_shared_openclaw_root(target, home_dir=home_dir):
        return True, ""
    allowed = shared_openclaw_write_allowed() if allow_shared_write is None else bool(allow_shared_write)
    if allowed:
        return True, ""
    return False, (
        "Refusing to write to shared ~/.openclaw without explicit override. "
        "Set MAESTRO_ALLOW_SHARED_OPENCLAW_WRITE=1 only for controlled migrations."
    )


def prepend_openclaw_profile_args(args: list[str], *, profile: str | None = None) -> list[str]:
    if not args:
        return list(args)
    if args[0] != "openclaw":
        return list(args)
    if "--profile" in args:
        return list(args)
    resolved = resolve_openclaw_profile() if profile is None else _normalize_profile(profile)
    if not resolved and not shared_openclaw_allowed():
        resolved = DEFAULT_MAESTRO_OPENCLAW_PROFILE
    if not resolved:
        return list(args)
    return [args[0], "--profile", resolved, *args[1:]]
