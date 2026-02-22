"""System Directive storage and normalization.

Directives are Commander grounding artifacts (SOPs, policy notes, alignment
rules) managed under the fleet store root.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .utils import load_json, save_json


DIRECTIVES_VERSION = 1
STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_ARCHIVED = "archived"
VALID_STATUSES = {STATUS_DRAFT, STATUS_ACTIVE, STATUS_SUPERSEDED, STATUS_ARCHIVED}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def directives_store_path(store_root: Path) -> Path:
    return Path(store_root).resolve() / ".command_center" / "system_directives.json"


def legacy_directives_path(store_root: Path) -> Path:
    return Path(store_root).resolve() / ".command_center" / "directives.json"


def _normalize_status(value: Any) -> str:
    raw = str(value).strip().lower() if isinstance(value, str) else ""
    return raw if raw in VALID_STATUSES else STATUS_ACTIVE


def _normalize_priority(value: Any) -> int:
    try:
        number = int(value)
    except Exception:
        number = 50
    return max(0, min(100, number))


def _normalize_scope(value: Any) -> str:
    if not isinstance(value, str):
        return "global"
    cleaned = value.strip()
    return cleaned or "global"


def _normalize_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            tags.append(text)
    return tags


def normalize_directive(raw: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    directive_id = str(raw.get("id", "")).strip() or f"DIR-{uuid4().hex[:8]}"
    title = str(raw.get("title", "")).strip() or directive_id
    body = str(raw.get("body", "")).strip()
    if not body:
        body = str(raw.get("command", "")).strip()
    status = _normalize_status(raw.get("status"))
    scope = _normalize_scope(raw.get("scope"))
    updated_at = str(raw.get("updated_at", "")).strip() or now
    created_at = str(raw.get("created_at", "")).strip() or updated_at
    version = max(1, int(raw.get("version", 1) or 1))
    return {
        "id": directive_id,
        "title": title,
        "body": body,
        "scope": scope,
        "priority": _normalize_priority(raw.get("priority")),
        "status": status,
        "tags": _normalize_tags(raw.get("tags")),
        "effective_at": str(raw.get("effective_at", "")).strip(),
        "created_at": created_at,
        "updated_at": updated_at,
        "updated_by": str(raw.get("updated_by", "")).strip() or "system",
        "version": version,
    }


def _normalize_doc(payload: dict[str, Any]) -> dict[str, Any]:
    directives_raw = payload.get("directives", []) if isinstance(payload.get("directives"), list) else []
    directives = [normalize_directive(item) for item in directives_raw if isinstance(item, dict)]
    return {
        "version": DIRECTIVES_VERSION,
        "updated_at": str(payload.get("updated_at", "")).strip() or _now_iso(),
        "directives": directives,
    }


def load_system_directives(store_root: Path) -> dict[str, Any]:
    path = directives_store_path(store_root)
    payload = load_json(path, default={})
    if isinstance(payload, dict) and isinstance(payload.get("directives"), list):
        return _normalize_doc(payload)

    # Legacy fallback: .command_center/directives.json
    legacy = load_json(legacy_directives_path(store_root), default={})
    if isinstance(legacy, list):
        items = legacy
    elif isinstance(legacy, dict):
        items = legacy.get("directives", []) if isinstance(legacy.get("directives"), list) else []
    else:
        items = []
    return _normalize_doc({"directives": items})


def save_system_directives(store_root: Path, doc: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_doc(doc)
    normalized["updated_at"] = _now_iso()
    save_json(directives_store_path(store_root), normalized)
    return normalized


def list_system_directives(
    store_root: Path,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    doc = load_system_directives(store_root)
    directives = doc.get("directives", []) if isinstance(doc.get("directives"), list) else []
    items = [item for item in directives if isinstance(item, dict)]
    if not include_archived:
        items = [item for item in items if str(item.get("status", "")).lower() != STATUS_ARCHIVED]
    return sorted(
        items,
        key=lambda item: (
            -int(item.get("priority", 0) or 0),
            str(item.get("updated_at", "")),
            str(item.get("id", "")),
        ),
    )


def list_active_directive_feed(store_root: Path) -> list[dict[str, Any]]:
    items = [
        item
        for item in list_system_directives(store_root, include_archived=False)
        if str(item.get("status", "")).lower() == STATUS_ACTIVE
    ]
    feed: list[dict[str, Any]] = []
    for item in items:
        feed.append({
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "command": item.get("body", ""),
            "status": item.get("status", STATUS_ACTIVE),
            "scope": item.get("scope", "global"),
            "priority": int(item.get("priority", 50) or 50),
            "timestamp": item.get("updated_at", ""),
        })
    return feed


def upsert_system_directive(
    store_root: Path,
    directive: dict[str, Any],
    *,
    updated_by: str = "system",
) -> dict[str, Any]:
    if not isinstance(directive, dict):
        raise ValueError("directive payload must be an object")

    doc = load_system_directives(store_root)
    directives = doc.get("directives", []) if isinstance(doc.get("directives"), list) else []
    normalized = normalize_directive({
        **directive,
        "updated_by": updated_by,
        "updated_at": _now_iso(),
    })
    target_id = str(normalized.get("id", "")).strip()

    replaced = False
    out: list[dict[str, Any]] = []
    for item in directives:
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")).strip() == target_id:
            merged = normalize_directive({
                **item,
                **normalized,
                "version": int(item.get("version", 1) or 1) + 1,
            })
            out.append(merged)
            normalized = merged
            replaced = True
        else:
            out.append(normalize_directive(item))
    if not replaced:
        out.append(normalized)

    saved = save_system_directives(store_root, {"directives": out})
    return {
        "ok": True,
        "directive": normalized,
        "created": not replaced,
        "updated": replaced,
        "count": len(saved.get("directives", [])),
    }


def archive_system_directive(
    store_root: Path,
    directive_id: str,
    *,
    updated_by: str = "system",
) -> dict[str, Any]:
    target = str(directive_id).strip()
    if not target:
        raise ValueError("directive_id is required")

    doc = load_system_directives(store_root)
    directives = doc.get("directives", []) if isinstance(doc.get("directives"), list) else []
    found = False
    archived: dict[str, Any] | None = None
    out: list[dict[str, Any]] = []

    for item in directives:
        if not isinstance(item, dict):
            continue
        current = normalize_directive(item)
        if str(current.get("id", "")).strip() == target:
            found = True
            current = normalize_directive({
                **current,
                "status": STATUS_ARCHIVED,
                "updated_by": updated_by,
                "updated_at": _now_iso(),
                "version": int(current.get("version", 1) or 1) + 1,
            })
            archived = current
        out.append(current)

    if not found:
        return {"ok": False, "error": f"Directive '{target}' not found"}

    save_system_directives(store_root, {"directives": out})
    return {"ok": True, "directive": archived}


def summarize_system_directives(store_root: Path) -> dict[str, Any]:
    directives = list_system_directives(store_root, include_archived=True)
    by_status: dict[str, int] = {
        STATUS_DRAFT: 0,
        STATUS_ACTIVE: 0,
        STATUS_SUPERSEDED: 0,
        STATUS_ARCHIVED: 0,
    }
    for item in directives:
        status = _normalize_status(item.get("status"))
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(directives),
        "active": by_status.get(STATUS_ACTIVE, 0),
        "draft": by_status.get(STATUS_DRAFT, 0),
        "superseded": by_status.get(STATUS_SUPERSEDED, 0),
        "archived": by_status.get(STATUS_ARCHIVED, 0),
    }
