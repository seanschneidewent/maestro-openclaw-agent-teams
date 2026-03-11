"""Compatibility shim; no new logic."""

from __future__ import annotations

import os
import sys

from ..._package_imports import ensure_package_src

ensure_package_src("maestro_fleet")

import maestro_fleet.openclaw_runtime as _openclaw_runtime
from maestro_fleet.subprocesses import parse_json_from_output, run_cmd_raw, run_profiled_cmd  # noqa: F401


def sanitized_subprocess_env(*, clear_profile_env: bool = False) -> dict[str, str]:
    original_os = _openclaw_runtime.os
    original_sys = _openclaw_runtime.sys
    try:
        _openclaw_runtime.os = os
        _openclaw_runtime.sys = sys
        return _openclaw_runtime.sanitized_subprocess_env(clear_profile_env=clear_profile_env)
    finally:
        _openclaw_runtime.os = original_os
        _openclaw_runtime.sys = original_sys


def maybe_reexec_without_disabled_malloc_stack_logging(*, module: str) -> None:
    original_os = _openclaw_runtime.os
    original_sys = _openclaw_runtime.sys
    try:
        _openclaw_runtime.os = os
        _openclaw_runtime.sys = sys
        _openclaw_runtime.maybe_reexec_without_disabled_malloc_stack_logging(module=module)
    finally:
        _openclaw_runtime.os = original_os
        _openclaw_runtime.sys = original_sys
