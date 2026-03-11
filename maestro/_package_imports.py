"""Helpers for importing package-native modules from source checkouts.

Compatibility shim support: when running from the monorepo without installed
package wheels, add `packages/*/src` entries to `sys.path` before importing
`maestro_fleet` / `maestro_engine`.
"""

from __future__ import annotations

import sys
from pathlib import Path


_PACKAGE_SRC_BY_NAME = {
    "maestro_fleet": Path(__file__).resolve().parents[1] / "packages" / "maestro-fleet" / "src",
    "maestro_engine": Path(__file__).resolve().parents[1] / "packages" / "maestro-engine" / "src",
}


def ensure_package_src(package_name: str) -> None:
    package_src = _PACKAGE_SRC_BY_NAME.get(package_name)
    if package_src is None:
        return
    if package_src.exists() and str(package_src) not in sys.path:
        sys.path.insert(0, str(package_src))
