"""Persistent state helpers for Maestro Solo billing service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from maestro_engine.utils import load_json, save_json

from .state_store import load_service_state, save_service_state


_SERVICE_NAME = "billing"


def billing_state_path() -> Path:
    root = os.environ.get("MAESTRO_SOLO_HOME", "").strip()
    base = Path(root).expanduser().resolve() if root else (Path.home() / ".maestro-solo").resolve()
    return base / "billing-service.json"


def billing_state_default() -> dict[str, Any]:
    return {"purchases": {}, "processed_events": {}, "auth_cli_sessions": {}}


def load_billing_state() -> dict[str, Any]:
    payload = load_service_state(_SERVICE_NAME, billing_state_default())
    if payload is None:
        payload = load_json(billing_state_path(), default={})
    if not isinstance(payload, dict):
        payload = {}
    purchases = payload.get("purchases")
    if not isinstance(purchases, dict):
        purchases = {}
    processed_events = payload.get("processed_events")
    if not isinstance(processed_events, dict):
        processed_events = {}
    auth_cli_sessions = payload.get("auth_cli_sessions")
    if not isinstance(auth_cli_sessions, dict):
        auth_cli_sessions = {}
    return {"purchases": purchases, "processed_events": processed_events, "auth_cli_sessions": auth_cli_sessions}


def save_billing_state(state: dict[str, Any]):
    if save_service_state(_SERVICE_NAME, state):
        return
    save_json(billing_state_path(), state)
