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


def main():
    print("[deprecated] `maestro-setup` is an alias. Use `maestro setup`.")
    return _setup.main()


if __name__ == "__main__":
    main()
