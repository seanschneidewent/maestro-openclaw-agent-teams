"""Standalone billing service for Solo purchase state + license provisioning."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .billing_storage import billing_state_default, load_billing_state, save_billing_state
from .billing_stripe import (
    create_billing_portal_session,
    create_checkout_session,
    find_customer_by_email,
)
from .billing_views import (
    render_checkout_cancel_page,
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


app = FastAPI(title="Maestro Solo Billing Service", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/upgrade")
def upgrade_page():
    return HTMLResponse(render_upgrade_page())


@app.post("/v1/solo/purchases")
def create_purchase(request: CreatePurchaseRequest, raw_request: Request):
    purchase_id = _purchase_id()
    base_url = _request_base_url(raw_request)
    mode = (_clean_text(request.mode) or "test").lower()
    if mode not in {"test", "live"}:
        mode = "test"
    if mode == "live" and not _stripe_secret_key():
        raise HTTPException(status_code=503, detail="live_checkout_unavailable:stripe_secret_key_missing")

    purchase = {
        "purchase_id": purchase_id,
        "status": PURCHASE_PENDING,
        "plan_id": request.plan_id.strip(),
        "email": request.email.strip(),
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
def get_purchase(purchase_id: str):
    state = _load_state()
    purchase = state["purchases"].get(str(purchase_id).strip())
    if not isinstance(purchase, dict):
        raise HTTPException(status_code=404, detail="purchase not found")
    return _purchase_response(purchase)


@app.post("/v1/solo/portal-sessions")
def create_portal_session(request: CreateBillingPortalSessionRequest, raw_request: Request):
    state = _load_state()
    lookup_email = _clean_text(request.email)
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
def mark_paid(request: MarkPaidRequest):
    state = _load_state()
    purchase_id = request.purchase_id.strip()
    purchase = state["purchases"].get(purchase_id)
    if not isinstance(purchase, dict):
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
