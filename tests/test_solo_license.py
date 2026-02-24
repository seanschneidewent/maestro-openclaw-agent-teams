"""Tests for Solo license primitives."""

from __future__ import annotations

from pathlib import Path

from maestro.solo_license import (
    issue_solo_license,
    load_local_license,
    save_local_license,
    verify_solo_license_key,
)


def test_issue_and_verify_solo_license_roundtrip():
    issued = issue_solo_license(
        purchase_id="pur_test_001",
        plan_id="solo_test_monthly",
        email="super@example.com",
    )
    status = verify_solo_license_key(issued["license_key"])
    assert status["valid"] is True
    assert status["sku"] == "solo"
    assert status["plan_id"] == "solo_test_monthly"
    assert status["purchase_id"] == "pur_test_001"


def test_save_and_load_local_license(tmp_path: Path):
    issued = issue_solo_license(
        purchase_id="pur_test_002",
        plan_id="solo_monthly",
        email="boss@example.com",
    )
    saved = save_local_license(issued["license_key"], home_dir=tmp_path)
    assert saved["valid"] is True

    loaded = load_local_license(home_dir=tmp_path)
    assert loaded["license_key"] == issued["license_key"]
    assert loaded["plan_id"] == "solo_monthly"

