"""OpenClaw profile/path helpers for Maestro runtime modules."""

from __future__ import annotations

import os
import re
import shlex
import shutil
from pathlib import Path


DEFAULT_FLEET_OPENCLAW_PROFILE = "maestro-fleet"
_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROFILE_OFF_VALUES = {"default", "none", "off", "shared"}


def _resolve_openclaw_executable(executable: str) -> str:
    candidate = str(executable or "").strip()
    if candidate != "openclaw":
        return candidate
    if os.name != "nt":
        return candidate
    if shutil.which("openclaw.cmd"):
        return "openclaw.cmd"
    if shutil.which("openclaw.exe"):
        return "openclaw.exe"
    return candidate


def _normalize_profile(raw: str | None) -> str:
    clean = str(raw or "").strip()
    if not clean:
        return ""
    lowered = clean.lower()
    if lowered in _PROFILE_OFF_VALUES:
        return ""
    if not _PROFILE_PATTERN.fullmatch(clean):
        return ""
    return clean


def resolve_openclaw_profile(*, default_profile: str = "") -> str:
    raw_env = os.environ.get("MAESTRO_OPENCLAW_PROFILE")
    if raw_env is not None:
        from_env = _normalize_profile(raw_env)
        if from_env or str(raw_env).strip().lower() in _PROFILE_OFF_VALUES:
            return from_env
    return _normalize_profile(default_profile)


def ensure_openclaw_profile_env(*, default_profile: str) -> str:
    profile = resolve_openclaw_profile(default_profile=default_profile)
    if profile and not str(os.environ.get("MAESTRO_OPENCLAW_PROFILE", "")).strip():
        os.environ["MAESTRO_OPENCLAW_PROFILE"] = profile
    return profile


def openclaw_state_root(
    *,
    home_dir: Path | None = None,
    default_profile: str = "",
    enforce_profile: bool = False,
) -> Path:
    home = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home().resolve()
    profile = resolve_openclaw_profile(default_profile=default_profile)
    if profile:
        profiled = home / f".openclaw-{profile}"
        if enforce_profile:
            return profiled
        shared = home / ".openclaw"
        if profiled.exists() or not shared.exists():
            return profiled
        return shared
    return home / ".openclaw"


def openclaw_config_path(
    *,
    home_dir: Path | None = None,
    default_profile: str = "",
    enforce_profile: bool = False,
) -> Path:
    return openclaw_state_root(
        home_dir=home_dir,
        default_profile=default_profile,
        enforce_profile=enforce_profile,
    ) / "openclaw.json"


def openclaw_workspace_root(
    *,
    home_dir: Path | None = None,
    default_profile: str = "",
    enforce_profile: bool = False,
    workspace_name: str = "workspace-maestro",
) -> Path:
    return openclaw_state_root(
        home_dir=home_dir,
        default_profile=default_profile,
        enforce_profile=enforce_profile,
    ) / workspace_name


def prepend_openclaw_profile_args(args: list[str], *, default_profile: str = "") -> list[str]:
    if not args or args[0] != "openclaw" or "--profile" in args:
        return list(args)
    executable = _resolve_openclaw_executable(args[0])
    profile = resolve_openclaw_profile(default_profile=default_profile)
    if not profile:
        return [executable, *args[1:]]
    return [executable, "--profile", profile, *args[1:]]


def prepend_openclaw_profile_shell(cmd: str, *, default_profile: str = "") -> str:
    text = str(cmd or "").strip()
    if not text.startswith("openclaw "):
        return text
    profile = resolve_openclaw_profile(default_profile=default_profile)
    if not profile or "--profile" in text:
        return text
    return f"openclaw --profile {shlex.quote(profile)} {text[len('openclaw '):]}"
