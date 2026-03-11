"""Fleet deploy entrypoint wrappers.

Compatibility-first owner for Fleet deploy orchestration. The legacy root module
currently holds the implementation while the package surface becomes the single
obvious import path.
"""

from __future__ import annotations

from typing import Any


def _load_legacy_deploy() -> Any:
    import maestro.fleet_deploy as legacy_deploy

    return legacy_deploy


def run_deploy(*args: Any, **kwargs: Any) -> int:
    return int(_load_legacy_deploy().run_deploy(*args, **kwargs))
