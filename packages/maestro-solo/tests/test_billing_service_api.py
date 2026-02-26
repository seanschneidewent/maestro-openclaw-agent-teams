from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from maestro_solo import billing_service
from maestro_solo.solo_license import issue_solo_license


@pytest.fixture(autouse=True)
def _clear_database_url(monkeypatch):
    monkeypatch.delenv("MAESTRO_DATABASE_URL", raising=False)
    monkeypatch.setenv("MAESTRO_BILLING_REQUIRE_AUTH", "0")
    monkeypatch.setenv("MAESTRO_ENABLE_DEV_ENDPOINTS", "1")


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


def test_billing_state_uses_sqlite_database_when_configured(tmp_path, monkeypatch):
    db_path = tmp_path / "billing.sqlite3"
    solo_home = tmp_path / "solo-home"
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(solo_home))
    monkeypatch.setenv("MAESTRO_DATABASE_URL", f"sqlite:///{db_path}")

    billing_service._save_state(
        {
            "purchases": {
                "pur_sqlite_001": {
                    "purchase_id": "pur_sqlite_001",
                    "status": "pending",
                }
            },
            "processed_events": {
                "evt_sqlite_001": {
                    "type": "checkout.session.completed",
                    "processed_at": "2026-01-01T00:00:00Z",
                }
            },
        }
    )

    loaded = billing_service._load_state()
    assert loaded["purchases"]["pur_sqlite_001"]["status"] == "pending"
    assert loaded["processed_events"]["evt_sqlite_001"]["type"] == "checkout.session.completed"
    assert not (solo_home / "billing-service.json").exists()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT service_name FROM maestro_service_state WHERE service_name = ?",
            ("billing",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_create_purchase_live_requires_stripe_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))

    client = TestClient(billing_service.app)
    created = client.post(
        "/v1/solo/purchases",
        json={
            "email": "stripe@example.com",
            "plan_id": "solo_test_monthly",
            "mode": "live",
        },
    )
    assert created.status_code == 503
    assert "stripe_secret_key_missing" in str(created.json().get("detail", ""))


def test_create_purchase_test_mode_uses_local_checkout_even_when_stripe_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("MAESTRO_STRIPE_PRICE_ID_SOLO_TEST_MONTHLY", "price_test_123")

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
    assert payload["checkout_url"].startswith("http://testserver/checkout/")

    purchase = client.get(f"/v1/solo/purchases/{payload['purchase_id']}")
    assert purchase.status_code == 200
    assert purchase.json()["provider"] == "local_dev"


def test_create_purchase_uses_stripe_checkout_when_live_configured(tmp_path, monkeypatch):
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
            "mode": "live",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["checkout_url"] == "https://checkout.stripe.test/session/cs_test_123"

    purchase = client.get(f"/v1/solo/purchases/{payload['purchase_id']}")
    assert purchase.status_code == 200
    assert purchase.json()["provider"] == "stripe"


def test_create_stripe_checkout_session_does_not_prefill_customer_email(monkeypatch):
    monkeypatch.setenv("MAESTRO_STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("MAESTRO_STRIPE_PRICE_ID_LIVE_SOLO_MONTHLY", "price_live_123")

    captured: dict[str, dict] = {}

    class _FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "id": "cs_test_123",
                "url": "https://checkout.stripe.test/session/cs_test_123",
            }

    def _fake_post(url, data=None, headers=None, timeout=None):
        captured["data"] = dict(data or {})
        return _FakeResponse()

    monkeypatch.setattr(billing_service.httpx, "post", _fake_post)

    ok, payload = billing_service._create_stripe_checkout_session(
        {
            "purchase_id": "pur_test_123",
            "plan_id": "solo_monthly",
            "mode": "live",
            "email": "customer@example.com",
            "success_url": "",
            "cancel_url": "",
        },
        base_url="https://billing.example.com",
    )
    assert ok is True
    assert payload.get("id") == "cs_test_123"
    assert "customer_email" not in captured.get("data", {})


