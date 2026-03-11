"""Compatibility shim; no new logic."""

from ._package_imports import ensure_package_src

ensure_package_src("maestro_fleet")

from maestro_fleet.constants import *  # noqa: F401,F403
