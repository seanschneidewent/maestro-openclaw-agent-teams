"""Schedule data helpers for workspace schedule APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .utils import load_json, save_json, slugify_underscore

MANAGED_SCHEDULE_FILE = "maestro_schedule.json"
SCHEDULE_ITEM_TYPES = {"activity", "milestone", "constraint", "inspection", "delivery", "task"}
SCHEDULE_ITEM_STATUSES = {"pending", "in_progress", "blocked", "done", "cancelled"}
CLOSED_SCHEDULE_ITEM_STATUSES = {"done", "cancelled"}


def _schedule_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _schedule_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _schedule_safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _schedule_safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_schedule_type(value: Any, default: str = "activity") -> str:
    raw = _schedule_text(value).lower().replace("-", "_").replace(" ", "_")
    return raw if raw in SCHEDULE_ITEM_TYPES else default


def _normalize_schedule_status(value: Any, default: str = "pending") -> str:
    raw = _schedule_text(value).lower().replace("-", "_").replace(" ", "_")
    return raw if raw in SCHEDULE_ITEM_STATUSES else default


def _schedule_variance_days(current_update: dict[str, Any]) -> int:
    activity_updates = current_update.get("activity_updates") if isinstance(current_update.get("activity_updates"), list) else []
    delays: list[int] = []
    for act in activity_updates:
        if not isinstance(act, dict):
            continue
        raw = act.get("variance_days")
        if raw is None:
            continue
        val = _schedule_safe_int(raw, 0)
        if val > 0:
            val = -val
        delays.append(val)
    return min(delays) if delays else 0


def _schedule_dir(proj: dict[str, Any]) -> Path:
    schedule_dir = Path(proj["path"]) / "schedule"
    schedule_dir.mkdir(parents=True, exist_ok=True)
    return schedule_dir


def _managed_schedule_path(proj: dict[str, Any]) -> Path:
    return _schedule_dir(proj) / MANAGED_SCHEDULE_FILE


def _load_managed_schedule(proj: dict[str, Any]) -> dict[str, Any]:
    payload = load_json(_managed_schedule_path(proj))
    if not isinstance(payload, dict):
        payload = {}
    items = payload.get("items")
    if not isinstance(items, list):
        items = []

    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = _schedule_text(item.get("id"))
        if not item_id:
            continue
        normalized_items.append({
            "id": item_id,
            "title": _schedule_text(item.get("title")),
            "type": _normalize_schedule_type(item.get("type")),
            "status": _normalize_schedule_status(item.get("status")),
            "due_date": _schedule_text(item.get("due_date")),
            "owner": _schedule_text(item.get("owner")),
            "activity_id": _schedule_text(item.get("activity_id")),
            "impact": _schedule_text(item.get("impact")),
            "notes": _schedule_text(item.get("notes")),
            "created_at": _schedule_text(item.get("created_at")),
            "updated_at": _schedule_text(item.get("updated_at")),
            "closed_at": _schedule_text(item.get("closed_at")),
            "close_reason": _schedule_text(item.get("close_reason")),
        })

    return {
        "version": _schedule_safe_int(payload.get("version"), 1),
        "updated_at": _schedule_text(payload.get("updated_at")),
        "items": normalized_items,
    }


def _save_managed_schedule(proj: dict[str, Any], payload: dict[str, Any]):
    save_json(_managed_schedule_path(proj), {
        "version": _schedule_safe_int(payload.get("version"), 1),
        "updated_at": _schedule_now_iso(),
        "items": payload.get("items", []),
    })


def _sort_schedule_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("due_date", "") or "9999-12-31"),
            str(item.get("updated_at", "") or ""),
            str(item.get("id", "") or ""),
        ),
    )


def schedule_status_payload(proj: dict[str, Any]) -> dict[str, Any]:
    schedule_dir = _schedule_dir(proj)
    current_path = schedule_dir / "current_update.json"
    lookahead_path = schedule_dir / "lookahead.json"
    baseline_path = schedule_dir / "baseline.json"

    current_update = load_json(current_path)
    lookahead = load_json(lookahead_path)
    baseline = load_json(baseline_path)
    if not isinstance(current_update, dict):
        current_update = {}
    if not isinstance(lookahead, dict):
        lookahead = {}
    if not isinstance(baseline, dict):
        baseline = {}

    managed = _load_managed_schedule(proj)
    managed_items = managed.get("items", []) if isinstance(managed.get("items"), list) else []
    status_counts = {status: 0 for status in sorted(SCHEDULE_ITEM_STATUSES)}
    for item in managed_items:
        if not isinstance(item, dict):
            continue
        status = _normalize_schedule_status(item.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    upcoming_critical = current_update.get("upcoming_critical_activities")
    if not isinstance(upcoming_critical, list):
        upcoming_critical = []
    constraints = lookahead.get("constraints")
    if not isinstance(constraints, list):
        constraints = []

    percent_complete = _schedule_safe_int(current_update.get("percent_complete"), 0)
    spi = _schedule_safe_float(current_update.get("schedule_performance_index"), 1.0)
    variance_days = _schedule_variance_days(current_update)
    blockers = sum(1 for item in managed_items if isinstance(item, dict) and item.get("status") == "blocked")
    summary = (
        f"{percent_complete}% complete · SPI {spi:.2f} · variance {variance_days}d · "
        f"managed blockers {blockers} · lookahead constraints {len(constraints)}"
    )

    return {
        "schedule_root": str(schedule_dir),
        "files": {
            "current_update": current_path.exists(),
            "lookahead": lookahead_path.exists(),
            "baseline": baseline_path.exists(),
            "managed_schedule": _managed_schedule_path(proj).exists(),
        },
        "current": {
            "data_date": _schedule_text(current_update.get("data_date")),
            "percent_complete": percent_complete,
            "schedule_performance_index": spi,
            "variance_days": variance_days,
            "weather_delays": _schedule_safe_int(current_update.get("weather_delays"), 0),
            "updated_substantial_completion": _schedule_text(current_update.get("updated_substantial_completion")),
            "updated_final_completion": _schedule_text(current_update.get("updated_final_completion")),
        },
        "lookahead": {
            "generated": _schedule_text(lookahead.get("generated")),
            "constraint_count": len(constraints),
            "upcoming_critical_count": len(upcoming_critical),
            "next_critical_ids": [
                _schedule_text(item.get("id"))
                for item in upcoming_critical
                if isinstance(item, dict) and _schedule_text(item.get("id"))
            ][:5],
        },
        "baseline": {
            "contract_duration_days": _schedule_safe_int(baseline.get("contract_duration_days"), 0),
            "substantial_completion": _schedule_text(baseline.get("substantial_completion")),
            "final_completion": _schedule_text(baseline.get("final_completion")),
        },
        "managed": {
            "updated_at": _schedule_text(managed.get("updated_at")),
            "item_count": len(managed_items),
            "status_counts": status_counts,
            "active_count": sum(
                1
                for item in managed_items
                if isinstance(item, dict) and _normalize_schedule_status(item.get("status")) not in CLOSED_SCHEDULE_ITEM_STATUSES
            ),
        },
        "summary": summary,
    }


def schedule_items_payload(proj: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    managed = _load_managed_schedule(proj)
    items = managed.get("items", []) if isinstance(managed.get("items"), list) else []
    target_status = None
    if status:
        target_status = _normalize_schedule_status(status, default="")
        if not target_status:
            valid = ", ".join(sorted(SCHEDULE_ITEM_STATUSES))
            raise ValueError(f"Invalid status '{status}'. Valid statuses: {valid}")
    filtered = [
        item for item in items
        if isinstance(item, dict) and (not target_status or _normalize_schedule_status(item.get("status")) == target_status)
    ]
    ordered = _sort_schedule_items(filtered)
    return {
        "items": ordered,
        "count": len(ordered),
        "updated_at": _schedule_text(managed.get("updated_at")),
    }


def upsert_schedule_item_for_project(proj: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    managed = _load_managed_schedule(proj)
    items = managed.get("items", []) if isinstance(managed.get("items"), list) else []
    item_id = slugify_underscore(_schedule_text(payload.get("item_id") or payload.get("id")))
    if not item_id:
        item_id = slugify_underscore(_schedule_text(payload.get("title")))
    if not item_id:
        raise ValueError("item_id or title is required.")

    existing = None
    for item in items:
        if isinstance(item, dict) and _schedule_text(item.get("id")) == item_id:
            existing = item
            break

    creating = existing is None
    if creating:
        title = _schedule_text(payload.get("title"))
        if not title:
            raise ValueError("title is required when creating a schedule item.")
        existing = {
            "id": item_id,
            "title": title,
            "type": "activity",
            "status": "pending",
            "due_date": "",
            "owner": "",
            "activity_id": "",
            "impact": "",
            "notes": "",
            "created_at": _schedule_now_iso(),
            "updated_at": _schedule_now_iso(),
            "closed_at": "",
            "close_reason": "",
        }
        items.append(existing)

    if "title" in payload:
        existing["title"] = _schedule_text(payload.get("title"))
    if "type" in payload or "item_type" in payload:
        raw_type = payload.get("type", payload.get("item_type"))
        existing["type"] = _normalize_schedule_type(raw_type, default=_normalize_schedule_type(existing.get("type"), "activity"))
    else:
        existing["type"] = _normalize_schedule_type(existing.get("type"), "activity")

    if "status" in payload:
        existing["status"] = _normalize_schedule_status(payload.get("status"), default=_normalize_schedule_status(existing.get("status"), "pending"))
    else:
        existing["status"] = _normalize_schedule_status(existing.get("status"), "pending")

    for key in ("due_date", "owner", "activity_id", "impact", "notes"):
        if key in payload:
            existing[key] = _schedule_text(payload.get(key))

    if existing.get("status") in CLOSED_SCHEDULE_ITEM_STATUSES:
        if not _schedule_text(existing.get("closed_at")):
            existing["closed_at"] = _schedule_now_iso()
    else:
        existing["closed_at"] = ""
        existing["close_reason"] = ""

    existing["updated_at"] = _schedule_now_iso()
    _save_managed_schedule(proj, {"version": managed.get("version", 1), "items": items})
    return (
        {
            "status": "created" if creating else "updated",
            "item": existing,
            "managed_item_count": len([item for item in items if isinstance(item, dict)]),
        },
        creating,
    )


def close_schedule_item_for_project(
    proj: dict[str, Any],
    item_id: str,
    *,
    reason: str | None = None,
    status: str = "done",
) -> dict[str, Any]:
    normalized_id = slugify_underscore(_schedule_text(item_id))
    if not normalized_id:
        raise ValueError("item_id is required.")

    normalized_status = _normalize_schedule_status(status, default="")
    if normalized_status not in CLOSED_SCHEDULE_ITEM_STATUSES:
        raise ValueError("close status must be one of: done, cancelled.")

    managed = _load_managed_schedule(proj)
    items = managed.get("items", []) if isinstance(managed.get("items"), list) else []
    target = None
    for item in items:
        if isinstance(item, dict) and _schedule_text(item.get("id")) == normalized_id:
            target = item
            break

    if not isinstance(target, dict):
        raise KeyError(normalized_id)

    target["status"] = normalized_status
    target["close_reason"] = _schedule_text(reason)
    target["closed_at"] = _schedule_now_iso()
    target["updated_at"] = _schedule_now_iso()
    _save_managed_schedule(proj, {"version": managed.get("version", 1), "items": items})
    return {
        "status": "closed",
        "item": target,
    }
