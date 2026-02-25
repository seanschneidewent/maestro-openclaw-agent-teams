"""Standalone billing service for Solo purchase state + license provisioning."""

from __future__ import annotations

import argparse
import html
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from maestro_engine.utils import load_json, save_json
from .state_store import load_service_state, save_service_state


PURCHASE_PENDING = "pending"
PURCHASE_PAID = "paid"
PURCHASE_LICENSED = "licensed"
PURCHASE_FAILED = "failed"
PURCHASE_CANCELED = "canceled"

STRIPE_ENDPOINT = "https://api.stripe.com/v1/checkout/sessions"
STRIPE_BILLING_PORTAL_ENDPOINT = "https://api.stripe.com/v1/billing_portal/sessions"
STRIPE_WEBHOOK_TOLERANCE_SECONDS_DEFAULT = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_optional_text(value: Any) -> str | None:
    clean = _clean_text(value)
    return clean or None


def _state_path() -> Path:
    root = os.environ.get("MAESTRO_SOLO_HOME", "").strip()
    base = Path(root).expanduser().resolve() if root else (Path.home() / ".maestro-solo").resolve()
    return base / "billing-service.json"


def _state_default() -> dict[str, Any]:
    return {"purchases": {}, "processed_events": {}}


def _load_state() -> dict[str, Any]:
    payload = load_service_state("billing", _state_default())
    if payload is None:
        payload = load_json(_state_path(), default={})
    if not isinstance(payload, dict):
        payload = {}
    purchases = payload.get("purchases")
    if not isinstance(purchases, dict):
        purchases = {}
    processed_events = payload.get("processed_events")
    if not isinstance(processed_events, dict):
        processed_events = {}
    return {"purchases": purchases, "processed_events": processed_events}


