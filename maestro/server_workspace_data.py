"""Compatibility shim; no new logic."""

from ._package_imports import ensure_package_src

ensure_package_src("maestro_engine")

from maestro_engine.server_workspace_data import *  # noqa: F401,F403
