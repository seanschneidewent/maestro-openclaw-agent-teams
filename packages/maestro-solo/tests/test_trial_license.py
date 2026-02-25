from __future__ import annotations

from maestro_solo.solo_license import ensure_local_trial_license


def test_ensure_local_trial_license_creates_then_reuses_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))

    first = ensure_local_trial_license(
        purchase_id="trial-install-001",
        email="trial@example.com",
    )
    assert first["created"] is True
    assert first["status"]["valid"] is True
    assert first["status"]["plan_id"] == "solo_trial"

    second = ensure_local_trial_license(
        purchase_id="trial-install-002",
        email="trial@example.com",
    )
    assert second["created"] is False
    assert second["status"]["valid"] is True
