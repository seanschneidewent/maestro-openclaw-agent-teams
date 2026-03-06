"""Shared subprocess helpers for Fleet runtime modules."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Callable


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
    env = os.environ.copy()
    if clear_profile_env:
        env.pop("MAESTRO_OPENCLAW_PROFILE", None)
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