def test_create_purchase_uses_forwarded_base_url_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))

    client = TestClient(billing_service.app)
    created = client.post(
        "/v1/solo/purchases",
        json={
            "email": "forwarded@example.com",
            "plan_id": "solo_test_monthly",
            "mode": "test",
        },
        headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "maestro-billing.example.com",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["checkout_url"].startswith("https://maestro-billing.example.com/checkout/")


def test_checkout_page_redirects_for_stripe_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("MAESTRO_STRIPE_PRICE_ID_SOLO_TEST_MONTHLY", "price_test_123")

    def _fake_create_session(purchase: dict, *, base_url: str, timeout_seconds: int = 20):
        return True, {
            "id": "cs_test_123",
            "url": "https://checkout.stripe.test/session/cs_test_123",
        }

    monkeypatch.setattr(billing_service, "_create_stripe_checkout_session", _fake_create_session)

    client = TestClient(billing_service.app)
    created = client.post(
        "/v1/solo/purchases",
        json={
            "email": "stripe@example.com",
            "plan_id": "solo_test_monthly",
            "mode": "live",
        },
    )
    assert created.status_code == 200
    purchase_id = created.json()["purchase_id"]

    checkout = client.get(f"/checkout/{purchase_id}", follow_redirects=False)
    assert checkout.status_code == 307
    assert checkout.headers["location"] == "https://checkout.stripe.test/session/cs_test_123"


def test_upgrade_page_renders():
    client = TestClient(billing_service.app)
    response = client.get("/upgrade")
    assert response.status_code == 200
    assert "Upgrade to Pro" in response.text
    assert "Continue to Secure Checkout" in response.text


def test_installer_launcher_free_requires_package_spec(monkeypatch):
    monkeypatch.delenv("MAESTRO_INSTALLER_CORE_PACKAGE_SPEC", raising=False)
    monkeypatch.delenv("MAESTRO_CORE_PACKAGE_SPEC", raising=False)

    client = TestClient(billing_service.app)
    response = client.get("/free")
    assert response.status_code == 503
    assert "missing_core_package_spec" in str(response.json().get("detail", ""))


def test_installer_launcher_free_renders_script(monkeypatch):
    monkeypatch.setenv(
        "MAESTRO_INSTALLER_CORE_PACKAGE_SPEC",
        "https://downloads.example.com/maestro_engine.whl https://downloads.example.com/maestro_solo.whl",
    )

    client = TestClient(billing_service.app)
    response = client.get(
        "/install/free",
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "get.maestro.run"},
    )
    assert response.status_code == 200
    assert "export MAESTRO_CORE_PACKAGE_SPEC='https://downloads.example.com/maestro_engine.whl https://downloads.example.com/maestro_solo.whl'" in response.text
    assert "export MAESTRO_BILLING_URL='https://get.maestro.run'" in response.text
    assert "install-maestro-free-macos.sh" in response.text


def test_installer_launcher_pro_renders_script_with_pro_or_core_spec(monkeypatch):
    monkeypatch.delenv("MAESTRO_INSTALLER_PRO_PACKAGE_SPEC", raising=False)
    monkeypatch.setenv("MAESTRO_INSTALLER_CORE_PACKAGE_SPEC", "https://downloads.example.com/maestro_core_bundle.whl")

    client = TestClient(billing_service.app)
    response = client.get("/pro")
    assert response.status_code == 200
    assert "export MAESTRO_CORE_PACKAGE_SPEC='https://downloads.example.com/maestro_core_bundle.whl'" in response.text
    assert "install-maestro-pro-macos.sh" in response.text

    monkeypatch.delenv("MAESTRO_INSTALLER_CORE_PACKAGE_SPEC", raising=False)
    monkeypatch.delenv("MAESTRO_CORE_PACKAGE_SPEC", raising=False)
    second = client.get("/pro")
    assert second.status_code == 503
    assert "missing_pro_or_core_package_spec" in str(second.json().get("detail", ""))


def test_checkout_success_and_cancel_pages_render():
    client = TestClient(billing_service.app)

    success = client.get("/checkout/success?purchase_id=pur_test_123")
    assert success.status_code == 200
    assert "Payment received" in success.text
    assert "Success. You can close this tab." in success.text
    assert "pur_test_123" in success.text

    cancel = client.get("/checkout/cancel?purchase_id=pur_test_123")
    assert cancel.status_code == 200
    assert "Checkout canceled" in cancel.text
    assert "Return to Upgrade to Pro" in cancel.text


