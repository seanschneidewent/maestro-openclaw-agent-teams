"""Tests for standalone Solo billing service API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from maestro import billing_service
from maestro.solo_license import issue_solo_license


def test_billing_purchase_and_mark_paid_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))

    def _fake_issue(purchase: dict, timeout_seconds: int = 10):
        issued = issue_solo_license(
            purchase_id=str(purchase.get("purchase_id", "")),
            plan_id=str(purchase.get("plan_id", "solo_test_monthly")),
            email=str(purchase.get("email", "super@example.com")),
        )
        return True, issued

    monkeypatch.setattr(billing_service, "_issue_license_for_purchase", _fake_issue)

    client = TestClient(billing_service.app)
    created = client.post(
        "/v1/solo/purchases",
        json={
            "email": "super@example.com",
            "plan_id": "solo_test_monthly",
            "mode": "test",
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    purchase_id = created_payload["purchase_id"]
    assert created_payload["status"] == "pending"
    assert purchase_id.startswith("pur_")

    pending = client.get(f"/v1/solo/purchases/{purchase_id}")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    marked = client.post("/v1/solo/dev/mark-paid", json={"purchase_id": purchase_id})
    assert marked.status_code == 200
    assert marked.json()["ok"] is True
    assert marked.json()["status"] == "licensed"

    licensed = client.get(f"/v1/solo/purchases/{purchase_id}")
    assert licensed.status_code == 200
    licensed_payload = licensed.json()
    assert licensed_payload["status"] == "licensed"
    assert isinstance(licensed_payload["license_key"], str)
    assert licensed_payload["license_key"].startswith("MSOLO.")

