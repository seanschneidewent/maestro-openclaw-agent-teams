"""Compatibility shim; no new logic."""

from __future__ import annotations

from ..._package_imports import ensure_package_src

ensure_package_src("maestro_fleet")

from maestro_fleet.command_center import (  # noqa: F401
    REGISTRY_VERSION,
    clean_registry_text,
    default_registry,
    find_registry_project,
    fleet_registry_path,
    load_fleet_registry,
    normalize_bot_username,
    registries_equal,
    resolve_node_identity,
    save_fleet_registry,
    sync_fleet_registry,
)