def _save_state(state: dict[str, Any]):
    if save_service_state("billing", state):
        return
    save_json(_state_path(), state)


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
    if not secret:
        return False, {"error": "stripe_secret_key_missing"}

    purchase_id = _clean_text(purchase.get("purchase_id"))
    plan_id = _clean_text(purchase.get("plan_id"))
    mode = _clean_text(purchase.get("mode")) or "test"
    email = _clean_text(purchase.get("email"))

    price_id = _stripe_price_id(plan_id, mode)
    if not price_id:
        return False, {"error": f"stripe_price_id_missing_for_plan:{plan_id}"}

    success_url = _clean_text(purchase.get("success_url")) or f"{base_url}/checkout/success?purchase_id={purchase_id}"
    cancel_url = _clean_text(purchase.get("cancel_url")) or f"{base_url}/checkout/cancel?purchase_id={purchase_id}"

    payload = {
        "mode": _plan_checkout_mode(plan_id),
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": purchase_id,
        "metadata[purchase_id]": purchase_id,
        "metadata[plan_id]": plan_id,
        "metadata[email]": email,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
    }
    headers = {
        "Authorization": f"Bearer {secret}",
        "Idempotency-Key": purchase_id,
    }

    try:
        response = httpx.post(STRIPE_ENDPOINT, data=payload, headers=headers, timeout=timeout_seconds)
    except Exception as exc:
        return False, {"error": f"stripe_unreachable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}

    if response.status_code >= 300:
        return False, {"error": f"stripe_status_{response.status_code}", "detail": data}
    if not isinstance(data, dict):
        return False, {"error": "stripe_invalid_response"}

    checkout_url = _clean_text(data.get("url"))
    checkout_session_id = _clean_text(data.get("id"))
    if not checkout_url or not checkout_session_id:
        return False, {"error": "stripe_missing_checkout_url", "detail": data}
    return True, data


def _create_stripe_billing_portal_session(
    customer_id: str,
    *,
    return_url: str,
    idempotency_key: str,
    timeout_seconds: int = 20,
) -> tuple[bool, dict[str, Any]]:
    secret = _stripe_secret_key()
    if not secret:
        return False, {"error": "stripe_secret_key_missing"}

    customer = _clean_text(customer_id)
    if not customer:
        return False, {"error": "stripe_customer_id_missing"}

    payload = {
        "customer": customer,
        "return_url": _clean_text(return_url),
    }
    headers = {
        "Authorization": f"Bearer {secret}",
        "Idempotency-Key": idempotency_key,
    }
    try:
        response = httpx.post(
            STRIPE_BILLING_PORTAL_ENDPOINT,
            data=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return False, {"error": f"stripe_portal_unreachable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    if response.status_code >= 300:
        return False, {"error": f"stripe_portal_status_{response.status_code}", "detail": data}
    if not isinstance(data, dict):
        return False, {"error": "stripe_portal_invalid_response"}
    if not _clean_text(data.get("url")):
        return False, {"error": "stripe_portal_missing_url", "detail": data}
    return True, data


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
    body = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Upgrade to Maestro Solo Pro</title>
    <style>
      :root {
        --ink: #13212f;
        --muted: #4a5b6a;
        --accent: #0d9f6e;
        --accent-strong: #0b825b;
        --card: rgba(255, 255, 255, 0.88);
        --bg-a: #f6efe5;
        --bg-b: #dce9f5;
        --line: #d3deea;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        min-height: 100vh;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(1200px 720px at -10% -10%, #ffe4c5 0%, transparent 60%),
          radial-gradient(800px 480px at 110% 110%, #d5ecff 0%, transparent 60%),
          linear-gradient(150deg, var(--bg-a), var(--bg-b));
        display: grid;
        place-items: center;
        padding: 20px;
      }
      .panel {
        width: min(560px, 100%);
        border: 1px solid var(--line);
        border-radius: 18px;
        background: var(--card);
        box-shadow: 0 18px 48px rgba(28, 44, 60, 0.12);
        backdrop-filter: blur(4px);
        padding: 26px;
      }
      .eyebrow {
        display: inline-block;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #0c6d92;
        font-weight: 700;
        margin-bottom: 8px;
      }
      h1 {
        margin: 0 0 8px;
        font-size: clamp(28px, 4vw, 36px);
        line-height: 1.08;
        letter-spacing: -0.02em;
      }
      p {
        margin: 0 0 16px;
        color: var(--muted);
        line-height: 1.5;
      }
      form {
        margin-top: 14px;
        display: grid;
        gap: 12px;
      }
      label {
        display: grid;
        gap: 6px;
        font-size: 13px;
        color: #2d4254;
      }
      input, select {
        border: 1px solid #b8c6d4;
        border-radius: 12px;
        padding: 12px 13px;
        font-size: 15px;
        background: #fff;
        color: #142536;
      }
      button {
        margin-top: 4px;
        border: 0;
        border-radius: 12px;
        padding: 13px 16px;
        font-size: 15px;
        font-weight: 700;
        color: #fff;
        background: linear-gradient(135deg, var(--accent), #1ca47b);
        cursor: pointer;
      }
      button:hover { background: linear-gradient(135deg, var(--accent-strong), #198f6b); }
      button[disabled] { opacity: 0.7; cursor: default; }
      .note {
        margin-top: 12px;
        font-size: 12px;
        color: #486071;
      }
      .error {
        display: none;
        margin-top: 10px;
        padding: 11px 12px;
        border-radius: 10px;
        border: 1px solid #f4b2b2;
        background: #fff4f4;
        color: #952626;
        font-size: 13px;
      }
      .error.show { display: block; }
    </style>
  </head>
  <body>
    <main class="panel">
      <div class="eyebrow">Maestro Solo Pro</div>
      <h1>Upgrade to Pro</h1>
      <p>Enter your email, continue to secure Stripe checkout, and Pro capabilities are provisioned automatically after payment.</p>
      <form id="upgrade-form">
        <label>
          Email
          <input id="email" type="email" required placeholder="you@example.com" />
        </label>
        <label>
          Plan
          <select id="plan">
            <option value="solo_monthly" selected>Solo Pro Monthly</option>
          </select>
        </label>
        <button id="submit" type="submit">Continue to Secure Checkout</button>
      </form>
      <div id="error" class="error"></div>
      <div class="note">Payment is processed by Stripe. Your card details are never entered on this page.</div>
    </main>
    <script>
      const form = document.getElementById("upgrade-form");
      const email = document.getElementById("email");
      const plan = document.getElementById("plan");
      const submit = document.getElementById("submit");
      const error = document.getElementById("error");

      function showError(message) {
        error.textContent = message || "Unable to start checkout.";
        error.classList.add("show");
      }

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        error.classList.remove("show");
        submit.disabled = true;
        submit.textContent = "Starting checkout...";

        try {
          const res = await fetch("/v1/solo/purchases", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              email: email.value.trim(),
              plan_id: plan.value,
              mode: "live"
            })
          });
          const data = await res.json();
          if (!res.ok) {
            throw new Error((data && data.detail) || "purchase_create_failed");
          }
          if (!data.checkout_url) {
            throw new Error("missing_checkout_url");
          }
          window.location.href = data.checkout_url;
        } catch (err) {
          showError(String(err.message || err));
          submit.disabled = false;
          submit.textContent = "Continue to Secure Checkout";
        }
      });
    </script>
  </body>
</html>"""
    return HTMLResponse(body)


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
    resolved = _resolve_portal_purchase(
        state,
        purchase_id=_clean_text(request.purchase_id),
        email=_clean_text(request.email),
    )
    if resolved is None:
        raise HTTPException(status_code=404, detail="purchase not found for portal session")

    purchase_id, purchase = resolved
    provider = _clean_text(purchase.get("provider")).lower()
    if provider != "stripe":
        raise HTTPException(status_code=400, detail="billing_portal_available_for_stripe_only")

    customer_id = _clean_text(purchase.get("stripe_customer_id"))
    if not customer_id:
        raise HTTPException(status_code=409, detail="stripe_customer_missing_for_purchase")

    base_url = _request_base_url(raw_request)
    return_url = _clean_text(request.return_url) or _stripe_billing_portal_return_url(base_url)
    idempotency_key = f"portal_{purchase_id}"
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

    purchase["updated_at"] = _now_iso()
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
    purchase_safe = html.escape(purchase_id)
    purchase_json = json.dumps(purchase_id)
    body = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Payment Received</title>
    <style>
      body {{ font-family: "Avenir Next", "Segoe UI", sans-serif; margin: 0; padding: 22px; background: #f4f7fb; color: #172532; }}
      .box {{ max-width: 680px; margin: 0 auto; background: #fff; border: 1px solid #d8e2ec; border-radius: 12px; padding: 18px; }}
      .pill {{ display: inline-block; margin-bottom: 8px; padding: 6px 10px; border-radius: 999px; background: #e7f7ee; color: #1d6a3f; font-size: 12px; font-weight: 700; }}
      h2 {{ margin-top: 0; }}
      code {{ background: #f1f5f8; border-radius: 6px; padding: 2px 6px; }}
      .muted {{ color: #4c6073; }}
      .state {{ margin-top: 12px; padding: 10px 12px; border-radius: 8px; background: #edf3fb; border: 1px solid #d3e0ef; }}
      .state.ok {{ background: #e9f7ee; border-color: #c4e9d0; color: #175e37; }}
    </style>
  </head>
  <body>
    <div class="box">
      <div class="pill">Success. You can close this tab.</div>
      <h2>Payment received</h2>
      <p class="muted">Stripe checkout completed. We are confirming your license provisioning.</p>
      <p>Purchase ID: <code>{purchase_safe or "unknown"}</code></p>
      <div id="status" class="state">Checking purchase status...</div>
      <p class="muted">If you started this from the terminal, return to it and wait for <code>status: licensed</code>.</p>
    </div>
    <script>
      const purchaseId = {purchase_json};
      const statusEl = document.getElementById("status");

      async function poll() {{
        if (!purchaseId) {{
          statusEl.textContent = "Payment completed. You can close this tab.";
          statusEl.classList.add("ok");
          return;
        }}
        try {{
          const res = await fetch("/v1/solo/purchases/" + encodeURIComponent(purchaseId));
          const data = await res.json();
          const state = data.status || "unknown";
          if (state === "licensed") {{
            statusEl.textContent = "Success. License is active. You can close this tab.";
            statusEl.classList.add("ok");
            return;
          }}
          if (state === "failed" || state === "canceled") {{
            statusEl.textContent = "Checkout completed but license status is " + state + ". Return to terminal for details.";
            return;
          }}
          statusEl.textContent = "Current status: " + state;
          if (state !== "failed" && state !== "canceled") {{
            setTimeout(poll, 2500);
          }}
        }} catch (err) {{
          statusEl.textContent = "Payment completed. Status lookup failed; return to terminal to confirm license.";
        }}
      }}
      poll();
    </script>
  </body>
</html>"""
    return HTMLResponse(body)


@app.get("/checkout/cancel")
def checkout_cancel_page(raw_request: Request):
    purchase_id = _clean_text(raw_request.query_params.get("purchase_id"))
    purchase_safe = html.escape(purchase_id)
    body = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Checkout Canceled</title>
    <style>
      body {{ font-family: "Avenir Next", "Segoe UI", sans-serif; margin: 0; padding: 22px; background: #f7f8fa; color: #172532; }}
      .box {{ max-width: 620px; margin: 0 auto; background: #fff; border: 1px solid #dae1e8; border-radius: 12px; padding: 18px; }}
      h2 {{ margin-top: 0; }}
      code {{ background: #f2f5f7; border-radius: 6px; padding: 2px 6px; }}
      .muted {{ color: #4d6274; }}
    </style>
  </head>
  <body>
    <div class="box">
      <h2>Checkout canceled</h2>
      <p class="muted">No charge was completed. You can restart anytime from the upgrade page.</p>
      <p>Purchase ID: <code>{purchase_safe or "unknown"}</code></p>
      <p><a href="/upgrade">Return to Upgrade to Pro</a></p>
    </div>
  </body>
</html>"""
    return HTMLResponse(body)


@app.get("/checkout/{purchase_id}")
def checkout_page(purchase_id: str):
    purchase = _clean_text(purchase_id)
    purchase_safe = html.escape(purchase)
    purchase_json = json.dumps(purchase)
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

    body = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Maestro Solo Checkout (Dev)</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; line-height: 1.5; }}
      .card {{ max-width: 680px; padding: 1.2rem; border: 1px solid #ddd; border-radius: 8px; }}
      button {{ padding: 0.6rem 0.9rem; border-radius: 6px; border: 0; background: #0a5; color: white; cursor: pointer; }}
      code {{ background: #f5f5f5; padding: 0.2rem 0.4rem; border-radius: 4px; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2>Maestro Solo Checkout (Test Mode)</h2>
      <p>Purchase id: <code>{purchase_safe}</code></p>
      <p>This is a development checkout page. Click the button to simulate payment completion.</p>
      <button onclick="markPaid()">Mark Paid + Provision License</button>
      <pre id="out"></pre>
    </div>
    <script>
      const purchaseId = {purchase_json};
      async function markPaid() {{
        const res = await fetch('/v1/solo/dev/mark-paid', {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          body: JSON.stringify({{ purchase_id: purchaseId }})
        }});
        const data = await res.json();
        document.getElementById('out').textContent = JSON.stringify(data, null, 2);
      }}
    </script>
  </body>
</html>
"""
    return HTMLResponse(body)


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
