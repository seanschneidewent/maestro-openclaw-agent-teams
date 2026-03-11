from __future__ import annotations

import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parent
for package_src in (
    _ROOT / "packages" / "maestro-fleet" / "src",
    _ROOT / "packages" / "maestro-engine" / "src",
):
    if package_src.exists() and str(package_src) not in sys.path:
        sys.path.insert(0, str(package_src))


@pytest.fixture(autouse=True)
def _isolate_test_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    yield
