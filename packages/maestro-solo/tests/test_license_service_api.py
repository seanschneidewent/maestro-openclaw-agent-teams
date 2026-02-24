from __future__ import annotations

from fastapi.testclient import TestClient

from maestro_solo import license_service


def test_issue_and_verify_solo_license_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_INTERNAL_TOKEN", "test-token")

    client = TestClient(license_service.app)
    payload = {
        "purchase_id": "pur_api_001",
        "plan_id": "solo_test_monthly",
        "email": "super@example.com",
    }
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "pur_api_001",
    }

    first = client.post("/v1/licenses/solo/issue", json=payload, headers=headers)
    assert first.status_code == 200
    first_data = first.json()

    second = client.post("/v1/licenses/solo/issue", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["license_key"] == first_data["license_key"]

    verify = client.post(
        "/v1/licenses/solo/verify",
        json={"license_key": first_data["license_key"]},
    )
    assert verify.status_code == 200
    verify_data = verify.json()
    assert verify_data["valid"] is True
    assert verify_data["plan_id"] == "solo_test_monthly"
