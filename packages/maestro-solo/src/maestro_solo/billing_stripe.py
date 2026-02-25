"""Stripe API helpers for Maestro Solo billing service."""

from __future__ import annotations

from typing import Any

import httpx


STRIPE_CHECKOUT_SESSIONS_ENDPOINT = "https://api.stripe.com/v1/checkout/sessions"
STRIPE_BILLING_PORTAL_SESSIONS_ENDPOINT = "https://api.stripe.com/v1/billing_portal/sessions"
STRIPE_CUSTOMERS_ENDPOINT = "https://api.stripe.com/v1/customers"


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def create_checkout_session(
    *,
    stripe_secret_key: str,
    purchase_id: str,
    plan_id: str,
    mode: str,
    email: str,
    price_id: str,
    checkout_mode: str,
    success_url: str,
    cancel_url: str,
    timeout_seconds: int = 20,
) -> tuple[bool, dict[str, Any]]:
    secret = _clean_text(stripe_secret_key)
    if not secret:
        return False, {"error": "stripe_secret_key_missing"}
    if not _clean_text(price_id):
        return False, {"error": f"stripe_price_id_missing_for_plan:{_clean_text(plan_id)}"}

    payload = {
        "mode": _clean_text(checkout_mode) or "payment",
        "success_url": _clean_text(success_url),
        "cancel_url": _clean_text(cancel_url),
        "client_reference_id": _clean_text(purchase_id),
        "metadata[purchase_id]": _clean_text(purchase_id),
        "metadata[plan_id]": _clean_text(plan_id),
        "metadata[email]": _clean_text(email),
        "metadata[mode]": _clean_text(mode),
        "line_items[0][price]": _clean_text(price_id),
        "line_items[0][quantity]": "1",
    }
    headers = {
        "Authorization": f"Bearer {secret}",
        "Idempotency-Key": _clean_text(purchase_id),
    }
    try:
        response = httpx.post(
            STRIPE_CHECKOUT_SESSIONS_ENDPOINT,
            data=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
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


def create_billing_portal_session(
    *,
    stripe_secret_key: str,
    customer_id: str,
    return_url: str,
    idempotency_key: str,
    timeout_seconds: int = 20,
) -> tuple[bool, dict[str, Any]]:
    secret = _clean_text(stripe_secret_key)
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
        "Idempotency-Key": _clean_text(idempotency_key) or customer,
    }
    try:
        response = httpx.post(
            STRIPE_BILLING_PORTAL_SESSIONS_ENDPOINT,
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


def find_customer_by_email(
    *,
    stripe_secret_key: str,
    email: str,
    timeout_seconds: int = 20,
) -> tuple[bool, dict[str, Any]]:
    secret = _clean_text(stripe_secret_key)
    if not secret:
        return False, {"error": "stripe_secret_key_missing"}
    clean_email = _clean_text(email)
    if not clean_email:
        return False, {"error": "email_missing"}

    headers = {"Authorization": f"Bearer {secret}"}
    params = {
        "email": clean_email,
        "limit": "1",
    }
    try:
        response = httpx.get(
            STRIPE_CUSTOMERS_ENDPOINT,
            params=params,
            headers=headers,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return False, {"error": f"stripe_customer_lookup_unreachable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    if response.status_code >= 300:
        return False, {"error": f"stripe_customer_lookup_status_{response.status_code}", "detail": data}
    if not isinstance(data, dict):
        return False, {"error": "stripe_customer_lookup_invalid_response"}

    records = data.get("data")
    if not isinstance(records, list) or not records:
        return False, {"error": "stripe_customer_not_found"}
    customer = records[0]
    if not isinstance(customer, dict):
        return False, {"error": "stripe_customer_invalid_record"}
    customer_id = _clean_text(customer.get("id"))
    if not customer_id:
        return False, {"error": "stripe_customer_missing_id"}
    return True, customer
