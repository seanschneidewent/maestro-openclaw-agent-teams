"""Standalone billing service for Solo purchase state + license provisioning."""

from __future__ import annotations

import argparse
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from maestro_engine.utils import load_json, save_json


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state_path() -> Path:
    root = os.environ.get("MAESTRO_SOLO_HOME", "").strip()
    base = Path(root).expanduser().resolve() if root else (Path.home() / ".maestro-solo").resolve()
    return base / "billing-service.json"


def _load_state() -> dict[str, Any]:
    payload = load_json(_state_path(), default={})
    if not isinstance(payload, dict):
        payload = {}
    purchases = payload.get("purchases")
    if not isinstance(purchases, dict):
        purchases = {}
    return {"purchases": purchases}


def _save_state(state: dict[str, Any]):
    save_json(_state_path(), state)


def _purchase_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"pur_{stamp}{secrets.token_hex(4)}"


def _purchase_response(purchase: dict[str, Any]) -> dict[str, Any]:
    return {
        "purchase_id": str(purchase.get("purchase_id", "")),
        "status": str(purchase.get("status", "pending")),
        "plan_id": str(purchase.get("plan_id", "")),
        "email": str(purchase.get("email", "")),
        "license_key": purchase.get("license_key"),
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

    license_key = str(data.get("license_key", "")).strip() if isinstance(data, dict) else ""
    if not license_key:
        return False, {"error": "license_service_missing_key", "detail": data}
    return True, data if isinstance(data, dict) else {"license_key": license_key}


class CreatePurchaseRequest(BaseModel):
    email: str = Field(..., min_length=3)
    plan_id: str = Field(..., min_length=1)
    mode: str = Field(default="test")
    success_url: str | None = None
    cancel_url: str | None = None


class MarkPaidRequest(BaseModel):
    purchase_id: str = Field(..., min_length=1)


app = FastAPI(title="Maestro Solo Billing Service", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/solo/purchases")
def create_purchase(request: CreatePurchaseRequest, raw_request: Request):
    purchase_id = _purchase_id()
    base = str(raw_request.base_url).rstrip("/")
    checkout_url = f"{base}/checkout/{purchase_id}"
    purchase = {
        "purchase_id": purchase_id,
        "status": "pending",
        "plan_id": request.plan_id.strip(),
        "email": request.email.strip(),
        "mode": request.mode.strip() or "test",
        "success_url": request.success_url or "",
        "cancel_url": request.cancel_url or "",
        "checkout_url": checkout_url,
        "license_key": None,
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    state = _load_state()
    state["purchases"][purchase_id] = purchase
    _save_state(state)
    return {
        "purchase_id": purchase_id,
        "status": "pending",
        "checkout_url": checkout_url,
        "poll_after_ms": 3000,
    }


@app.get("/v1/solo/purchases/{purchase_id}")
def get_purchase(purchase_id: str):
    state = _load_state()
    purchase = state["purchases"].get(str(purchase_id).strip())
    if not isinstance(purchase, dict):
        raise HTTPException(status_code=404, detail="purchase not found")
    return _purchase_response(purchase)


@app.post("/v1/solo/dev/mark-paid")
def mark_paid(request: MarkPaidRequest):
    state = _load_state()
    purchase_id = request.purchase_id.strip()
    purchase = state["purchases"].get(purchase_id)
    if not isinstance(purchase, dict):
        raise HTTPException(status_code=404, detail="purchase not found")

    status = str(purchase.get("status", "pending")).strip()
    if status == "licensed":
        return {"ok": True, "status": "licensed"}
    if status == "canceled":
        return {"ok": False, "status": "canceled"}

    purchase["status"] = "paid"
    purchase["updated_at"] = _now_iso()
    purchase["error"] = None
    _save_state(state)

    ok, issued = _issue_license_for_purchase(purchase)
    if ok:
        purchase["status"] = "licensed"
        purchase["license_key"] = str(issued.get("license_key", ""))
        purchase["error"] = None
    else:
        purchase["status"] = "failed"
        purchase["error"] = str(issued.get("error", "license_issue_failed"))
    purchase["updated_at"] = _now_iso()
    state["purchases"][purchase_id] = purchase
    _save_state(state)
    return {"ok": purchase["status"] == "licensed", "status": purchase["status"]}


@app.get("/checkout/{purchase_id}")
def checkout_page(purchase_id: str):
    purchase = str(purchase_id).strip()
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
      <p>Purchase id: <code>{purchase}</code></p>
      <p>This is a development checkout page. Click the button to simulate payment completion.</p>
      <button onclick="markPaid()">Mark Paid + Provision License</button>
      <pre id="out"></pre>
    </div>
    <script>
      async function markPaid() {{
        const res = await fetch('/v1/solo/dev/mark-paid', {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          body: JSON.stringify({{ purchase_id: '{purchase}' }})
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
    parser = argparse.ArgumentParser(prog="maestro-billing-service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args(argv)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
