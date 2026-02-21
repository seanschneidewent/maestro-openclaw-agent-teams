"""Compatibility facade for control-plane APIs.

Canonical implementation lives in `maestro.control_plane_core`.
This wrapper preserves all existing imports, including private helper names
used by tests and monkeypatching.
"""

from __future__ import annotations

from . import control_plane_core as _core


for _name in dir(_core):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_core, _name)


__all__ = [name for name in dir(_core) if not name.startswith("__")]
