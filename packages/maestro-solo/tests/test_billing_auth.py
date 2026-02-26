from __future__ import annotations

from fastapi.testclient import TestClient

from maestro_solo import billing_service


def _auth_header_for(email: str, sub: str) -> dict[str, str]:
    token = billing_service._issue_auth_token_for_user(sub=sub, email=email, name="Test User")
    return {"Authorization": f"Bearer {token}"}


def test_purchase_requires_auth_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_BILLING_REQUIRE_AUTH", "1")
    monkeypatch.setenv("MAESTRO_AUTH_JWT_SECRET", "test-auth-secret")

    client = TestClient(billing_service.app)
    unauth = client.post(
        "/v1/solo/purchases",
        json={"email": "owner@example.com", "plan_id": "solo_monthly", "mode": "test"},
    )
    assert unauth.status_code == 401

    authed = client.post(
        "/v1/solo/purchases",
        json={"email": "owner@example.com", "plan_id": "solo_monthly", "mode": "test"},
        headers=_auth_header_for("owner@example.com", "google-oauth2|owner"),
    )
    assert authed.status_code == 200


def test_purchase_lookup_is_scoped_to_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_BILLING_REQUIRE_AUTH", "1")
    monkeypatch.setenv("MAESTRO_AUTH_JWT_SECRET", "test-auth-secret")

    client = TestClient(billing_service.app)
    owner_headers = _auth_header_for("owner@example.com", "google-oauth2|owner")
    created = client.post(
        "/v1/solo/purchases",
        json={"email": "owner@example.com", "plan_id": "solo_monthly", "mode": "test"},
        headers=owner_headers,
    )
    assert created.status_code == 200
    purchase_id = created.json()["purchase_id"]

    other_headers = _auth_header_for("other@example.com", "google-oauth2|other")
    forbidden_lookup = client.get(f"/v1/solo/purchases/{purchase_id}", headers=other_headers)
    assert forbidden_lookup.status_code == 404

    owner_lookup = client.get(f"/v1/solo/purchases/{purchase_id}", headers=owner_headers)
    assert owner_lookup.status_code == 200