def test_create_portal_session_by_purchase_id(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))

    client = TestClient(billing_service.app)
    created = client.post(
        "/v1/solo/purchases",
        json={
            "email": "portal@example.com",
            "plan_id": "solo_monthly",
            "mode": "test",
        },
    )
    assert created.status_code == 200
    purchase_id = created.json()["purchase_id"]

    state = billing_service._load_state()
    purchase = state["purchases"][purchase_id]
    purchase["provider"] = "stripe"
    purchase["stripe_customer_id"] = "cus_portal_001"
    state["purchases"][purchase_id] = purchase
    billing_service._save_state(state)

    def _fake_create_portal(customer_id: str, *, return_url: str, idempotency_key: str, timeout_seconds: int = 20):
        assert customer_id == "cus_portal_001"
        assert idempotency_key == f"portal_{purchase_id}"
        assert return_url == "http://testserver/upgrade"
        return True, {"id": "bps_test_001", "url": "https://billing.stripe.test/session/bps_test_001"}

    monkeypatch.setattr(billing_service, "_create_stripe_billing_portal_session", _fake_create_portal)

    portal = client.post("/v1/solo/portal-sessions", json={"purchase_id": purchase_id})
    assert portal.status_code == 200
    payload = portal.json()
    assert payload["purchase_id"] == purchase_id
    assert payload["portal_url"] == "https://billing.stripe.test/session/bps_test_001"
    assert payload["return_url"] == "http://testserver/upgrade"


def test_create_portal_session_falls_back_to_latest_email_purchase(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))

    state = {
        "purchases": {
            "pur_old_001": {
                "purchase_id": "pur_old_001",
                "provider": "stripe",
                "email": "portal@example.com",
                "stripe_customer_id": "cus_old_001",
                "created_at": "2026-01-01T00:00:00Z",
            },
            "pur_new_001": {
                "purchase_id": "pur_new_001",
                "provider": "stripe",
                "email": "portal@example.com",
                "stripe_customer_id": "cus_new_001",
                "created_at": "2026-01-02T00:00:00Z",
            },
        },
        "processed_events": {},
    }
    billing_service._save_state(state)

    def _fake_create_portal(customer_id: str, *, return_url: str, idempotency_key: str, timeout_seconds: int = 20):
        assert customer_id == "cus_new_001"
        assert idempotency_key == "portal_pur_new_001"
        return True, {"id": "bps_test_002", "url": "https://billing.stripe.test/session/bps_test_002"}

    monkeypatch.setattr(billing_service, "_create_stripe_billing_portal_session", _fake_create_portal)

    client = TestClient(billing_service.app)
    portal = client.post("/v1/solo/portal-sessions", json={"email": "portal@example.com"})
    assert portal.status_code == 200
    payload = portal.json()
    assert payload["purchase_id"] == "pur_new_001"
    assert payload["portal_url"] == "https://billing.stripe.test/session/bps_test_002"


def test_create_portal_session_can_lookup_customer_by_email_without_purchase_record(monkeypatch):
    def _fake_lookup(email: str, *, timeout_seconds: int = 20):
        assert email == "lookup@example.com"
        return True, {"id": "cus_lookup_001"}

    def _fake_create_portal(customer_id: str, *, return_url: str, idempotency_key: str, timeout_seconds: int = 20):
        assert customer_id == "cus_lookup_001"
        assert idempotency_key == "portal_cus_lookup_001"
        assert return_url == "http://testserver/upgrade"
        return True, {"id": "bps_test_003", "url": "https://billing.stripe.test/session/bps_test_003"}

    monkeypatch.setattr(billing_service, "_find_stripe_customer_by_email", _fake_lookup)
    monkeypatch.setattr(billing_service, "_create_stripe_billing_portal_session", _fake_create_portal)

    client = TestClient(billing_service.app)
    portal = client.post("/v1/solo/portal-sessions", json={"email": "lookup@example.com"})
    assert portal.status_code == 200
    payload = portal.json()
    assert payload["purchase_id"] == ""
    assert payload["portal_url"] == "https://billing.stripe.test/session/bps_test_003"


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
