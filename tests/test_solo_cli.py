"""Tests for the Maestro Solo CLI surface."""

from __future__ import annotations

import pytest

from maestro import solo_cli
from maestro.solo_license import issue_solo_license, load_local_license


def _run_cli(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exc:
        solo_cli.main(argv)
    return int(exc.value.code)


def test_solo_status_without_license_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    code = _run_cli(["status"])
    assert code == 1


def test_solo_purchase_polls_until_licensed_and_saves_local_license(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setattr(solo_cli, "_open_url", lambda *_: None)
    monkeypatch.setattr(solo_cli.time, "sleep", lambda *_: None)

    issued = issue_solo_license(
        purchase_id="pur_cli_001",
        plan_id="solo_test_monthly",
        email="cli@example.com",
    )
    poll_responses = [
        {"status": "pending"},
        {"status": "licensed", "license_key": issued["license_key"]},
    ]

    def _fake_post(url: str, payload: dict, timeout: int = 20):
        return True, {
            "purchase_id": "pur_cli_001",
            "status": "pending",
            "checkout_url": "http://localhost/checkout/pur_cli_001",
            "poll_after_ms": 3000,
        }

    def _fake_get(url: str, timeout: int = 20):
        if poll_responses:
            return True, poll_responses.pop(0)
        return True, {"status": "licensed", "license_key": issued["license_key"]}

    monkeypatch.setattr(solo_cli, "_http_post_json", _fake_post)
    monkeypatch.setattr(solo_cli, "_http_get_json", _fake_get)

    code = _run_cli([
        "purchase",
        "--email",
        "cli@example.com",
        "--plan",
        "solo_test_monthly",
        "--no-open",
        "--timeout-seconds",
        "10",
    ])
    assert code == 0

    saved = load_local_license(home_dir=tmp_path)
    assert saved["plan_id"] == "solo_test_monthly"
    assert saved["license_key"] == issued["license_key"]

