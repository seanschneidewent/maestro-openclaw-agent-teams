"""Solo license primitives shared by CLI and services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from maestro_engine.utils import load_json, save_json


LICENSE_PREFIX = "MSOLO"
LICENSE_VERSION = 1
DEFAULT_PLAN_DAYS = 30
PLAN_DAYS: dict[str, int] = {
    "solo_trial": 14,
    "solo_test_monthly": 30,
    "solo_monthly": 30,
    "solo_yearly": 365,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def _license_secret() -> str:
    return os.environ.get("MAESTRO_SOLO_LICENSE_SECRET", "maestro-solo-dev-secret")


def _sign(payload_b64: str, *, secret: str | None = None) -> str:
    key = (secret or _license_secret()).encode("utf-8")
    digest = hmac.new(key, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _solo_home(home_dir: Path | None = None) -> Path:
    if home_dir is not None:
        return Path(home_dir).expanduser().resolve()
    override = os.environ.get("MAESTRO_SOLO_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".maestro-solo").resolve()


def local_license_path(home_dir: Path | None = None) -> Path:
    return _solo_home(home_dir=home_dir) / "license.json"


def _plan_days(plan_id: str) -> int:
    clean = str(plan_id).strip()
    if clean in PLAN_DAYS:
        return PLAN_DAYS[clean]
    return DEFAULT_PLAN_DAYS


def issue_solo_license(
    *,
    purchase_id: str,
    plan_id: str,
    email: str,
    now: datetime | None = None,
    secret: str | None = None,
) -> dict[str, Any]:
    issued = (now or _now()).astimezone(timezone.utc)
    expires = issued + timedelta(days=_plan_days(plan_id))
    payload = {
        "v": LICENSE_VERSION,
        "sku": "solo",
        "purchase_id": str(purchase_id).strip(),
        "plan_id": str(plan_id).strip(),
        "email": str(email).strip(),
        "issued_at": _iso(issued),
        "expires_at": _iso(expires),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    sig = _sign(payload_b64, secret=secret)
    license_key = f"{LICENSE_PREFIX}.{payload_b64}.{sig}"
    return {
        "license_key": license_key,
        "sku": "solo",
        "plan_id": payload["plan_id"],
        "purchase_id": payload["purchase_id"],
        "email": payload["email"],
        "issued_at": payload["issued_at"],
        "expires_at": payload["expires_at"],
    }


def verify_solo_license_key(
    license_key: str,
    *,
    now: datetime | None = None,
    secret: str | None = None,
) -> dict[str, Any]:
    key = str(license_key or "").strip()
    if not key:
        return {"valid": False, "error": "missing_license_key"}

    parts = key.split(".")
    if len(parts) != 3:
        return {"valid": False, "error": "invalid_format"}
    if parts[0] != LICENSE_PREFIX:
        return {"valid": False, "error": "invalid_prefix"}

    payload_b64, sig = parts[1], parts[2]
    expected_sig = _sign(payload_b64, secret=secret)
    if not hmac.compare_digest(sig, expected_sig):
        return {"valid": False, "error": "signature_mismatch"}

    try:
        payload_raw = _b64url_decode(payload_b64)
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return {"valid": False, "error": "invalid_payload"}

    if not isinstance(payload, dict):
        return {"valid": False, "error": "invalid_payload"}

    expires_at = _from_iso(str(payload.get("expires_at", "")).strip())
    if not expires_at:
        return {"valid": False, "error": "missing_expiry"}
    if expires_at.astimezone(timezone.utc) <= (now or _now()).astimezone(timezone.utc):
        return {
            "valid": False,
            "error": "expired",
            "sku": str(payload.get("sku", "")),
            "plan_id": str(payload.get("plan_id", "")),
            "purchase_id": str(payload.get("purchase_id", "")),
            "email": str(payload.get("email", "")),
            "issued_at": str(payload.get("issued_at", "")),
            "expires_at": str(payload.get("expires_at", "")),
        }

    return {
        "valid": True,
        "sku": str(payload.get("sku", "")),
        "plan_id": str(payload.get("plan_id", "")),
        "purchase_id": str(payload.get("purchase_id", "")),
        "email": str(payload.get("email", "")),
        "issued_at": str(payload.get("issued_at", "")),
        "expires_at": str(payload.get("expires_at", "")),
    }


def save_local_license(
    license_key: str,
    *,
    source: str = "billing_service",
    home_dir: Path | None = None,
) -> dict[str, Any]:
    status = verify_solo_license_key(license_key)
    payload = {
        "license_key": str(license_key).strip(),
        "valid": bool(status.get("valid")),
        "sku": str(status.get("sku", "")),
        "plan_id": str(status.get("plan_id", "")),
        "purchase_id": str(status.get("purchase_id", "")),
        "email": str(status.get("email", "")),
        "issued_at": str(status.get("issued_at", "")),
        "expires_at": str(status.get("expires_at", "")),
        "source": str(source).strip() or "unknown",
        "saved_at": _iso(_now()),
    }
    save_json(local_license_path(home_dir=home_dir), payload)
    return payload


def load_local_license(home_dir: Path | None = None) -> dict[str, Any]:
    payload = load_json(local_license_path(home_dir=home_dir), default={})
    return payload if isinstance(payload, dict) else {}


def ensure_local_trial_license(
    *,
    purchase_id: str,
    email: str,
    plan_id: str = "solo_trial",
    source: str = "quick_setup_trial",
    home_dir: Path | None = None,
) -> dict[str, Any]:
    """Create and save a local trial license when no valid local license exists."""
    existing = load_local_license(home_dir=home_dir)
    existing_key = str(existing.get("license_key", "")).strip()
    if existing_key:
        status = verify_solo_license_key(existing_key)
        if bool(status.get("valid")):
            return {
                "created": False,
                "saved": existing,
                "status": status,
            }

    issued = issue_solo_license(
        purchase_id=purchase_id,
        plan_id=plan_id,
        email=email,
    )
    saved = save_local_license(
        str(issued.get("license_key", "")),
        source=source,
        home_dir=home_dir,
    )
    status = verify_solo_license_key(str(saved.get("license_key", "")))
    return {
        "created": True,
        "saved": saved,
        "status": status,
    }
