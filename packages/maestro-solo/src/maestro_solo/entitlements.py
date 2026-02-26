"""Capability and entitlement helpers for Maestro Solo Core/Pro."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from maestro_engine.utils import load_json, save_json

from .solo_license import load_local_license, verify_solo_license_key


ENTITLEMENT_PREFIX = "MSENT"
ENTITLEMENT_VERSION = 1
TIER_CORE = "core"
TIER_PRO = "pro"
DEFAULT_OFFLINE_GRACE_HOURS = 72

CORE_CAPABILITIES = (
    "ingest",
    "generic_tools",
)
PRO_ONLY_CAPABILITIES = (
    "workspace_basics",
    "maestro_skill",
    "maestro_native_tools",
    "workspace_frontend",
)
PRO_PLAN_IDS = {
    "solo_monthly",
    "solo_yearly",
    "solo_test_monthly",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _solo_home(home_dir: Path | None = None) -> Path:
    if home_dir is not None:
        return Path(home_dir).expanduser().resolve()
    root = os.environ.get("MAESTRO_SOLO_HOME", "").strip()
    if root:
        return Path(root).expanduser().resolve()
    return (Path.home() / ".maestro-solo").resolve()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def normalize_tier(value: str | None) -> str:
    clean = str(value or "").strip().lower()
    if clean == TIER_PRO:
        return TIER_PRO
    return TIER_CORE


def capabilities_for_tier(tier: str | None) -> list[str]:
    base = list(CORE_CAPABILITIES)
    if normalize_tier(tier) == TIER_PRO:
        base.extend(PRO_ONLY_CAPABILITIES)
    # Preserve order while dropping duplicates.
    return list(dict.fromkeys(base))


def plan_tier(plan_id: str | None) -> str:
    clean = str(plan_id or "").strip().lower()
    if clean in PRO_PLAN_IDS:
        return TIER_PRO
    return TIER_CORE


def install_channel() -> str:
    """Install distribution channel override (`core`, `pro`, or `auto`)."""
    channel = str(os.environ.get("MAESTRO_INSTALL_CHANNEL", "auto")).strip().lower()
    if channel not in {TIER_CORE, TIER_PRO}:
        channel_file = _solo_home() / "install-channel.txt"
        if channel_file.exists():
            try:
                channel = channel_file.read_text(encoding="utf-8").strip().lower()
            except Exception:
                channel = "auto"
    if channel in {TIER_CORE, TIER_PRO}:
        return channel
    return "auto"


def entitlement_cache_path(home_dir: Path | None = None) -> Path:
    return _solo_home(home_dir=home_dir) / "entitlement.json"


def load_local_entitlement(home_dir: Path | None = None) -> dict[str, Any]:
    payload = load_json(entitlement_cache_path(home_dir=home_dir), default={})
    return payload if isinstance(payload, dict) else {}


def clear_local_entitlement(home_dir: Path | None = None):
    save_json(entitlement_cache_path(home_dir=home_dir), {})


def _public_key_text() -> str:
    return str(os.environ.get("MAESTRO_ENTITLEMENT_PUBLIC_KEY", "")).strip()


def _private_key_text() -> str:
    return str(os.environ.get("MAESTRO_ENTITLEMENT_PRIVATE_KEY", "")).strip()


def _parse_env_key_text(raw: str) -> str:
    text = str(raw or "").strip()
    if "-----BEGIN" in text and "\\n" in text:
        text = text.replace("\\n", "\n")
    return text


def _load_ed25519_public_key(raw: str) -> Ed25519PublicKey | None:
    text = _parse_env_key_text(raw)
    if not text:
        return None
    if "-----BEGIN" in text:
        try:
            key = serialization.load_pem_public_key(text.encode("utf-8"))
        except Exception:
            return None
        return key if isinstance(key, Ed25519PublicKey) else None
    try:
        key_bytes = _b64url_decode(text)
    except Exception:
        return None
    if len(key_bytes) != 32:
        return None
    return Ed25519PublicKey.from_public_bytes(key_bytes)


def _load_ed25519_private_key(raw: str) -> Ed25519PrivateKey | None:
    text = _parse_env_key_text(raw)
    if not text:
        return None
    if "-----BEGIN" in text:
        try:
            key = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
        except Exception:
            return None
        return key if isinstance(key, Ed25519PrivateKey) else None
    try:
        key_bytes = _b64url_decode(text)
    except Exception:
        return None
    if len(key_bytes) != 32:
        return None
    return Ed25519PrivateKey.from_private_bytes(key_bytes)


def issue_entitlement_token(
    *,
    subject: str,
    tier: str,
    plan_id: str = "",
    email: str = "",
    capabilities: list[str] | None = None,
    now: datetime | None = None,
    expires_days: int = 30,
) -> dict[str, Any]:
    private_key = _load_ed25519_private_key(_private_key_text())
    if private_key is None:
        return {"ok": False, "error": "entitlement_private_key_missing"}

    clean_tier = normalize_tier(tier)
    issued = (now or _now()).astimezone(timezone.utc)
    expires = issued + timedelta(days=max(1, int(expires_days)))

    payload = {
        "v": ENTITLEMENT_VERSION,
        "product": "maestro-solo",
        "sub": str(subject).strip(),
        "tier": clean_tier,
        "plan_id": str(plan_id).strip(),
        "email": str(email).strip(),
        "capabilities": list(dict.fromkeys(capabilities or capabilities_for_tier(clean_tier))),
        "issued_at": _iso(issued),
        "expires_at": _iso(expires),
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_raw)
    signature = private_key.sign(payload_b64.encode("utf-8"))
    token = f"{ENTITLEMENT_PREFIX}.{payload_b64}.{_b64url_encode(signature)}"
    return {"ok": True, "entitlement_token": token, **payload}


def verify_entitlement_token(
    entitlement_token: str,
    *,
    now: datetime | None = None,
    public_key: str | None = None,
) -> dict[str, Any]:
    token = str(entitlement_token or "").strip()
    if not token:
        return {"valid": False, "error": "missing_entitlement_token"}

    parts = token.split(".")
    if len(parts) != 3:
        return {"valid": False, "error": "invalid_format"}
    if parts[0] != ENTITLEMENT_PREFIX:
        return {"valid": False, "error": "invalid_prefix"}

    payload_b64 = parts[1]
    signature_b64 = parts[2]
    key = _load_ed25519_public_key(str(public_key) if public_key is not None else _public_key_text())
    if key is None:
        return {"valid": False, "error": "entitlement_public_key_missing"}

    try:
        key.verify(_b64url_decode(signature_b64), payload_b64.encode("utf-8"))
    except Exception:
        return {"valid": False, "error": "signature_mismatch"}

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return {"valid": False, "error": "invalid_payload"}

    if not isinstance(payload, dict):
        return {"valid": False, "error": "invalid_payload"}
    if int(payload.get("v", 0)) != ENTITLEMENT_VERSION:
        return {"valid": False, "error": "unsupported_version"}

    expires_at = _from_iso(str(payload.get("expires_at", "")))
    if not expires_at:
        return {"valid": False, "error": "missing_expiry"}
    if expires_at.astimezone(timezone.utc) <= (now or _now()).astimezone(timezone.utc):
        return {
            "valid": False,
            "error": "expired",
            "tier": normalize_tier(str(payload.get("tier", ""))),
            "capabilities": payload.get("capabilities", []),
            "expires_at": str(payload.get("expires_at", "")),
            "issued_at": str(payload.get("issued_at", "")),
            "sub": str(payload.get("sub", "")),
            "plan_id": str(payload.get("plan_id", "")),
            "email": str(payload.get("email", "")),
        }

    return {
        "valid": True,
        "tier": normalize_tier(str(payload.get("tier", ""))),
        "capabilities": list(payload.get("capabilities", [])) if isinstance(payload.get("capabilities"), list) else [],
        "expires_at": str(payload.get("expires_at", "")),
        "issued_at": str(payload.get("issued_at", "")),
        "sub": str(payload.get("sub", "")),
        "plan_id": str(payload.get("plan_id", "")),
        "email": str(payload.get("email", "")),
    }


def save_local_entitlement(
    entitlement_token: str,
    *,
    source: str = "manual",
    home_dir: Path | None = None,
) -> dict[str, Any]:
    token = _clean_text(entitlement_token)
    status = verify_entitlement_token(token)
    payload = {
        "entitlement_token": token,
        "source": str(source or "unknown").strip(),
        "saved_at": _iso(_now()),
        "valid": bool(status.get("valid")),
        "tier": normalize_tier(str(status.get("tier", TIER_CORE))),
        "capabilities": list(status.get("capabilities", [])) if isinstance(status.get("capabilities"), list) else [],
        "expires_at": str(status.get("expires_at", "")),
        "issued_at": str(status.get("issued_at", "")),
        "sub": str(status.get("sub", "")),
        "plan_id": str(status.get("plan_id", "")),
        "email": str(status.get("email", "")),
        "error": str(status.get("error", "")),
    }
    save_json(entitlement_cache_path(home_dir=home_dir), payload)
    return payload


def _within_offline_grace(saved_at: str, now: datetime | None = None) -> bool:
    saved = _from_iso(saved_at)
    if saved is None:
        return False
    grace_hours = max(0, int(os.environ.get("MAESTRO_OFFLINE_GRACE_HOURS", DEFAULT_OFFLINE_GRACE_HOURS)))
    elapsed = (now or _now()).astimezone(timezone.utc) - saved.astimezone(timezone.utc)
    return elapsed.total_seconds() <= (grace_hours * 3600)


def _core_channel_allows_pro_upgrade() -> bool:
    raw = str(os.environ.get("MAESTRO_ALLOW_PRO_ON_CORE_CHANNEL", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def resolve_effective_entitlement(*, home_dir: Path | None = None) -> dict[str, Any]:
    """Resolve current runtime tier and capabilities with core fallback."""
    channel = install_channel()
    allow_core_upgrade = _core_channel_allows_pro_upgrade()

    local_entitlement = load_local_entitlement(home_dir=home_dir)
    token = _clean_text(local_entitlement.get("entitlement_token"))
    if token:
        status = verify_entitlement_token(token)
        if bool(status.get("valid")):
            tier = normalize_tier(str(status.get("tier", TIER_CORE)))
            if tier == TIER_PRO and channel == TIER_CORE and not allow_core_upgrade:
                tier = TIER_CORE
            return {
                "tier": tier,
                "capabilities": list(status.get("capabilities", [])) or capabilities_for_tier(tier),
                "source": "entitlement_token",
                "expires_at": str(status.get("expires_at", "")),
                "plan_id": str(status.get("plan_id", "")),
                "email": str(status.get("email", "")),
            }
        if str(status.get("error", "")) == "expired" and _within_offline_grace(str(local_entitlement.get("saved_at", ""))):
            cached_tier = normalize_tier(str(local_entitlement.get("tier", TIER_CORE)))
            if cached_tier == TIER_PRO:
                return {
                    "tier": TIER_PRO,
                    "capabilities": list(local_entitlement.get("capabilities", [])) or capabilities_for_tier(TIER_PRO),
                    "source": "entitlement_cache_grace",
                    "stale": True,
                    "expires_at": str(local_entitlement.get("expires_at", "")),
                }

    local_license = load_local_license(home_dir=home_dir)
    license_key = str(local_license.get("license_key", "")).strip()
    if license_key:
        license_status = verify_solo_license_key(license_key)
        if bool(license_status.get("valid")):
            tier = plan_tier(str(license_status.get("plan_id", "")))
            if tier == TIER_PRO and (channel != TIER_CORE or allow_core_upgrade):
                return {
                    "tier": TIER_PRO,
                    "capabilities": capabilities_for_tier(TIER_PRO),
                    "source": "local_license",
                    "plan_id": str(license_status.get("plan_id", "")),
                    "expires_at": str(license_status.get("expires_at", "")),
                    "email": str(license_status.get("email", "")),
                }

    return {
        "tier": TIER_CORE,
        "capabilities": capabilities_for_tier(TIER_CORE),
        "source": "install_channel" if channel == TIER_CORE else "default_core",
    }


def has_capability(state: dict[str, Any], capability: str) -> bool:
    caps = state.get("capabilities", []) if isinstance(state.get("capabilities"), list) else []
    return str(capability).strip() in {str(item).strip() for item in caps}


def entitlement_label(state: dict[str, Any]) -> str:
    tier = normalize_tier(str(state.get("tier", TIER_CORE)))
    source = str(state.get("source", "unknown")).strip() or "unknown"
    return f"{tier} ({source})"
