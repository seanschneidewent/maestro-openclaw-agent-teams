"""Standalone billing service for Solo purchase state + license provisioning."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

from .billing_storage import billing_state_default, load_billing_state, save_billing_state
from .billing_stripe import (
    create_billing_portal_session,
    create_checkout_session,
    find_customer_by_email,
)
from .billing_views import (
    render_checkout_cancel_page,
    render_checkout_cli_auth_complete_page,
    render_checkout_login_page,
    render_checkout_dev_page,
    render_checkout_success_page,
    render_upgrade_page,
)


PURCHASE_PENDING = "pending"
PURCHASE_PAID = "paid"
PURCHASE_LICENSED = "licensed"
PURCHASE_FAILED = "failed"
PURCHASE_CANCELED = "canceled"

STRIPE_WEBHOOK_TOLERANCE_SECONDS_DEFAULT = 300
AUTH_TOKEN_PREFIX = "MAAUTH"
AUTH_STATE_PREFIX = "MASTATE"
AUTH_COOKIE_NAME = "maestro_auth"
AUTH_TOKEN_TTL_SECONDS_DEFAULT = 60 * 60 * 24 * 7
AUTH_STATE_TTL_SECONDS_DEFAULT = 60 * 15
AUTH_CLI_SESSION_TTL_SECONDS_DEFAULT = 60 * 15
INSTALLER_SCRIPT_BASE_URL_DEFAULT = (
    "https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_optional_text(value: Any) -> str | None:
    clean = _clean_text(value)
    return clean or None


def _state_default() -> dict[str, Any]:
    return billing_state_default()


def _load_state() -> dict[str, Any]:
    return load_billing_state()


def _save_state(state: dict[str, Any]):
    save_billing_state(state)


def _purchase_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"pur_{stamp}{secrets.token_hex(4)}"


def _purchase_response(purchase: dict[str, Any]) -> dict[str, Any]:
    return {
        "purchase_id": str(purchase.get("purchase_id", "")),
        "status": str(purchase.get("status", PURCHASE_PENDING)),
        "plan_id": str(purchase.get("plan_id", "")),
        "email": str(purchase.get("email", "")),
        "provider": str(purchase.get("provider", "local_dev")),
        "checkout_url": str(purchase.get("checkout_url", "")),
        "license_key": purchase.get("license_key"),
        "entitlement_token": purchase.get("entitlement_token"),
        "error": purchase.get("error"),
    }


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def _is_truthy(raw: str) -> bool:
    return _clean_text(raw).lower() in {"1", "true", "yes", "on"}


def _billing_auth_required() -> bool:
    return not _clean_text(os.environ.get("MAESTRO_BILLING_REQUIRE_AUTH", "1")).lower() in {"0", "false", "no", "off"}


def _enable_dev_endpoints() -> bool:
    return _is_truthy(os.environ.get("MAESTRO_ENABLE_DEV_ENDPOINTS", "0"))


def _auth_secret() -> str:
    return _clean_text(os.environ.get("MAESTRO_AUTH_JWT_SECRET"))


def _auth_token_ttl_seconds() -> int:
    raw = _clean_text(os.environ.get("MAESTRO_AUTH_TOKEN_TTL_SECONDS"))
    if not raw:
        return AUTH_TOKEN_TTL_SECONDS_DEFAULT
    try:
        return max(300, int(raw))
    except ValueError:
        return AUTH_TOKEN_TTL_SECONDS_DEFAULT


def _auth_state_ttl_seconds() -> int:
    raw = _clean_text(os.environ.get("MAESTRO_AUTH_STATE_TTL_SECONDS"))
    if not raw:
        return AUTH_STATE_TTL_SECONDS_DEFAULT
    try:
        return max(60, int(raw))
    except ValueError:
        return AUTH_STATE_TTL_SECONDS_DEFAULT


def _auth_cli_session_ttl_seconds() -> int:
    raw = _clean_text(os.environ.get("MAESTRO_AUTH_CLI_SESSION_TTL_SECONDS"))
    if not raw:
        return AUTH_CLI_SESSION_TTL_SECONDS_DEFAULT
    try:
        return max(120, int(raw))
    except ValueError:
        return AUTH_CLI_SESSION_TTL_SECONDS_DEFAULT


def _google_client_id() -> str:
    return _clean_text(os.environ.get("MAESTRO_GOOGLE_CLIENT_ID"))


def _google_client_secret() -> str:
    return _clean_text(os.environ.get("MAESTRO_GOOGLE_CLIENT_SECRET"))


def _google_redirect_uri() -> str:
    return _clean_text(os.environ.get("MAESTRO_GOOGLE_REDIRECT_URI"))


def _google_oauth_configured() -> bool:
    return bool(_google_client_id() and _google_client_secret() and _google_redirect_uri())


def _allowed_google_domains() -> set[str]:
    raw = _clean_text(os.environ.get("MAESTRO_AUTH_ALLOWED_DOMAINS"))
    if not raw:
        return set()
    values: set[str] = set()
    for token in re.split(r"[,\s]+", raw):
        clean = _clean_text(token).lower()
        if clean:
            values.add(clean)
    return values


def _auth_cookie_secure(raw_request: Request) -> bool:
    override = _clean_text(os.environ.get("MAESTRO_AUTH_COOKIE_SECURE"))
    if override:
        return _is_truthy(override)
    forwarded_proto = _clean_text(raw_request.headers.get("x-forwarded-proto")).lower()
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip() == "https"
    return str(raw_request.url.scheme).lower() == "https"


def _require_auth_secret() -> str:
    secret = _auth_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="auth_not_configured:missing_MAESTRO_AUTH_JWT_SECRET")
    return secret


def _sign_blob(prefix: str, payload_b64: str, *, secret: str) -> str:
    signed = f"{prefix}.{payload_b64}".encode("utf-8")
    return _b64url_encode(hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).digest())


def _issue_signed_token(prefix: str, payload: dict[str, Any], *, secret: str) -> str:
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_raw)
    signature = _sign_blob(prefix, payload_b64, secret=secret)
    return f"{prefix}.{payload_b64}.{signature}"


def _verify_signed_token(token: str, *, expected_prefix: str, secret: str) -> tuple[bool, dict[str, Any] | str]:
    parts = _clean_text(token).split(".")
    if len(parts) != 3:
        return False, "invalid_format"
    prefix, payload_b64, signature = parts
    if prefix != expected_prefix:
        return False, "invalid_prefix"
    expected = _sign_blob(prefix, payload_b64, secret=secret)
    if not hmac.compare_digest(expected, signature):
        return False, "signature_mismatch"
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return False, "invalid_payload"
    if not isinstance(payload, dict):
        return False, "invalid_payload"
    return True, payload


def _issue_auth_token_for_user(*, sub: str, email: str, name: str = "", picture: str = "") -> str:
    now = int(time.time())
    payload = {
        "v": 1,
        "typ": "session",
        "sub": _clean_text(sub),
        "email": _clean_text(email),
        "name": _clean_text(name),
        "picture": _clean_text(picture),
        "iat": now,
        "exp": now + _auth_token_ttl_seconds(),
    }
    return _issue_signed_token(AUTH_TOKEN_PREFIX, payload, secret=_require_auth_secret())


def _verify_auth_token(token: str) -> tuple[bool, dict[str, Any] | str]:
    secret = _require_auth_secret()
    ok, parsed = _verify_signed_token(token, expected_prefix=AUTH_TOKEN_PREFIX, secret=secret)
    if not ok:
        return False, parsed
    payload = parsed if isinstance(parsed, dict) else {}
    if int(payload.get("v", 0)) != 1 or _clean_text(payload.get("typ")) != "session":
        return False, "invalid_token_type"
    if int(payload.get("exp", 0)) <= int(time.time()):
        return False, "expired"
    if not _clean_text(payload.get("sub")) or not _clean_text(payload.get("email")):
        return False, "missing_identity_fields"
    return True, payload


def _issue_oauth_state_token(*, cli_session_id: str = "", return_to: str = "") -> str:
    now = int(time.time())
    payload = {
        "v": 1,
        "typ": "oauth_state",
        "iat": now,
        "exp": now + _auth_state_ttl_seconds(),
        "nonce": secrets.token_urlsafe(18),
        "cli_session_id": _clean_text(cli_session_id),
        "return_to": _clean_text(return_to),
    }
    return _issue_signed_token(AUTH_STATE_PREFIX, payload, secret=_require_auth_secret())


def _verify_oauth_state_token(state_token: str) -> tuple[bool, dict[str, Any] | str]:
    secret = _require_auth_secret()
    ok, parsed = _verify_signed_token(state_token, expected_prefix=AUTH_STATE_PREFIX, secret=secret)
    if not ok:
        return False, parsed
    payload = parsed if isinstance(parsed, dict) else {}
    if int(payload.get("v", 0)) != 1 or _clean_text(payload.get("typ")) != "oauth_state":
        return False, "invalid_state_type"
    if int(payload.get("exp", 0)) <= int(time.time()):
        return False, "state_expired"
    return True, payload


def _extract_auth_token(raw_request: Request) -> str:
    header = _clean_text(raw_request.headers.get("Authorization"))
    if header.startswith("Bearer "):
        token = _clean_text(header[len("Bearer "):])
        if token:
            return token
    cookie_token = _clean_text(raw_request.cookies.get(AUTH_COOKIE_NAME))
    return cookie_token


def _resolve_auth_user(raw_request: Request, *, required: bool) -> dict[str, Any]:
    if not _billing_auth_required() and required:
        return {"sub": "", "email": "", "name": "", "picture": ""}

    token = _extract_auth_token(raw_request)
    if not token:
        if required:
            raise HTTPException(status_code=401, detail="auth_required")
        return {"authenticated": False}

    try:
        ok, parsed = _verify_auth_token(token)
    except HTTPException:
        if required:
            raise
        return {"authenticated": False, "error": "auth_not_configured"}

    if not ok:
        if required:
            raise HTTPException(status_code=401, detail=f"invalid_auth_token:{parsed}")
        return {"authenticated": False, "error": str(parsed)}

    user = parsed if isinstance(parsed, dict) else {}
    user["authenticated"] = True
    user["token"] = token
    return user


def _purchase_owned_by_user(purchase: dict[str, Any], user: dict[str, Any]) -> bool:
    if not _billing_auth_required():
        return True

    user_sub = _clean_text(user.get("sub"))
    user_email = _clean_text(user.get("email")).lower()
    owner_sub = _clean_text(purchase.get("owner_sub"))
    owner_email = _clean_text(purchase.get("owner_email")).lower()
    purchase_email = _clean_text(purchase.get("email")).lower()

    if owner_sub:
        return owner_sub == user_sub
    if owner_email:
        return owner_email == user_email
    return purchase_email == user_email


def _safe_return_to(raw_value: str) -> str:
    value = _clean_text(raw_value)
    return value if value.startswith("/") else ""


def _google_authorize_url(*, state_token: str, raw_request: Request) -> str:
    if not _google_oauth_configured():
        raise HTTPException(status_code=503, detail="google_oauth_not_configured")
    params = {
        "client_id": _google_client_id(),
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state_token,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def _exchange_google_code_for_access_token(code: str) -> str:
    payload = {
        "code": _clean_text(code),
        "client_id": _google_client_id(),
        "client_secret": _google_client_secret(),
        "redirect_uri": _google_redirect_uri(),
        "grant_type": "authorization_code",
    }
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data=payload,
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"google_token_exchange_failed:{exc}") from exc

    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    if response.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"google_token_exchange_status_{response.status_code}")

    access_token = _clean_text(data.get("access_token")) if isinstance(data, dict) else ""
    if not access_token:
        raise HTTPException(status_code=502, detail="google_token_exchange_missing_access_token")
    return access_token


def _fetch_google_user(access_token: str) -> dict[str, str]:
    try:
        response = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"google_userinfo_failed:{exc}") from exc

    try:
        data = response.json()
    except Exception:
        data = {}
    if response.status_code >= 300 or not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="google_userinfo_unavailable")

    sub = _clean_text(data.get("sub"))
    email = _clean_text(data.get("email")).lower()
    email_verified = bool(data.get("email_verified"))
    if not sub or not email:
        raise HTTPException(status_code=401, detail="google_identity_missing_fields")
    if not email_verified:
        raise HTTPException(status_code=401, detail="google_email_not_verified")

    allowed_domains = _allowed_google_domains()
    if allowed_domains:
        domain = email.split("@", 1)[-1] if "@" in email else ""
        if domain.lower() not in allowed_domains:
            raise HTTPException(status_code=403, detail="google_account_domain_not_allowed")

    return {
        "sub": sub,
        "email": email,
        "name": _clean_text(data.get("name")),
        "picture": _clean_text(data.get("picture")),
    }


def _set_auth_cookie(response: HTMLResponse, token: str, *, raw_request: Request):
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=_auth_token_ttl_seconds(),
        httponly=True,
        samesite="lax",
        secure=_auth_cookie_secure(raw_request),
        path="/",
    )


def _clear_auth_cookie(response: Any):
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")


def _prune_cli_auth_sessions(state: dict[str, Any]):
    sessions = state.get("auth_cli_sessions")
    if not isinstance(sessions, dict):
        state["auth_cli_sessions"] = {}
        return

    now = int(time.time())
    to_delete: list[str] = []
    for session_id, session in sessions.items():
        if not isinstance(session, dict):
            to_delete.append(str(session_id))
            continue
        expires_epoch = int(session.get("expires_epoch", 0))
        status = _clean_text(session.get("status"))
        completed_epoch = int(session.get("completed_epoch", 0))
        if expires_epoch and now > expires_epoch:
            to_delete.append(str(session_id))
            continue
        if status == "authenticated" and completed_epoch and now - completed_epoch > 600:
            to_delete.append(str(session_id))
    for session_id in to_delete:
        sessions.pop(session_id, None)

def _license_service_url() -> str:
    return os.environ.get("MAESTRO_LICENSE_URL", "http://127.0.0.1:8082").strip().rstrip("/")


def _internal_token() -> str:
    return os.environ.get("MAESTRO_INTERNAL_TOKEN", "dev-internal-token").strip()


def _issue_license_for_purchase(purchase: dict[str, Any], timeout_seconds: int = 10) -> tuple[bool, dict[str, Any]]:
    purchase_id = str(purchase.get("purchase_id", "")).strip()
    payload = {
        "purchase_id": purchase_id,
        "plan_id": str(purchase.get("plan_id", "")),
        "email": str(purchase.get("email", "")),
    }
    headers = {
        "Authorization": f"Bearer {_internal_token()}",
        "Idempotency-Key": purchase_id,
    }
    url = f"{_license_service_url()}/v1/licenses/solo/issue"
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    except Exception as exc:
        return False, {"error": f"license_service_unreachable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}

    if response.status_code >= 300:
        return False, {"error": f"license_service_status_{response.status_code}", "detail": data}

    license_key = _clean_text(data.get("license_key")) if isinstance(data, dict) else ""
    if not license_key:
        return False, {"error": "license_service_missing_key", "detail": data}
    return True, data if isinstance(data, dict) else {"license_key": license_key}


def _stripe_secret_key() -> str:
    return _clean_text(os.environ.get("MAESTRO_STRIPE_SECRET_KEY"))


def _stripe_webhook_secret() -> str:
    return _clean_text(os.environ.get("MAESTRO_STRIPE_WEBHOOK_SECRET"))


def _stripe_webhook_tolerance_seconds() -> int:
    raw = _clean_text(os.environ.get("MAESTRO_STRIPE_WEBHOOK_TOLERANCE_SECONDS"))
    if not raw:
        return STRIPE_WEBHOOK_TOLERANCE_SECONDS_DEFAULT
    try:
        return max(10, int(raw))
    except ValueError:
        return STRIPE_WEBHOOK_TOLERANCE_SECONDS_DEFAULT


def _request_base_url(raw_request: Request) -> str:
    forwarded_proto = _clean_text(raw_request.headers.get("x-forwarded-proto"))
    forwarded_host = _clean_text(raw_request.headers.get("x-forwarded-host"))
    if forwarded_proto and forwarded_host:
        proto = forwarded_proto.split(",")[0].strip().lower()
        host = forwarded_host.split(",")[0].strip()
        if proto and host:
            return f"{proto}://{host}"
    return str(raw_request.base_url).rstrip("/")


def _shell_single_quote(value: str) -> str:
    clean = str(value)
    return "'" + clean.replace("'", "'\"'\"'") + "'"


def _first_env_value(*keys: str) -> str:
    for key in keys:
        value = _clean_text(os.environ.get(key))
        if value:
            return value
    return ""


def _installer_script_base_url() -> str:
    return _first_env_value("MAESTRO_INSTALLER_SCRIPT_BASE_URL") or INSTALLER_SCRIPT_BASE_URL_DEFAULT


def _installer_free_script_url() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_FREE_SCRIPT_URL")
    if configured:
        return configured
    return f"{_installer_script_base_url().rstrip('/')}/install-maestro-free-macos.sh"


def _installer_pro_script_url() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_PRO_SCRIPT_URL")
    if configured:
        return configured
    return f"{_installer_script_base_url().rstrip('/')}/install-maestro-pro-macos.sh"


def _installer_core_package_spec() -> str:
    return _first_env_value("MAESTRO_INSTALLER_CORE_PACKAGE_SPEC", "MAESTRO_CORE_PACKAGE_SPEC")


def _installer_pro_package_spec() -> str:
    return _first_env_value("MAESTRO_INSTALLER_PRO_PACKAGE_SPEC", "MAESTRO_PRO_PACKAGE_SPEC")


def _build_installer_script(*, flow: str, billing_base_url: str) -> str:
    clean_flow = _clean_text(flow).lower()
    if clean_flow not in {"free", "pro"}:
        raise HTTPException(status_code=400, detail="invalid_install_flow")

    core_spec = _installer_core_package_spec()
    pro_spec = _installer_pro_package_spec()
    if clean_flow == "free" and not core_spec:
        raise HTTPException(status_code=503, detail="installer_not_configured:missing_core_package_spec")
    if clean_flow == "pro" and not pro_spec and not core_spec:
        raise HTTPException(status_code=503, detail="installer_not_configured:missing_pro_or_core_package_spec")

    script_url = _installer_free_script_url() if clean_flow == "free" else _installer_pro_script_url()
    env_assignments: list[tuple[str, str]] = []
    if core_spec:
        env_assignments.append(("MAESTRO_CORE_PACKAGE_SPEC", core_spec))
    if clean_flow == "pro" and pro_spec:
        env_assignments.append(("MAESTRO_PRO_PACKAGE_SPEC", pro_spec))
    if billing_base_url:
        env_assignments.append(("MAESTRO_BILLING_URL", billing_base_url))

    prefix = " ".join(f"{key}={_shell_single_quote(value)}" for key, value in env_assignments).strip()
    command = f"curl -fsSL {_shell_single_quote(script_url)} | bash"
    if prefix:
        command = f"{prefix} {command}"

    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "# Generated by Maestro installer launcher.\n"
        f"{command}\n"
    )


def _plan_checkout_mode(plan_id: str) -> str:
    clean = _clean_text(plan_id).lower()
    if "monthly" in clean or "yearly" in clean:
        return "subscription"
    return "payment"


def _plan_price_env_keys(plan_id: str, mode: str) -> list[str]:
    normalized_plan = re.sub(r"[^A-Z0-9]+", "_", _clean_text(plan_id).upper()).strip("_")
    normalized_mode = re.sub(r"[^A-Z0-9]+", "_", _clean_text(mode).upper()).strip("_")
    keys: list[str] = []
    if normalized_mode and normalized_plan:
        keys.append(f"MAESTRO_STRIPE_PRICE_ID_{normalized_mode}_{normalized_plan}")
    if normalized_plan:
        keys.append(f"MAESTRO_STRIPE_PRICE_ID_{normalized_plan}")
    keys.append("MAESTRO_STRIPE_PRICE_ID")
    return keys


def _stripe_price_id(plan_id: str, mode: str) -> str:
    for key in _plan_price_env_keys(plan_id, mode):
        value = _clean_text(os.environ.get(key))
        if value:
            return value
    return ""


def _stripe_billing_portal_return_url(base_url: str) -> str:
    configured = _clean_text(os.environ.get("MAESTRO_STRIPE_BILLING_PORTAL_RETURN_URL"))
    return configured or f"{base_url}/upgrade"


def _create_stripe_checkout_session(
    purchase: dict[str, Any],
    *,
    base_url: str,
    timeout_seconds: int = 20,
) -> tuple[bool, dict[str, Any]]:
    secret = _stripe_secret_key()
    purchase_id = _clean_text(purchase.get("purchase_id"))
    plan_id = _clean_text(purchase.get("plan_id"))
    mode = _clean_text(purchase.get("mode")) or "test"
    email = _clean_text(purchase.get("email"))
    price_id = _stripe_price_id(plan_id, mode)
    success_url = _clean_text(purchase.get("success_url")) or f"{base_url}/checkout/success?purchase_id={purchase_id}"
    cancel_url = _clean_text(purchase.get("cancel_url")) or f"{base_url}/checkout/cancel?purchase_id={purchase_id}"
    return create_checkout_session(
        stripe_secret_key=secret,
        purchase_id=purchase_id,
        plan_id=plan_id,
        mode=mode,
        email=email,
        price_id=price_id,
        checkout_mode=_plan_checkout_mode(plan_id),
        success_url=success_url,
        cancel_url=cancel_url,
        timeout_seconds=timeout_seconds,
    )


def _create_stripe_billing_portal_session(
    customer_id: str,
    *,
    return_url: str,
    idempotency_key: str,
    timeout_seconds: int = 20,
) -> tuple[bool, dict[str, Any]]:
    return create_billing_portal_session(
        stripe_secret_key=_stripe_secret_key(),
        customer_id=customer_id,
        return_url=return_url,
        idempotency_key=idempotency_key,
        timeout_seconds=timeout_seconds,
    )


def _find_stripe_customer_by_email(
    email: str,
    *,
    timeout_seconds: int = 20,
) -> tuple[bool, dict[str, Any]]:
    return find_customer_by_email(
        stripe_secret_key=_stripe_secret_key(),
        email=email,
        timeout_seconds=timeout_seconds,
    )


def _verify_stripe_signature(payload: bytes, signature_header: str) -> tuple[bool, dict[str, Any] | str]:
    secret = _stripe_webhook_secret()
    if not secret:
        return False, "stripe_webhook_secret_missing"

    header = _clean_text(signature_header)
    if not header:
        return False, "stripe_signature_missing"

    timestamp_raw = ""
    signatures: list[str] = []
    for part in header.split(","):
        key, sep, value = part.partition("=")
        if not sep:
            continue
        clean_key = _clean_text(key)
        clean_value = _clean_text(value)
        if clean_key == "t":
            timestamp_raw = clean_value
        elif clean_key == "v1" and clean_value:
            signatures.append(clean_value)

    if not timestamp_raw or not signatures:
        return False, "stripe_signature_invalid_format"

    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        return False, "stripe_signature_invalid_timestamp"

    if abs(int(time.time()) - timestamp) > _stripe_webhook_tolerance_seconds():
        return False, "stripe_signature_timestamp_out_of_tolerance"

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        return False, "stripe_signature_mismatch"

    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception:
        return False, "stripe_payload_invalid_json"
    if not isinstance(event, dict):
        return False, "stripe_payload_invalid_type"
    return True, event


def _transition_purchase_status(purchase: dict[str, Any], new_status: str, *, reason: str = "") -> tuple[bool, str]:
    target = _clean_text(new_status).lower()
    current = _clean_text(purchase.get("status")).lower() or PURCHASE_PENDING

    allowed = {
        PURCHASE_PENDING: {PURCHASE_PENDING, PURCHASE_PAID, PURCHASE_FAILED, PURCHASE_CANCELED},
        PURCHASE_PAID: {PURCHASE_PAID, PURCHASE_LICENSED, PURCHASE_FAILED, PURCHASE_CANCELED},
        PURCHASE_FAILED: {PURCHASE_FAILED, PURCHASE_PAID, PURCHASE_CANCELED},
        PURCHASE_LICENSED: {PURCHASE_LICENSED, PURCHASE_CANCELED},
        PURCHASE_CANCELED: {PURCHASE_CANCELED},
    }

    if current not in allowed:
        current = PURCHASE_PENDING

    if target not in allowed[current]:
        return False, f"invalid_transition:{current}->{target}"

    purchase["status"] = target
    purchase["updated_at"] = _now_iso()
    if target in {PURCHASE_PENDING, PURCHASE_PAID, PURCHASE_LICENSED}:
        purchase["error"] = None
    elif reason:
        purchase["error"] = reason
    return True, target


def _set_purchase_stripe_refs(
    purchase: dict[str, Any],
    *,
    checkout_session_id: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
    payment_intent_id: str | None = None,
):
    if _clean_text(checkout_session_id):
        purchase["stripe_checkout_session_id"] = _clean_text(checkout_session_id)
    if _clean_text(customer_id):
        purchase["stripe_customer_id"] = _clean_text(customer_id)
    if _clean_text(subscription_id):
        purchase["stripe_subscription_id"] = _clean_text(subscription_id)
    if _clean_text(payment_intent_id):
        purchase["stripe_payment_intent_id"] = _clean_text(payment_intent_id)
    purchase["updated_at"] = _now_iso()


def _provision_purchase_license(purchase: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    status = _clean_text(purchase.get("status")).lower() or PURCHASE_PENDING
    if status == PURCHASE_LICENSED:
        return True, {"status": PURCHASE_LICENSED, "already_licensed": True}
    if status == PURCHASE_CANCELED:
        return False, {"error": "purchase_canceled"}

    transitioned, reason = _transition_purchase_status(purchase, PURCHASE_PAID)
    if not transitioned:
        return False, {"error": reason}

    ok, issued = _issue_license_for_purchase(purchase)
    if not ok:
        error_text = _clean_text(issued.get("error")) or "license_issue_failed"
        _transition_purchase_status(purchase, PURCHASE_FAILED, reason=error_text)
        return False, {"error": error_text}

    transitioned, reason = _transition_purchase_status(purchase, PURCHASE_LICENSED)
    if not transitioned:
        return False, {"error": reason}

    purchase["license_key"] = _clean_optional_text(issued.get("license_key"))
    purchase["entitlement_token"] = _clean_optional_text(issued.get("entitlement_token"))
    purchase["licensed_at"] = _now_iso()
    purchase["error"] = None
    return True, {"status": PURCHASE_LICENSED}


def _event_already_processed(state: dict[str, Any], event_id: str) -> bool:
    processed = state.get("processed_events")
    if not isinstance(processed, dict):
        return False
    return event_id in processed


def _record_event_processed(state: dict[str, Any], event_id: str, event_type: str):
    processed = state.get("processed_events")
    if not isinstance(processed, dict):
        processed = {}
        state["processed_events"] = processed
    processed[event_id] = {
        "type": _clean_text(event_type),
        "processed_at": _now_iso(),
    }


def _extract_purchase_id_from_metadata(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return ""
    return _clean_text(metadata.get("purchase_id"))


def _find_purchase_by_subscription_id(state: dict[str, Any], subscription_id: str) -> tuple[str, dict[str, Any]] | None:
    target = _clean_text(subscription_id)
    if not target:
        return None
    purchases = state.get("purchases")
    if not isinstance(purchases, dict):
        return None
    for purchase_id, purchase in purchases.items():
        if not isinstance(purchase, dict):
            continue
        if _clean_text(purchase.get("stripe_subscription_id")) == target:
            return str(purchase_id), purchase
    return None


def _find_purchase_by_customer_id(state: dict[str, Any], customer_id: str) -> tuple[str, dict[str, Any]] | None:
    target = _clean_text(customer_id)
    if not target:
        return None
    purchases = state.get("purchases")
    if not isinstance(purchases, dict):
        return None
    for purchase_id, purchase in purchases.items():
        if not isinstance(purchase, dict):
            continue
        if _clean_text(purchase.get("stripe_customer_id")) == target:
            return str(purchase_id), purchase
    return None


def _find_latest_purchase_by_email(state: dict[str, Any], email: str) -> tuple[str, dict[str, Any]] | None:
    target = _clean_text(email).lower()
    if not target:
        return None
    purchases = state.get("purchases")
    if not isinstance(purchases, dict):
        return None

    matches: list[tuple[str, str, dict[str, Any]]] = []
    for purchase_id, purchase in purchases.items():
        if not isinstance(purchase, dict):
            continue
        purchase_email = _clean_text(purchase.get("email")).lower()
        if purchase_email != target:
            continue
        created_at = _clean_text(purchase.get("created_at"))
        matches.append((created_at, str(purchase_id), purchase))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    _, purchase_id, purchase = matches[0]
    return purchase_id, purchase


def _resolve_portal_purchase(
    state: dict[str, Any],
    *,
    purchase_id: str,
    email: str,
) -> tuple[str, dict[str, Any]] | None:
    purchases = state.get("purchases")
    if not isinstance(purchases, dict):
        return None

    normalized_purchase_id = _clean_text(purchase_id)
    if normalized_purchase_id:
        purchase = purchases.get(normalized_purchase_id)
        if isinstance(purchase, dict):
            return normalized_purchase_id, purchase

    return _find_latest_purchase_by_email(state, email)


def _handle_checkout_session_completed(state: dict[str, Any], event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    payload = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(payload, dict):
        return True, {"ignored": "missing_session_payload"}

    purchase_id = _extract_purchase_id_from_metadata(payload.get("metadata"))
    if not purchase_id:
        purchase_id = _clean_text(payload.get("client_reference_id"))
    if not purchase_id:
        return True, {"ignored": "missing_purchase_id"}

    purchases = state["purchases"]
    purchase = purchases.get(purchase_id)
    if not isinstance(purchase, dict):
        return True, {"ignored": "purchase_not_found", "purchase_id": purchase_id}

    _set_purchase_stripe_refs(
        purchase,
        checkout_session_id=_clean_text(payload.get("id")),
        customer_id=_clean_text(payload.get("customer")),
        subscription_id=_clean_text(payload.get("subscription")),
        payment_intent_id=_clean_text(payload.get("payment_intent")),
    )
    payment_status = _clean_text(payload.get("payment_status")).lower()
    if payment_status not in {"paid", "no_payment_required"}:
        return True, {"status": purchase.get("status"), "purchase_id": purchase_id, "ignored": "payment_not_settled"}

    ok, info = _provision_purchase_license(purchase)
    if not ok:
        return False, {"purchase_id": purchase_id, **info}
    purchases[purchase_id] = purchase
    return True, {"purchase_id": purchase_id, **info}


def _handle_invoice_paid(state: dict[str, Any], event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    payload = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(payload, dict):
        return True, {"ignored": "missing_invoice_payload"}

    purchase_id = _extract_purchase_id_from_metadata(payload.get("metadata"))
    purchase: dict[str, Any] | None = None
    if purchase_id:
        candidate = state["purchases"].get(purchase_id)
        if isinstance(candidate, dict):
            purchase = candidate

    if purchase is None:
        match = _find_purchase_by_subscription_id(state, _clean_text(payload.get("subscription")))
        if match is not None:
            purchase_id, purchase = match

    if purchase is None:
        match = _find_purchase_by_customer_id(state, _clean_text(payload.get("customer")))
        if match is not None:
            purchase_id, purchase = match

    if purchase is None or not purchase_id:
        return True, {"ignored": "invoice_purchase_not_found"}

    _set_purchase_stripe_refs(
        purchase,
        customer_id=_clean_text(payload.get("customer")),
        subscription_id=_clean_text(payload.get("subscription")),
        payment_intent_id=_clean_text(payload.get("payment_intent")),
    )

    ok, info = _provision_purchase_license(purchase)
    if not ok:
        return False, {"purchase_id": purchase_id, **info}
    state["purchases"][purchase_id] = purchase
    return True, {"purchase_id": purchase_id, **info}


def _handle_subscription_deleted(state: dict[str, Any], event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    payload = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(payload, dict):
        return True, {"ignored": "missing_subscription_payload"}

    purchase_id = _extract_purchase_id_from_metadata(payload.get("metadata"))
    purchase: dict[str, Any] | None = None

    if purchase_id:
        candidate = state["purchases"].get(purchase_id)
        if isinstance(candidate, dict):
            purchase = candidate

    if purchase is None:
        subscription_id = _clean_text(payload.get("id"))
        match = _find_purchase_by_subscription_id(state, subscription_id)
        if match is not None:
            purchase_id, purchase = match

    if purchase is None or not purchase_id:
        return True, {"ignored": "subscription_purchase_not_found"}

    _set_purchase_stripe_refs(
        purchase,
        customer_id=_clean_text(payload.get("customer")),
        subscription_id=_clean_text(payload.get("id")),
    )
    transitioned, reason = _transition_purchase_status(
        purchase,
        PURCHASE_CANCELED,
        reason="stripe_subscription_deleted",
    )
    if not transitioned:
        return False, {"purchase_id": purchase_id, "error": reason}
    state["purchases"][purchase_id] = purchase
    return True, {"purchase_id": purchase_id, "status": purchase.get("status")}


def _handle_checkout_session_expired(state: dict[str, Any], event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    payload = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(payload, dict):
        return True, {"ignored": "missing_session_payload"}

    purchase_id = _extract_purchase_id_from_metadata(payload.get("metadata"))
    if not purchase_id:
        purchase_id = _clean_text(payload.get("client_reference_id"))
    if not purchase_id:
        return True, {"ignored": "missing_purchase_id"}

    purchase = state["purchases"].get(purchase_id)
    if not isinstance(purchase, dict):
        return True, {"ignored": "purchase_not_found", "purchase_id": purchase_id}

    transitioned, reason = _transition_purchase_status(
        purchase,
        PURCHASE_CANCELED,
        reason="stripe_checkout_expired",
    )
    if not transitioned:
        return False, {"purchase_id": purchase_id, "error": reason}
    state["purchases"][purchase_id] = purchase
    return True, {"purchase_id": purchase_id, "status": purchase.get("status")}


def _handle_invoice_payment_failed(state: dict[str, Any], event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    payload = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(payload, dict):
        return True, {"ignored": "missing_invoice_payload"}

    match = _find_purchase_by_subscription_id(state, _clean_text(payload.get("subscription")))
    if match is None:
        return True, {"ignored": "invoice_purchase_not_found"}

    purchase_id, purchase = match
    transitioned, reason = _transition_purchase_status(
        purchase,
        PURCHASE_FAILED,
        reason="stripe_invoice_payment_failed",
    )
    if not transitioned:
        return False, {"purchase_id": purchase_id, "error": reason}
    state["purchases"][purchase_id] = purchase
    return True, {"purchase_id": purchase_id, "status": purchase.get("status")}


def _process_stripe_event(state: dict[str, Any], event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    event_id = _clean_text(event.get("id"))
    event_type = _clean_text(event.get("type"))
    if not event_id or not event_type:
        return False, {"error": "stripe_event_missing_fields"}

    if _event_already_processed(state, event_id):
        return True, {"duplicate": True, "event_id": event_id, "event_type": event_type}

    handlers = {
        "checkout.session.completed": _handle_checkout_session_completed,
        "invoice.paid": _handle_invoice_paid,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "checkout.session.expired": _handle_checkout_session_expired,
        "invoice.payment_failed": _handle_invoice_payment_failed,
    }
    handler = handlers.get(event_type)
    if handler is None:
        _record_event_processed(state, event_id, event_type)
        return True, {"ignored": "event_not_handled", "event_id": event_id, "event_type": event_type}

    ok, result = handler(state, event)
    if ok:
        _record_event_processed(state, event_id, event_type)
    return ok, {"event_id": event_id, "event_type": event_type, **result}


class CreatePurchaseRequest(BaseModel):
    email: str = Field(..., min_length=3)
    plan_id: str = Field(..., min_length=1)
    mode: str = Field(default="test")
    success_url: str | None = None
    cancel_url: str | None = None


class MarkPaidRequest(BaseModel):
    purchase_id: str = Field(..., min_length=1)


class CreateBillingPortalSessionRequest(BaseModel):
    purchase_id: str | None = None
    email: str | None = None
    return_url: str | None = None


class CreateCliAuthSessionRequest(BaseModel):
    return_to: str | None = None


app = FastAPI(title="Maestro Solo Billing Service", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/free")
@app.get("/install/free")
def install_free_script(raw_request: Request):
    script = _build_installer_script(flow="free", billing_base_url=_request_base_url(raw_request))
    return PlainTextResponse(script, media_type="text/x-shellscript; charset=utf-8")


@app.get("/pro")
@app.get("/install/pro")
def install_pro_script(raw_request: Request):
    script = _build_installer_script(flow="pro", billing_base_url=_request_base_url(raw_request))
    return PlainTextResponse(script, media_type="text/x-shellscript; charset=utf-8")


@app.get("/upgrade")
def upgrade_page(raw_request: Request):
    user = _resolve_auth_user(raw_request, required=False)
    if _billing_auth_required() and not bool(user.get("authenticated")):
        base_url = _request_base_url(raw_request)
        login_url = f"{base_url}/v1/auth/google/start?{urlencode({'return_to': '/upgrade'})}"
        return HTMLResponse(render_checkout_login_page(login_url=login_url))
    return HTMLResponse(render_upgrade_page(authenticated_email=_clean_text(user.get("email"))))


@app.get("/v1/auth/session")
def auth_session(raw_request: Request):
    user = _resolve_auth_user(raw_request, required=False)
    if not bool(user.get("authenticated")):
        return {"authenticated": False}
    return {
        "authenticated": True,
        "sub": _clean_text(user.get("sub")),
        "email": _clean_text(user.get("email")),
        "name": _clean_text(user.get("name")),
    }


@app.post("/v1/auth/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    _clear_auth_cookie(response)
    return response


@app.post("/v1/auth/cli/sessions")
def create_cli_auth_session(request: CreateCliAuthSessionRequest, raw_request: Request):
    if not _google_oauth_configured():
        raise HTTPException(status_code=503, detail="google_oauth_not_configured")
    _require_auth_secret()

    state = _load_state()
    _prune_cli_auth_sessions(state)
    sessions = state.get("auth_cli_sessions")
    if not isinstance(sessions, dict):
        sessions = {}
        state["auth_cli_sessions"] = sessions

    session_id = f"auth_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4)}"
    poll_token = secrets.token_urlsafe(24)
    expires_epoch = int(time.time()) + _auth_cli_session_ttl_seconds()
    safe_return_to = _safe_return_to(_clean_text(request.return_to))
    state_token = _issue_oauth_state_token(cli_session_id=session_id, return_to=safe_return_to)
    authorize_url = _google_authorize_url(state_token=state_token, raw_request=raw_request)
    base_url = _request_base_url(raw_request)

    sessions[session_id] = {
        "status": "pending",
        "poll_token": poll_token,
        "created_at": _now_iso(),
        "expires_epoch": expires_epoch,
        "return_to": safe_return_to,
        "authorize_url": authorize_url,
        "token": "",
        "user": {},
    }
    _save_state(state)
    return {
        "session_id": session_id,
        "poll_token": poll_token,
        "authorize_url": authorize_url,
        "poll_url": f"{base_url}/v1/auth/cli/sessions/{session_id}",
        "expires_at": datetime.fromtimestamp(expires_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@app.get("/v1/auth/cli/sessions/{session_id}")
def get_cli_auth_session(session_id: str, poll_token: str):
    state = _load_state()
    _prune_cli_auth_sessions(state)
    sessions = state.get("auth_cli_sessions")
    if not isinstance(sessions, dict):
        raise HTTPException(status_code=404, detail="auth_session_not_found")
    session = sessions.get(_clean_text(session_id))
    if not isinstance(session, dict):
        raise HTTPException(status_code=404, detail="auth_session_not_found")
    if _clean_text(session.get("poll_token")) != _clean_text(poll_token):
        raise HTTPException(status_code=403, detail="auth_session_poll_token_invalid")

    status = _clean_text(session.get("status")) or "pending"
    if status == "authenticated":
        user = session.get("user") if isinstance(session.get("user"), dict) else {}
        return {
            "status": "authenticated",
            "access_token": _clean_text(session.get("token")),
            "sub": _clean_text(user.get("sub")),
            "email": _clean_text(user.get("email")),
            "name": _clean_text(user.get("name")),
        }

    expires_epoch = int(session.get("expires_epoch", 0))
    if expires_epoch and int(time.time()) > expires_epoch:
        session["status"] = "expired"
        sessions[_clean_text(session_id)] = session
        _save_state(state)
        return {"status": "expired"}

    return {"status": status}


@app.get("/v1/auth/google/start")
def auth_google_start(raw_request: Request, cli_session_id: str | None = None, return_to: str | None = None):
    if not _google_oauth_configured():
        raise HTTPException(status_code=503, detail="google_oauth_not_configured")
    _require_auth_secret()

    clean_cli_session_id = _clean_text(cli_session_id)
    clean_return_to = _safe_return_to(_clean_text(return_to))

    if clean_cli_session_id:
        state = _load_state()
        _prune_cli_auth_sessions(state)
        sessions = state.get("auth_cli_sessions")
        session = sessions.get(clean_cli_session_id) if isinstance(sessions, dict) else None
        if not isinstance(session, dict):
            raise HTTPException(status_code=404, detail="auth_session_not_found")
        expires_epoch = int(session.get("expires_epoch", 0))
        if expires_epoch and int(time.time()) > expires_epoch:
            raise HTTPException(status_code=410, detail="auth_session_expired")
        session_return = _safe_return_to(_clean_text(session.get("return_to")))
        if session_return:
            clean_return_to = session_return

    state_token = _issue_oauth_state_token(
        cli_session_id=clean_cli_session_id,
        return_to=clean_return_to,
    )
    return RedirectResponse(url=_google_authorize_url(state_token=state_token, raw_request=raw_request), status_code=307)


@app.get("/v1/auth/google/callback")
def auth_google_callback(raw_request: Request, code: str = "", state: str = ""):
    clean_code = _clean_text(code)
    clean_state = _clean_text(state)
    if not clean_code or not clean_state:
        raise HTTPException(status_code=400, detail="google_callback_missing_code_or_state")

    ok, parsed_state = _verify_oauth_state_token(clean_state)
    if not ok:
        raise HTTPException(status_code=400, detail=f"google_callback_invalid_state:{parsed_state}")

    state_payload = parsed_state if isinstance(parsed_state, dict) else {}
    cli_session_id = _clean_text(state_payload.get("cli_session_id"))
    return_to = _safe_return_to(_clean_text(state_payload.get("return_to")))

    access_token = _exchange_google_code_for_access_token(clean_code)
    user = _fetch_google_user(access_token)
    session_token = _issue_auth_token_for_user(
        sub=_clean_text(user.get("sub")),
        email=_clean_text(user.get("email")),
        name=_clean_text(user.get("name")),
        picture=_clean_text(user.get("picture")),
    )

    if cli_session_id:
        state_obj = _load_state()
        _prune_cli_auth_sessions(state_obj)
        sessions = state_obj.get("auth_cli_sessions")
        session = sessions.get(cli_session_id) if isinstance(sessions, dict) else None
        if isinstance(session, dict):
            session["status"] = "authenticated"
            session["completed_epoch"] = int(time.time())
            session["token"] = session_token
            session["user"] = user
            sessions[cli_session_id] = session
            _save_state(state_obj)
        response = HTMLResponse(render_checkout_cli_auth_complete_page(email=_clean_text(user.get("email"))))
        _set_auth_cookie(response, session_token, raw_request=raw_request)
        return response

    redirect_target = return_to or "/upgrade"
    response = RedirectResponse(url=redirect_target, status_code=307)
    _set_auth_cookie(response, session_token, raw_request=raw_request)
    return response


@app.post("/v1/solo/purchases")
def create_purchase(request: CreatePurchaseRequest, raw_request: Request):
    auth_user = _resolve_auth_user(raw_request, required=True)
    purchase_id = _purchase_id()
    base_url = _request_base_url(raw_request)
    mode = (_clean_text(request.mode) or "test").lower()
    if mode not in {"test", "live"}:
        mode = "test"
    if mode == "live" and not _stripe_secret_key():
        raise HTTPException(status_code=503, detail="live_checkout_unavailable:stripe_secret_key_missing")
    user_email = _clean_text(auth_user.get("email")).lower()
    request_email = _clean_text(request.email).lower()
    if _billing_auth_required() and request_email != user_email:
        raise HTTPException(status_code=403, detail="email_mismatch_with_authenticated_user")

    purchase = {
        "purchase_id": purchase_id,
        "status": PURCHASE_PENDING,
        "plan_id": request.plan_id.strip(),
        "email": request_email,
        "owner_sub": _clean_text(auth_user.get("sub")),
        "owner_email": user_email,
        "mode": mode,
        "success_url": _clean_text(request.success_url),
        "cancel_url": _clean_text(request.cancel_url),
        "provider": "local_dev",
        "checkout_url": f"{base_url}/checkout/{purchase_id}",
        "stripe_checkout_session_id": None,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "stripe_payment_intent_id": None,
        "license_key": None,
        "entitlement_token": None,
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    if mode == "live":
        ok, stripe_session = _create_stripe_checkout_session(purchase, base_url=base_url)
        if not ok:
            raise HTTPException(status_code=502, detail=str(stripe_session.get("error", "stripe_checkout_failed")))
        checkout_url = _clean_text(stripe_session.get("url"))
        checkout_session_id = _clean_text(stripe_session.get("id"))
        if not checkout_url or not checkout_session_id:
            raise HTTPException(status_code=502, detail="stripe_checkout_missing_url")
        purchase["provider"] = "stripe"
        purchase["checkout_url"] = checkout_url
        _set_purchase_stripe_refs(
            purchase,
            checkout_session_id=checkout_session_id,
            customer_id=_clean_text(stripe_session.get("customer")),
            subscription_id=_clean_text(stripe_session.get("subscription")),
            payment_intent_id=_clean_text(stripe_session.get("payment_intent")),
        )

    state = _load_state()
    state["purchases"][purchase_id] = purchase
    _save_state(state)
    return {
        "purchase_id": purchase_id,
        "status": PURCHASE_PENDING,
        "checkout_url": str(purchase.get("checkout_url", "")),
        "poll_after_ms": 3000,
    }


@app.get("/v1/solo/purchases/{purchase_id}")
def get_purchase(purchase_id: str, raw_request: Request):
    auth_user = _resolve_auth_user(raw_request, required=True)
    state = _load_state()
    purchase = state["purchases"].get(str(purchase_id).strip())
    if not isinstance(purchase, dict):
        raise HTTPException(status_code=404, detail="purchase not found")
    if not _purchase_owned_by_user(purchase, auth_user):
        raise HTTPException(status_code=404, detail="purchase not found")
    return _purchase_response(purchase)


@app.post("/v1/solo/portal-sessions")
def create_portal_session(request: CreateBillingPortalSessionRequest, raw_request: Request):
    auth_user = _resolve_auth_user(raw_request, required=True)
    state = _load_state()
    user_email = _clean_text(auth_user.get("email")).lower()
    lookup_email = _clean_text(request.email).lower()
    if _billing_auth_required():
        if lookup_email and lookup_email != user_email:
            raise HTTPException(status_code=403, detail="email_mismatch_with_authenticated_user")
        lookup_email = user_email
    resolved = _resolve_portal_purchase(
        state,
        purchase_id=_clean_text(request.purchase_id),
        email=lookup_email,
    )
    purchase_id = ""
    purchase: dict[str, Any] | None = None
    provider = ""
    customer_id = ""
    if resolved is not None:
        purchase_id, purchase = resolved
        if isinstance(purchase, dict) and not _purchase_owned_by_user(purchase, auth_user):
            raise HTTPException(status_code=404, detail="purchase not found for portal session")
        provider = _clean_text(purchase.get("provider")).lower()
        customer_id = _clean_text(purchase.get("stripe_customer_id"))
        if not lookup_email:
            lookup_email = _clean_text(purchase.get("email"))

    if not customer_id and lookup_email:
        found, customer = _find_stripe_customer_by_email(lookup_email)
        if found:
            customer_id = _clean_text(customer.get("id"))

    if not customer_id:
        if resolved is None:
            raise HTTPException(status_code=404, detail="purchase not found for portal session")
        if provider and provider != "stripe":
            raise HTTPException(status_code=400, detail="billing_portal_available_for_stripe_only")
        raise HTTPException(status_code=409, detail="stripe_customer_missing_for_purchase")

    base_url = _request_base_url(raw_request)
    return_url = _clean_text(request.return_url) or _stripe_billing_portal_return_url(base_url)
    idempotency_key = f"portal_{purchase_id or customer_id}"
    ok, session = _create_stripe_billing_portal_session(
        customer_id,
        return_url=return_url,
        idempotency_key=idempotency_key,
    )
    if not ok:
        raise HTTPException(status_code=502, detail=str(session.get("error", "stripe_portal_session_failed")))

    portal_url = _clean_text(session.get("url"))
    if not portal_url:
        raise HTTPException(status_code=502, detail="stripe_portal_missing_url")

    if purchase_id and purchase is not None:
        purchase["updated_at"] = _now_iso()
        if not _clean_text(purchase.get("stripe_customer_id")):
            purchase["stripe_customer_id"] = customer_id
        state["purchases"][purchase_id] = purchase
        _save_state(state)
    return {
        "purchase_id": purchase_id,
        "portal_url": portal_url,
        "return_url": return_url,
    }


@app.post("/v1/solo/dev/mark-paid")
def mark_paid(request: MarkPaidRequest, raw_request: Request):
    if not _enable_dev_endpoints():
        raise HTTPException(status_code=404, detail="not_found")
    auth_user = _resolve_auth_user(raw_request, required=True)

    state = _load_state()
    purchase_id = request.purchase_id.strip()
    purchase = state["purchases"].get(purchase_id)
    if not isinstance(purchase, dict):
        raise HTTPException(status_code=404, detail="purchase not found")
    if not _purchase_owned_by_user(purchase, auth_user):
        raise HTTPException(status_code=404, detail="purchase not found")

    status = _clean_text(purchase.get("status")).lower() or PURCHASE_PENDING
    if status == PURCHASE_LICENSED:
        return {"ok": True, "status": PURCHASE_LICENSED}
    if status == PURCHASE_CANCELED:
        return {"ok": False, "status": PURCHASE_CANCELED}

    ok, result = _provision_purchase_license(purchase)
    state["purchases"][purchase_id] = purchase
    _save_state(state)
    return {"ok": ok, "status": purchase.get("status"), "detail": result}


@app.post("/v1/stripe/webhook")
async def stripe_webhook(raw_request: Request):
    payload = await raw_request.body()
    signature_header = _clean_text(raw_request.headers.get("Stripe-Signature"))
    verified, parsed = _verify_stripe_signature(payload, signature_header)
    if not verified:
        raise HTTPException(status_code=400, detail=str(parsed))
    event = parsed if isinstance(parsed, dict) else {}

    state = _load_state()
    ok, result = _process_stripe_event(state, event)
    _save_state(state)
    if not ok:
        raise HTTPException(status_code=500, detail=result.get("error", "stripe_event_failed"))
    return {"ok": True, **result}


@app.get("/checkout/success")
def checkout_success_page(raw_request: Request):
    purchase_id = _clean_text(raw_request.query_params.get("purchase_id"))
    return HTMLResponse(render_checkout_success_page(purchase_id))


@app.get("/checkout/cancel")
def checkout_cancel_page(raw_request: Request):
    purchase_id = _clean_text(raw_request.query_params.get("purchase_id"))
    return HTMLResponse(render_checkout_cancel_page(purchase_id))


@app.get("/checkout/{purchase_id}")
def checkout_page(purchase_id: str):
    purchase = _clean_text(purchase_id)
    state = _load_state()
    stored = state.get("purchases", {}).get(purchase)
    if isinstance(stored, dict):
        provider = _clean_text(stored.get("provider")).lower()
        checkout_url = _clean_text(stored.get("checkout_url"))
        mode = _clean_text(stored.get("mode")).lower() or "test"
        if provider == "stripe" and checkout_url:
            return RedirectResponse(url=checkout_url, status_code=307)
        if mode == "live":
            return HTMLResponse(
                "<h3>Checkout unavailable</h3><p>Live checkout is not configured for this purchase.</p>",
                status_code=503,
            )
    return HTMLResponse(render_checkout_dev_page(purchase))


def main(argv: list[str] | None = None):
    default_port_raw = _clean_text(os.environ.get("PORT")) or _clean_text(os.environ.get("MAESTRO_BILLING_PORT")) or "8081"
    try:
        default_port = int(default_port_raw)
    except ValueError:
        default_port = 8081
    default_host = _clean_text(os.environ.get("MAESTRO_BILLING_HOST")) or ("0.0.0.0" if _clean_text(os.environ.get("PORT")) else "127.0.0.1")

    parser = argparse.ArgumentParser(prog="maestro-billing-service")
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args(argv)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
