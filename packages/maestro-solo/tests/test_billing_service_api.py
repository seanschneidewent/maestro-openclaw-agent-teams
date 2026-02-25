from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from maestro_solo import billing_service
from maestro_solo.solo_license import issue_solo_license


def _stripe_signature(payload: bytes, *, secret: str, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else int(timestamp)
    signed_payload = f"{ts}.{payload.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


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
    purchase_id = created.json()["purchase_id"]

    marked = client.post("/v1/solo/dev/mark-paid", json={"purchase_id": purchase_id})
    assert marked.status_code == 200
    assert marked.json()["ok"] is True

    licensed = client.get(f"/v1/solo/purchases/{purchase_id}")
    assert licensed.status_code == 200
    assert licensed.json()["status"] == "licensed"


def test_create_purchase_uses_stripe_checkout_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("MAESTRO_STRIPE_PRICE_ID_SOLO_TEST_MONTHLY", "price_test_123")

    def _fake_create_session(purchase: dict, *, base_url: str, timeout_seconds: int = 20):
        assert purchase["plan_id"] == "solo_test_monthly"
        assert base_url.startswith("http://testserver")
        return True, {
            "id": "cs_test_123",
            "url": "https://checkout.stripe.test/session/cs_test_123",
            "customer": "cus_test_123",
            "subscription": "sub_test_123",
        }

    monkeypatch.setattr(billing_service, "_create_stripe_checkout_session", _fake_create_session)

    client = TestClient(billing_service.app)
    created = client.post(
        "/v1/solo/purchases",
        json={
            "email": "stripe@example.com",
            "plan_id": "solo_test_monthly",
            "mode": "test",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["checkout_url"] == "https://checkout.stripe.test/session/cs_test_123"

    purchase = client.get(f"/v1/solo/purchases/{payload['purchase_id']}")
    assert purchase.status_code == 200
    assert purchase.json()["provider"] == "stripe"


def test_stripe_webhook_checkout_session_completed_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_STRIPE_WEBHOOK_SECRET", "whsec_test_123")

    issue_calls = {"count": 0}

    def _fake_issue(purchase: dict, timeout_seconds: int = 10):
        issue_calls["count"] += 1
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
    purchase_id = created.json()["purchase_id"]

    event = {
        "id": "evt_test_checkout_completed",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_abc",
                "payment_status": "paid",
                "metadata": {"purchase_id": purchase_id},
                "customer": "cus_abc",
                "subscription": "sub_abc",
            }
        },
    }
    raw = json.dumps(event).encode("utf-8")
    signature = _stripe_signature(raw, secret="whsec_test_123")

    first = client.post(
        "/v1/stripe/webhook",
        content=raw,
        headers={"Stripe-Signature": signature, "content-type": "application/json"},
    )
    assert first.status_code == 200
    assert first.json()["ok"] is True

    second = client.post(
        "/v1/stripe/webhook",
        content=raw,
        headers={"Stripe-Signature": signature, "content-type": "application/json"},
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert issue_calls["count"] == 1

    purchase = client.get(f"/v1/solo/purchases/{purchase_id}")
    assert purchase.status_code == 200
    assert purchase.json()["status"] == "licensed"


def test_stripe_webhook_customer_subscription_deleted_cancels_purchase(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_STRIPE_WEBHOOK_SECRET", "whsec_test_123")

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
    purchase_id = created.json()["purchase_id"]

    state = billing_service._load_state()
    purchase = state["purchases"][purchase_id]
    purchase["stripe_subscription_id"] = "sub_test_cancel_123"
    state["purchases"][purchase_id] = purchase
    billing_service._save_state(state)

    event = {
        "id": "evt_test_subscription_deleted",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test_cancel_123",
                "customer": "cus_test_cancel",
                "metadata": {},
            }
        },
    }
    raw = json.dumps(event).encode("utf-8")
    signature = _stripe_signature(raw, secret="whsec_test_123")

    response = client.post(
        "/v1/stripe/webhook",
        content=raw,
        headers={"Stripe-Signature": signature, "content-type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

    purchase = client.get(f"/v1/solo/purchases/{purchase_id}")
    assert purchase.status_code == 200
    assert purchase.json()["status"] == "canceled"


def test_stripe_webhook_invoice_paid_provisions_by_subscription_id(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_STRIPE_WEBHOOK_SECRET", "whsec_test_123")

    issue_calls = {"count": 0}

    def _fake_issue(purchase: dict, timeout_seconds: int = 10):
        issue_calls["count"] += 1
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
    purchase_id = created.json()["purchase_id"]

    state = billing_service._load_state()
    purchase = state["purchases"][purchase_id]
    purchase["stripe_subscription_id"] = "sub_test_invoice_123"
    state["purchases"][purchase_id] = purchase
    billing_service._save_state(state)

    event = {
        "id": "evt_test_invoice_paid",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_test_123",
                "subscription": "sub_test_invoice_123",
                "customer": "cus_test_invoice_123",
                "payment_intent": "pi_test_invoice_123",
                "metadata": {},
            }
        },
    }
    raw = json.dumps(event).encode("utf-8")
    signature = _stripe_signature(raw, secret="whsec_test_123")

    response = client.post(
        "/v1/stripe/webhook",
        content=raw,
        headers={"Stripe-Signature": signature, "content-type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert issue_calls["count"] == 1

    purchase = client.get(f"/v1/solo/purchases/{purchase_id}")
    assert purchase.status_code == 200
    assert purchase.json()["status"] == "licensed"


def test_stripe_webhook_rejects_invalid_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_STRIPE_WEBHOOK_SECRET", "whsec_test_123")

    client = TestClient(billing_service.app)
    event = {"id": "evt_bad_sig", "type": "checkout.session.completed", "data": {"object": {}}}
    raw = json.dumps(event).encode("utf-8")

    response = client.post(
        "/v1/stripe/webhook",
        content=raw,
        headers={"Stripe-Signature": "t=1,v1=invalid", "content-type": "application/json"},
    )
    assert response.status_code == 400
