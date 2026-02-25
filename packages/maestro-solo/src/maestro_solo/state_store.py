"""Shared persistent state helpers for Maestro Solo services."""

from __future__ import annotations

import json
import os
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_TABLE_NAME = "maestro_service_state"


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _database_url() -> str:
    return _clean_text(os.environ.get("MAESTRO_DATABASE_URL"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_copy(default_state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(default_state)


def _normalize_loaded_state(raw_state: Any, default_state: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_state, dict):
        return raw_state
    if isinstance(raw_state, str):
        try:
            parsed = json.loads(raw_state)
        except Exception:
            return _default_copy(default_state)
        if isinstance(parsed, dict):
            return parsed
    return _default_copy(default_state)


def _sqlite_path(database_url: str) -> str:
    raw_path = database_url[len("sqlite:///"):]
    if not raw_path:
        raise RuntimeError("MAESTRO_DATABASE_URL sqlite path is empty")
    if raw_path == ":memory:":
        return raw_path
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _ensure_sqlite_schema(conn: sqlite3.Connection):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
          service_name TEXT PRIMARY KEY,
          state_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_sqlite_state(database_url: str, service_name: str, default_state: dict[str, Any]) -> dict[str, Any]:
    path = _sqlite_path(database_url)
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        _ensure_sqlite_schema(conn)
        row = conn.execute(
            f"SELECT state_json FROM {_TABLE_NAME} WHERE service_name = ?",
            (service_name,),
        ).fetchone()
        if row is None:
            return _default_copy(default_state)
        return _normalize_loaded_state(row["state_json"], default_state)
    finally:
        conn.close()


def _save_sqlite_state(database_url: str, service_name: str, state: dict[str, Any]):
    path = _sqlite_path(database_url)
    payload = json.dumps(state, separators=(",", ":"), sort_keys=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        _ensure_sqlite_schema(conn)
        conn.execute(
            f"""
            INSERT INTO {_TABLE_NAME} (service_name, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(service_name) DO UPDATE SET
              state_json = excluded.state_json,
              updated_at = excluded.updated_at
            """,
            (service_name, payload, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_postgres_schema(conn: Any):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
              service_name TEXT PRIMARY KEY,
              state_json JSONB NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
    conn.commit()


def _load_postgres_state(database_url: str, service_name: str, default_state: dict[str, Any]) -> dict[str, Any]:
    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError("psycopg is required for PostgreSQL MAESTRO_DATABASE_URL") from exc

    with psycopg.connect(database_url) as conn:
        _ensure_postgres_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT state_json FROM {_TABLE_NAME} WHERE service_name = %s",
                (service_name,),
            )
            row = cur.fetchone()
            if row is None:
                return _default_copy(default_state)
            return _normalize_loaded_state(row[0], default_state)


def _save_postgres_state(database_url: str, service_name: str, state: dict[str, Any]):
    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError("psycopg is required for PostgreSQL MAESTRO_DATABASE_URL") from exc

    payload = json.dumps(state, separators=(",", ":"), sort_keys=True)
    with psycopg.connect(database_url) as conn:
        _ensure_postgres_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_TABLE_NAME} (service_name, state_json, updated_at)
                VALUES (%s, %s::jsonb, %s::timestamptz)
                ON CONFLICT(service_name) DO UPDATE SET
                  state_json = excluded.state_json,
                  updated_at = excluded.updated_at
                """,
                (service_name, payload, _now_iso()),
            )


def load_service_state(service_name: str, default_state: dict[str, Any]) -> dict[str, Any] | None:
    """Load per-service state from DB; returns None when DB is not configured."""
    database_url = _database_url()
    if not database_url:
        return None

    if database_url.startswith("sqlite:///"):
        return _load_sqlite_state(database_url, service_name, default_state)
    if database_url.startswith("postgres://") or database_url.startswith("postgresql://"):
        return _load_postgres_state(database_url, service_name, default_state)

    raise RuntimeError(
        "Unsupported MAESTRO_DATABASE_URL scheme. Use sqlite:///... or postgresql://..."
    )


def save_service_state(service_name: str, state: dict[str, Any]) -> bool:
    """Save per-service state into DB; returns False when DB is not configured."""
    database_url = _database_url()
    if not database_url:
        return False

    if database_url.startswith("sqlite:///"):
        _save_sqlite_state(database_url, service_name, state)
        return True
    if database_url.startswith("postgres://") or database_url.startswith("postgresql://"):
        _save_postgres_state(database_url, service_name, state)
        return True

    raise RuntimeError(
        "Unsupported MAESTRO_DATABASE_URL scheme. Use sqlite:///... or postgresql://..."
    )
