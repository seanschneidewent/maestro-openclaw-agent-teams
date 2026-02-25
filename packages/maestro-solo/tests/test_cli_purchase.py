from __future__ import annotations

from argparse import Namespace

from maestro_solo import cli


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
