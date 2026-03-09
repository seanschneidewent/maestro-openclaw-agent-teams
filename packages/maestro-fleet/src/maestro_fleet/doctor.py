"""Fleet-native doctor entrypoint wrappers."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from .command_center import build_derived_registry
from .openclaw_runtime import (
    DEFAULT_FLEET_OPENCLAW_PROFILE,
    openclaw_config_path,
    openclaw_state_root,
    prepend_openclaw_profile_args,
)


def _load_legacy_doctor() -> Any:
    try:
        import maestro.doctor as legacy_doctor
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "maestro-fleet doctor currently depends on legacy runtime modules in `maestro/`.\n"
            "Install root package too: pip install -e /absolute/path/to/repo"
        ) from exc
    return legacy_doctor


@contextmanager
def _fleet_doctor_overrides(home_dir: Path | None = None) -> Iterator[Any]:
    legacy_doctor = _load_legacy_doctor()

    def _derived_registry(store_root: Path, dry_run: bool = False) -> dict[str, Any]:
        _ = dry_run
        return build_derived_registry(Path(store_root).resolve(), home_dir=home_dir)

    with ExitStack() as stack:
        stack.enter_context(patch.object(legacy_doctor, "sync_fleet_registry", _derived_registry))
        stack.enter_context(patch.object(legacy_doctor, "openclaw_config_path", openclaw_config_path))
        stack.enter_context(patch.object(legacy_doctor, "openclaw_state_root", openclaw_state_root))
        stack.enter_context(patch.object(legacy_doctor, "prepend_openclaw_profile_args", prepend_openclaw_profile_args))
        stack.enter_context(
            patch.object(legacy_doctor, "DEFAULT_FLEET_OPENCLAW_PROFILE", DEFAULT_FLEET_OPENCLAW_PROFILE)
        )
        yield legacy_doctor


def build_doctor_report(
    fix: bool = False,
    store_override: str | None = None,
    restart_gateway: bool = True,
    runtime_checks: bool = True,
    field_access_required: bool | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    with _fleet_doctor_overrides(home_dir=home_dir) as legacy_doctor:
        return legacy_doctor.build_doctor_report(
            fix=fix,
            store_override=store_override,
            restart_gateway=restart_gateway,
            runtime_checks=runtime_checks,
            field_access_required=field_access_required,
            home_dir=home_dir,
        )


def run_doctor(
    fix: bool = False,
    store_override: str | None = None,
    restart_gateway: bool = True,
    runtime_checks: bool = True,
    json_output: bool = False,
    field_access_required: bool | None = None,
    home_dir: Path | None = None,
) -> int:
    with _fleet_doctor_overrides(home_dir=home_dir) as legacy_doctor:
        return legacy_doctor.run_doctor(
            fix=fix,
            store_override=store_override,
            restart_gateway=restart_gateway,
            runtime_checks=runtime_checks,
            json_output=json_output,
            field_access_required=field_access_required,
            home_dir=home_dir,
        )


__all__ = ["build_doctor_report", "run_doctor"]
