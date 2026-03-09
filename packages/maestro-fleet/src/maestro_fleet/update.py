"""Fleet-native update entrypoints."""

from __future__ import annotations

import shlex
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from .openclaw_runtime import (
    DEFAULT_FLEET_OPENCLAW_PROFILE,
    openclaw_config_path,
    openclaw_state_root,
    openclaw_workspace_root,
    prepend_openclaw_profile_args,
)


def _load_legacy_update() -> Any:
    try:
        import maestro.update as legacy_update
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "maestro-fleet update currently depends on legacy runtime modules in `maestro/`.\n"
            "Install root package too: pip install -e /absolute/path/to/repo"
        ) from exc
    return legacy_update


def _prepend_openclaw_profile_shell(cmd: str) -> str:
    text = str(cmd or "").strip()
    if not text.startswith("openclaw "):
        return text
    parts = shlex.split(text)
    profiled = prepend_openclaw_profile_args(parts)
    return " ".join(shlex.quote(part) for part in profiled)


@contextmanager
def _fleet_update_overrides() -> Iterator[Any]:
    legacy_update = _load_legacy_update()
    with ExitStack() as stack:
        stack.enter_context(patch.object(legacy_update, "openclaw_config_path", openclaw_config_path))
        stack.enter_context(patch.object(legacy_update, "openclaw_state_root", openclaw_state_root))
        stack.enter_context(patch.object(legacy_update, "openclaw_workspace_root", openclaw_workspace_root))
        stack.enter_context(patch.object(legacy_update, "prepend_openclaw_profile_shell", _prepend_openclaw_profile_shell))
        stack.enter_context(
            patch.object(legacy_update, "DEFAULT_FLEET_OPENCLAW_PROFILE", DEFAULT_FLEET_OPENCLAW_PROFILE, create=True)
        )
        yield legacy_update


def run_update(
    *,
    workspace_override: str | None = None,
    restart_gateway: bool = True,
    dry_run: bool = False,
) -> int:
    with _fleet_update_overrides() as legacy_update:
        return legacy_update.run_update(
            workspace_override=workspace_override,
            restart_gateway=restart_gateway,
            dry_run=dry_run,
        )


__all__ = ["run_update"]
