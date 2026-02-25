from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from fastapi.testclient import TestClient

from maestro_solo import license_service
from maestro_solo.entitlements import verify_entitlement_token


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


def test_issue_license_includes_entitlement_token_when_key_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_INTERNAL_TOKEN", "test-token")

    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PRIVATE_KEY", base64.urlsafe_b64encode(private_raw).decode("ascii").rstrip("="))
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PUBLIC_KEY", base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("="))

    client = TestClient(license_service.app)
    payload = {
        "purchase_id": "pur_api_002",
        "plan_id": "solo_monthly",
        "email": "owner@example.com",
    }
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "pur_api_002",
    }

    issued = client.post("/v1/licenses/solo/issue", json=payload, headers=headers)
    assert issued.status_code == 200
    token = str(issued.json().get("entitlement_token", "")).strip()
    assert token

    status = verify_entitlement_token(token)
    assert status["valid"] is True
    assert status["tier"] == "pro"
