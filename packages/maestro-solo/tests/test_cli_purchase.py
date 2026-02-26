from __future__ import annotations

from argparse import Namespace

import pytest

from maestro_solo import cli


@pytest.fixture(autouse=True)
def _auth_headers(monkeypatch):
    monkeypatch.setattr(cli, "_auth_headers", lambda required=False: {"Authorization": "Bearer test-token"})


def _purchase_args(**overrides):
    payload = {
        "email": "you@example.com",
        "non_interactive": True,
        "billing_url": "http://127.0.0.1:8081",
        "plan": "solo_test_monthly",
        "mode": "test",
        "success_url": None,
        "cancel_url": None,
        "poll_seconds": 1,
        "timeout_seconds": 10,
        "no_open": True,
    }
    payload.update(overrides)
    return Namespace(**payload)


def test_purchase_ignores_null_entitlement_token(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_http_post_json",
        lambda *_args, **_kwargs: (
            True,
            {"purchase_id": "pur_test_001", "checkout_url": "http://127.0.0.1:8081/checkout/pur_test_001"},
        ),
    )
    monkeypatch.setattr(
        cli,
        "_http_get_json",
        lambda *_args, **_kwargs: (
            True,
            {
                "status": "licensed",
                "license_key": "solo_license_placeholder",
                "entitlement_token": None,
            },
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_solo_license_key",
        lambda *_args, **_kwargs: {"valid": True},
    )
    monkeypatch.setattr(
        cli,
        "save_local_license",
        lambda *_args, **_kwargs: {
            "sku": "solo",
            "plan_id": "solo_test_monthly",
            "expires_at": "2026-03-27T07:33:09Z",
        },
    )
    monkeypatch.setattr(
        cli,
        "resolve_effective_entitlement",
        lambda *_args, **_kwargs: {"tier": "pro"},
    )

    save_entitlement_calls = {"count": 0}

    def _save_local_entitlement(*_args, **_kwargs):
        save_entitlement_calls["count"] += 1
        return {"valid": True}

    monkeypatch.setattr(cli, "save_local_entitlement", _save_local_entitlement)

    code = cli._cmd_purchase(_purchase_args())
    assert code == 0
    assert save_entitlement_calls["count"] == 0


def test_purchase_preview_does_not_require_auth_or_create_checkout(monkeypatch):
    calls = {"post": 0, "auth": 0}

    def _fail_auth(required=False):
        calls["auth"] += 1
        raise RuntimeError("auth_should_not_be_called")

    def _post(*_args, **_kwargs):
        calls["post"] += 1
        return True, {}

    monkeypatch.setattr(cli, "_auth_headers", _fail_auth)
    monkeypatch.setattr(cli, "_http_post_json", _post)

    code = cli._cmd_purchase(_purchase_args(mode="live", preview=True))
    assert code == 0
    assert calls["auth"] == 0
    assert calls["post"] == 0


def test_purchase_does_not_send_localhost_success_or_cancel_urls_by_default(monkeypatch):
    captured: dict[str, dict] = {}

    def _fake_post(_url, payload, timeout=20, headers=None):
        captured["payload"] = dict(payload)
        return True, {
            "purchase_id": "pur_test_002",
            "checkout_url": "http://127.0.0.1:8081/checkout/pur_test_002",
        }

    monkeypatch.setattr(cli, "_http_post_json", _fake_post)
    monkeypatch.setattr(
        cli,
        "_http_get_json",
        lambda *_args, **_kwargs: (
            True,
            {
                "status": "licensed",
                "license_key": "solo_license_placeholder",
                "entitlement_token": "",
            },
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_solo_license_key",
        lambda *_args, **_kwargs: {"valid": True},
    )
    monkeypatch.setattr(
        cli,
        "save_local_license",
        lambda *_args, **_kwargs: {
            "sku": "solo",
            "plan_id": "solo_test_monthly",
            "expires_at": "2026-03-27T07:33:09Z",
        },
    )
    monkeypatch.setattr(
        cli,
        "resolve_effective_entitlement",
        lambda *_args, **_kwargs: {"tier": "pro"},
    )

    code = cli._cmd_purchase(_purchase_args())
    assert code == 0
    payload = captured["payload"]
    assert "success_url" not in payload
    assert "cancel_url" not in payload


def test_unsubscribe_uses_local_purchase_context(monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_local_license",
        lambda *_args, **_kwargs: {
            "purchase_id": "pur_local_001",
            "email": "owner@example.com",
        },
    )
    captured: dict[str, object] = {}

    def _fake_post(url, payload, timeout=20, headers=None):
        captured["url"] = url
        captured["payload"] = dict(payload)
        return True, {
            "purchase_id": "pur_local_001",
            "portal_url": "https://billing.stripe.com/p/session_test_123",
        }

    opened: list[str] = []
    monkeypatch.setattr(cli, "_http_post_json", _fake_post)
    monkeypatch.setattr(cli, "_open_url", lambda url: opened.append(url))

    args = Namespace(
        purchase_id="",
        email="",
        billing_url="http://127.0.0.1:8081",
        return_url="",
        no_open=False,
    )
    code = cli._cmd_unsubscribe(args)
    assert code == 0
    assert str(captured["url"]).endswith("/v1/solo/portal-sessions")
    assert captured["payload"] == {
        "purchase_id": "pur_local_001",
        "email": "owner@example.com",
    }
    assert opened == ["https://billing.stripe.com/p/session_test_123"]


def test_default_billing_url_points_to_production():
    assert cli.DEFAULT_BILLING_URL == "https://maestro-billing-service-production.up.railway.app"
