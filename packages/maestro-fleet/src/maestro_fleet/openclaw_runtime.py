"""Fleet-native OpenClaw runtime and environment helpers."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path


DEFAULT_FLEET_OPENCLAW_PROFILE = "maestro-fleet"
_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROFILE_OFF_VALUES = {"default", "none", "off", "shared"}

_DISABLED_MALLOC_ENV_VARS = (
    "MallocStackLogging",
    "MallocStackLoggingNoCompact",
)
_FALSEY_ENV_VALUES = {"", "0", "false", "no", "off"}
_MALLOC_ENV_REEXEC_GUARD = "MAESTRO_MALLOC_ENV_CLEANED"


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


def _has_disabled_malloc_stack_logging(env: dict[str, str]) -> bool:
    return any(
        name in env and str(env.get(name, "")).strip().lower() in _FALSEY_ENV_VALUES
        for name in _DISABLED_MALLOC_ENV_VARS
    )


def resolve_openclaw_profile(*, default_profile: str = DEFAULT_FLEET_OPENCLAW_PROFILE) -> str:
    raw_env = os.environ.get("MAESTRO_OPENCLAW_PROFILE")
    if raw_env is not None:
        from_env = _normalize_profile(raw_env)
        if from_env or str(raw_env).strip().lower() in _PROFILE_OFF_VALUES:
            return from_env
    return _normalize_profile(default_profile)


def ensure_openclaw_profile_env(*, default_profile: str = DEFAULT_FLEET_OPENCLAW_PROFILE) -> str:
    profile = resolve_openclaw_profile(default_profile=default_profile)
    if profile and not str(os.environ.get("MAESTRO_OPENCLAW_PROFILE", "")).strip():
        os.environ["MAESTRO_OPENCLAW_PROFILE"] = profile
    return profile


def openclaw_state_root(
    *,
    home_dir: Path | None = None,
    default_profile: str = DEFAULT_FLEET_OPENCLAW_PROFILE,
    enforce_profile: bool = False,
) -> Path:
    home = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home().resolve()
    profile = resolve_openclaw_profile(default_profile=default_profile)
    if profile:
        return home / f".openclaw-{profile}"
    return home / ".openclaw"


def openclaw_config_path(
    *,
    home_dir: Path | None = None,
    default_profile: str = DEFAULT_FLEET_OPENCLAW_PROFILE,
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
    default_profile: str = DEFAULT_FLEET_OPENCLAW_PROFILE,
    enforce_profile: bool = False,
    workspace_name: str = "workspace-maestro",
) -> Path:
    return openclaw_state_root(
        home_dir=home_dir,
        default_profile=default_profile,
        enforce_profile=enforce_profile,
    ) / workspace_name


def prepend_openclaw_profile_args(
    args: list[str],
    *,
    default_profile: str = DEFAULT_FLEET_OPENCLAW_PROFILE,
) -> list[str]:
    if not args or args[0] != "openclaw" or "--profile" in args:
        return list(args)
    executable = _resolve_openclaw_executable(args[0])
    profile = resolve_openclaw_profile(default_profile=default_profile)
    if not profile:
        return [executable, *args[1:]]
    return [executable, "--profile", profile, *args[1:]]


def sanitized_subprocess_env(*, clear_profile_env: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    if clear_profile_env:
        env.pop("MAESTRO_OPENCLAW_PROFILE", None)
    if sys.platform == "darwin":
        for name in _DISABLED_MALLOC_ENV_VARS:
            value = str(env.get(name, "")).strip().lower()
            if value in _FALSEY_ENV_VALUES:
                env.pop(name, None)
    return env


def maybe_reexec_without_disabled_malloc_stack_logging(*, module: str) -> None:
    if sys.platform != "darwin":
        return
    if str(os.environ.get(_MALLOC_ENV_REEXEC_GUARD, "")).strip() == "1":
        return
    if not _has_disabled_malloc_stack_logging(os.environ):
        return
    env = sanitized_subprocess_env()
    env[_MALLOC_ENV_REEXEC_GUARD] = "1"
    os.execve(
        sys.executable,
        [sys.executable, "-m", str(module).strip(), *sys.argv[1:]],
        env,
    )


__all__ = [
    "DEFAULT_FLEET_OPENCLAW_PROFILE",
    "ensure_openclaw_profile_env",
    "maybe_reexec_without_disabled_malloc_stack_logging",
    "openclaw_config_path",
    "openclaw_state_root",
    "openclaw_workspace_root",
    "prepend_openclaw_profile_args",
    "resolve_openclaw_profile",
    "sanitized_subprocess_env",
]
