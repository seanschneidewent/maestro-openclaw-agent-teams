from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from maestro_solo.entitlements import (
    clear_local_entitlement,
    issue_entitlement_token,
    resolve_effective_entitlement,
    save_local_entitlement,
    verify_entitlement_token,
)
from maestro_solo.solo_license import issue_solo_license, save_local_license


def _keypair_b64() -> tuple[str, str]:
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
    private_b64 = base64.urlsafe_b64encode(private_raw).decode("ascii").rstrip("=")
    public_b64 = base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")
    return private_b64, public_b64


def test_entitlement_issue_verify_roundtrip(monkeypatch):
    private_b64, public_b64 = _keypair_b64()
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PRIVATE_KEY", private_b64)
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PUBLIC_KEY", public_b64)

    issued = issue_entitlement_token(
        subject="pur_test_001",
        tier="pro",
        plan_id="solo_monthly",
        email="owner@example.com",
    )
    assert issued["ok"] is True
    status = verify_entitlement_token(issued["entitlement_token"])
    assert status["valid"] is True
    assert status["tier"] == "pro"
    assert status["plan_id"] == "solo_monthly"


def test_resolve_effective_entitlement_allows_pro_upgrade_on_core_channel_by_default(tmp_path, monkeypatch):
    private_b64, public_b64 = _keypair_b64()
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PRIVATE_KEY", private_b64)
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PUBLIC_KEY", public_b64)
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))

    issued = issue_entitlement_token(
        subject="pur_test_002",
        tier="pro",
        plan_id="solo_yearly",
        email="owner@example.com",
    )
    saved = save_local_entitlement(issued["entitlement_token"], source="unit_test", home_dir=tmp_path)
    assert saved["valid"] is True

    effective = resolve_effective_entitlement(home_dir=tmp_path)
    assert effective["tier"] == "pro"
    assert effective["source"] == "entitlement_token"

    monkeypatch.setenv("MAESTRO_INSTALL_CHANNEL", "core")
    still_pro = resolve_effective_entitlement(home_dir=tmp_path)
    assert still_pro["tier"] == "pro"
    assert still_pro["source"] == "entitlement_token"


def test_resolve_effective_entitlement_can_force_core_channel_when_upgrade_disabled(tmp_path, monkeypatch):
    private_b64, public_b64 = _keypair_b64()
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PRIVATE_KEY", private_b64)
    monkeypatch.setenv("MAESTRO_ENTITLEMENT_PUBLIC_KEY", public_b64)
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.setenv("MAESTRO_INSTALL_CHANNEL", "core")
    monkeypatch.setenv("MAESTRO_ALLOW_PRO_ON_CORE_CHANNEL", "0")

    issued = issue_entitlement_token(
        subject="pur_test_002b",
        tier="pro",
        plan_id="solo_yearly",
        email="owner@example.com",
    )
    saved = save_local_entitlement(issued["entitlement_token"], source="unit_test", home_dir=tmp_path)
    assert saved["valid"] is True

    forced = resolve_effective_entitlement(home_dir=tmp_path)
    assert forced["tier"] == "core"
    assert forced["source"] == "entitlement_token"


def test_resolve_effective_entitlement_falls_back_to_pro_license(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path))
    monkeypatch.delenv("MAESTRO_INSTALL_CHANNEL", raising=False)
    monkeypatch.delenv("MAESTRO_ENTITLEMENT_PUBLIC_KEY", raising=False)
    clear_local_entitlement(home_dir=tmp_path)

    issued = issue_solo_license(
        purchase_id="pur_test_003",
        plan_id="solo_test_monthly",
        email="owner@example.com",
    )
    save_local_license(issued["license_key"], source="unit_test", home_dir=tmp_path)

    effective = resolve_effective_entitlement(home_dir=tmp_path)
    assert effective["tier"] == "pro"
    assert effective["source"] == "local_license"
