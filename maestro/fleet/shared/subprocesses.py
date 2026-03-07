"""Shared subprocess helpers for Fleet runtime modules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Callable


_DISABLED_MALLOC_ENV_VARS = (
    "MallocStackLogging",
    "MallocStackLoggingNoCompact",
)
_FALSEY_ENV_VALUES = {"", "0", "false", "no", "off"}
_MALLOC_ENV_REEXEC_GUARD = "MAESTRO_MALLOC_ENV_CLEANED"


def _has_disabled_malloc_stack_logging(env: dict[str, str]) -> bool:
    return any(
        name in env and str(env.get(name, "")).strip().lower() in _FALSEY_ENV_VALUES
        for name in _DISABLED_MALLOC_ENV_VARS
    )


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


def run_profiled_cmd(
    args: list[str],
    *,
    timeout: int,
    prepend_profile_args: Callable[[list[str]], list[str]],
) -> tuple[bool, str]:
    profiled_args = prepend_profile_args(args)
    try:
        result = subprocess.run(
            profiled_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=sanitized_subprocess_env(),
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def run_cmd_raw(
    args: list[str],
    *,
    timeout: int,
    clear_profile_env: bool = False,
) -> tuple[bool, str]:
    env = sanitized_subprocess_env(clear_profile_env=clear_profile_env)
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def parse_json_from_output(text: str) -> dict[str, Any]:
    raw = str(text or "")
    idx = raw.find("{")
    if idx < 0:
        return {}
    snippet = raw[idx:].strip()
    try:
        payload = json.loads(snippet)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
