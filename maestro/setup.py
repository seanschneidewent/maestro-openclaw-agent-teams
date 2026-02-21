#!/usr/bin/env python3
"""Compatibility facade for setup wizard entrypoint.

Canonical implementation lives in `maestro.setup_wizard`.
"""

from __future__ import annotations

from . import setup_wizard as _setup


for _name in dir(_setup):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_setup, _name)


__all__ = [name for name in dir(_setup) if not name.startswith("__")]


if __name__ == "__main__":
    main()
