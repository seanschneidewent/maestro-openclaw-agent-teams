"""Standalone license service for Solo key issuance and verification."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .entitlements import issue_entitlement_token, plan_tier
from .solo_license import issue_solo_license, verify_solo_license_key
from maestro_engine.utils import load_json, save_json


def _state_path() -> Path:
    root = os.environ.get("MAESTRO_SOLO_HOME", "").strip()
    base = Path(root).expanduser().resolve() if root else (Path.home() / ".maestro-solo").resolve()
    return base / "license-service.json"


def _load_state() -> dict[str, Any]:
    payload = load_json(_state_path(), default={})
    if not isinstance(payload, dict):
        payload = {}
    by_purchase = payload.get("licenses_by_purchase")
    if not isinstance(by_purchase, dict):
        by_purchase = {}
    return {"licenses_by_purchase": by_purchase}


def _save_state(state: dict[str, Any]):
    save_json(_state_path(), state)


def _require_internal_auth(authorization: str | None):
    expected = os.environ.get("MAESTRO_INTERNAL_TOKEN", "dev-internal-token").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="internal auth token is not configured")
    header = str(authorization or "").strip()
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header[len("Bearer "):].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid bearer token")


class IssueSoloRequest(BaseModel):
    purchase_id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)


class VerifySoloRequest(BaseModel):
    license_key: str = Field(..., min_length=8)


app = FastAPI(title="Maestro Solo License Service", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/licenses/solo/issue")
def issue_solo(
    request: IssueSoloRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _require_internal_auth(authorization)

    purchase_id = request.purchase_id.strip()
    if idempotency_key and idempotency_key.strip() and idempotency_key.strip() != purchase_id:
        raise HTTPException(status_code=400, detail="idempotency key must match purchase_id")

    state = _load_state()
    by_purchase = state["licenses_by_purchase"]
    existing = by_purchase.get(purchase_id)
    if isinstance(existing, dict):
        return existing

    issued = issue_solo_license(
        purchase_id=purchase_id,
        plan_id=request.plan_id,
        email=request.email,
    )
    entitlement = issue_entitlement_token(
        subject=purchase_id,
        tier=plan_tier(request.plan_id),
        plan_id=request.plan_id,
        email=request.email,
    )
    if bool(entitlement.get("ok")):
        issued["entitlement_token"] = str(entitlement.get("entitlement_token", ""))
    by_purchase[purchase_id] = issued
    _save_state(state)
    return issued


@app.post("/v1/licenses/solo/verify")
def verify_solo(request: VerifySoloRequest):
    status = verify_solo_license_key(request.license_key)
    if bool(status.get("valid")):
        return status
    return {
        "valid": False,
        "error": str(status.get("error", "invalid_license")),
        "sku": str(status.get("sku", "")),
        "plan_id": str(status.get("plan_id", "")),
        "purchase_id": str(status.get("purchase_id", "")),
        "email": str(status.get("email", "")),
        "issued_at": str(status.get("issued_at", "")),
        "expires_at": str(status.get("expires_at", "")),
    }


def main(argv: list[str] | None = None):
    default_port_raw = str(os.environ.get("PORT", "")).strip() or str(os.environ.get("MAESTRO_LICENSE_PORT", "")).strip() or "8082"
    try:
        default_port = int(default_port_raw)
    except ValueError:
        default_port = 8082
    default_host = str(os.environ.get("MAESTRO_LICENSE_HOST", "")).strip() or ("0.0.0.0" if str(os.environ.get("PORT", "")).strip() else "127.0.0.1")

    parser = argparse.ArgumentParser(prog="maestro-license-service")
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args(argv)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
