"""Command Center aggregation logic.

The Commander consumes normalized project snapshots from project stores.
This module is intentionally side-effect free and filesystem-read only.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .system_directives import list_active_directive_feed
from .utils import load_json, slugify


RELEVANT_DATE_KEYS = (
    "generated",
    "updated_at",
    "last_updated",
    "data_date",
    "ingested_at",
    "baseline_date",
)

HEARTBEAT_FRESH_SECONDS = 120


def _clean_str(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _to_str_list(value: Any, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _clean_str(item if isinstance(item, str) else str(item))
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _parse_dt(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None

    # Common variants we emit/ingest in this codebase.
    for candidate in (v, v.replace("Z", "+00:00"), f"{v}T00:00:00"):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _latest_timestamp(values: list[str]) -> str:
    parsed: list[tuple[datetime, str]] = []
    for raw in values:
        dt = _parse_dt(raw)
        if dt:
            parsed.append((dt, raw))
    if not parsed:
        return ""
    parsed.sort(key=lambda t: t[0])
    return parsed[-1][1]


def _status_is_open(status: Any) -> bool:
    if not isinstance(status, str):
        return False
    return "open" in status.lower() or "pending" in status.lower()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_ref_id(text: str) -> str | None:
    if not isinstance(text, str):
        return None

    match = re.search(r"RFI\s*#?\s*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"RFI-{int(match.group(1)):03d}"

    match = re.search(r"(?:SUBMITTAL|SUB)\s*#?\s*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"SUB-{int(match.group(1)):03d}"

    match = re.search(r"SUB-(\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"SUB-{int(match.group(1)):03d}"

    return None


def _project_name(project_dir: Path, project_data: dict[str, Any]) -> str:
    name = project_data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return project_dir.name


def _project_slug(project_dir: Path, project_data: dict[str, Any]) -> str:
    explicit = project_data.get("slug")
    if isinstance(explicit, str) and explicit.strip():
        return slugify(explicit)
    return slugify(_project_name(project_dir, project_data))


def _collect_timestamps(*records: dict[str, Any]) -> str:
    values: list[str] = []
    for record in records:
        for key in RELEVANT_DATE_KEYS:
            raw = record.get(key)
            if isinstance(raw, str) and raw.strip():
                values.append(raw.strip())
    return _latest_timestamp(values)


def discover_project_dirs(store_root: Path) -> list[Path]:
    """Discover project roots from a store root.

    Supports:
    1) Multi-project store: <root>/<project>/project.json
    2) Single-project store: <root>/project.json
    """
    root = Path(store_root)
    if not root.exists() or not root.is_dir():
        return []

    if (root / "project.json").exists():
        return [root]

    projects: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir() and (child / "project.json").exists():
            projects.append(child)
    return projects


def _compute_rfi_metrics(rfis_log: dict[str, Any]) -> dict[str, int]:
    items = rfis_log.get("rfis") if isinstance(rfis_log.get("rfis"), list) else []
    summary = rfis_log.get("status_summary") if isinstance(rfis_log.get("status_summary"), dict) else {}

    open_items = [item for item in items if isinstance(item, dict) and _status_is_open(item.get("status"))]

    blocking_open = sum(1 for item in open_items if item.get("blocking_activity") is True)
    high_risk_open = sum(
        1
        for item in open_items
        if isinstance(item.get("risk_level"), str) and "high" in item.get("risk_level", "").lower()
    )
    oldest_open_days = max((_safe_int(item.get("days_outstanding"), 0) for item in open_items), default=0)

    open_summary = _safe_int(summary.get("open"), 0)
    open_count = open_summary if open_summary > 0 else len(open_items)

    return {
        "total": _safe_int(rfis_log.get("total_rfis"), len(items)),
        "open": open_count,
        "blocking_open": blocking_open,
        "high_risk_open": high_risk_open,
        "oldest_open_days": oldest_open_days,
    }


def _compute_submittal_metrics(submittals_log: dict[str, Any]) -> dict[str, int]:
    items = submittals_log.get("submittals") if isinstance(submittals_log.get("submittals"), list) else []
    summary = submittals_log.get("status_summary") if isinstance(submittals_log.get("status_summary"), dict) else {}

    pending_review = _safe_int(summary.get("pending_review"), 0)
    rejected = _safe_int(summary.get("rejected"), 0)

    if pending_review == 0:
        pending_review = sum(
            1
            for item in items
            if isinstance(item, dict) and isinstance(item.get("status"), str)
            and "pending" in item.get("status", "").lower()
        )

    if rejected == 0:
        rejected = sum(
            1
            for item in items
            if isinstance(item, dict) and isinstance(item.get("status"), str)
            and "reject" in item.get("status", "").lower()
        )

    high_risk = sum(
        1
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("risk_level"), str)
        and "high" in item.get("risk_level", "").lower()
        and _status_is_open(item.get("status"))
    )

    long_lead_pending = sum(
        1
        for item in items
        if isinstance(item, dict)
        and _safe_int(item.get("lead_time_weeks"), 0) >= 6
        and _status_is_open(item.get("status"))
    )

    return {
        "total": _safe_int(submittals_log.get("total_submittals"), len(items)),
        "pending_review": pending_review,
        "rejected": rejected,
        "high_risk": high_risk,
        "long_lead_pending": long_lead_pending,
    }


def _compute_decision_metrics(decisions_log: dict[str, Any]) -> dict[str, int]:
    summary = decisions_log.get("summary") if isinstance(decisions_log.get("summary"), dict) else {}
    decisions = decisions_log.get("decisions") if isinstance(decisions_log.get("decisions"), list) else []

    pending_cos = _safe_int(summary.get("pending_change_orders"), 0)
    if pending_cos == 0:
        pending_cos = sum(
            1
            for item in decisions
            if isinstance(item, dict)
            and isinstance(item.get("change_order_status"), str)
            and "pending" in item.get("change_order_status", "").lower()
        )

    exposure = _safe_int(summary.get("total_exposure"), 0)
    if exposure == 0:
        exposures = summary.get("exposure_risks") if isinstance(summary.get("exposure_risks"), list) else []
        exposure = sum(
            _safe_int(item.get("exposure_amount"), 0)
            for item in exposures if isinstance(item, dict)
        )

    return {
        "total": _safe_int(summary.get("total_decisions"), len(decisions)),
        "pending_change_orders": pending_cos,
        "total_exposure_usd": exposure,
    }


def _compute_scope_metrics(scope_matrix: dict[str, Any]) -> dict[str, int]:
    gaps = scope_matrix.get("identified_gaps") if isinstance(scope_matrix.get("identified_gaps"), list) else []
    overlaps = scope_matrix.get("identified_overlaps") if isinstance(scope_matrix.get("identified_overlaps"), list) else []
    return {
        "gaps": len(gaps),
        "overlaps": len(overlaps),
    }


def _derive_variance_days(current_update: dict[str, Any]) -> int:
    activity_updates = current_update.get("activity_updates") if isinstance(current_update.get("activity_updates"), list) else []
    delays: list[int] = []
    for act in activity_updates:
        if not isinstance(act, dict):
            continue
        raw = act.get("variance_days")
        if raw is None:
            continue
        val = _safe_int(raw, 0)
        # In source files positive means delayed; snapshot contract uses negative for behind.
        if val > 0:
            val = -val
        delays.append(val)

    return min(delays) if delays else 0


def _derive_top_blockers(
    current_update: dict[str, Any],
    lookahead: dict[str, Any],
    rfis_log: dict[str, Any],
    submittals_log: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []

    # 1) Blocking open RFIs first (highest signal).
    rfis = rfis_log.get("rfis") if isinstance(rfis_log.get("rfis"), list) else []
    for item in rfis:
        if not isinstance(item, dict):
            continue
        if not _status_is_open(item.get("status")):
            continue
        if item.get("blocking_activity"):
            rfi_id = item.get("id")
            if isinstance(rfi_id, str):
                blockers.append(rfi_id)

    # 2) High-risk/rejected/pending submittals.
    subs = submittals_log.get("submittals") if isinstance(submittals_log.get("submittals"), list) else []
    for item in subs:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).lower()
        is_hot = (
            "reject" in status
            or (
                "pending" in status
                and isinstance(item.get("risk_level"), str)
                and "high" in item.get("risk_level", "").lower()
            )
        )
        if is_hot:
            sid = item.get("id")
            if isinstance(sid, str):
                blockers.append(sid)

    # 3) Constraint textual extraction (RFI#/SUB# hints).
    constraints = lookahead.get("constraints") if isinstance(lookahead.get("constraints"), list) else []
    for constraint in constraints:
        if not isinstance(constraint, dict):
            continue
        text_parts = [
            str(constraint.get("description", "")),
            str(constraint.get("impact_if_delayed", "")),
        ]
        for text in text_parts:
            ref_id = _normalize_ref_id(text)
            if ref_id:
                blockers.append(ref_id)

    # 4) Upcoming critical blockers (fallback text).
    upcoming = current_update.get("upcoming_critical_activities") if isinstance(current_update.get("upcoming_critical_activities"), list) else []
    for activity in upcoming:
        if not isinstance(activity, dict):
            continue
        for entry in activity.get("blockers", []) if isinstance(activity.get("blockers"), list) else []:
            if isinstance(entry, str) and entry.strip():
                ref_id = _normalize_ref_id(entry)
                blockers.append(ref_id or entry.strip())

    deduped: list[str] = []
    for blocker in blockers:
        if blocker not in deduped:
            deduped.append(blocker)
    return deduped[:3]


def _heartbeat_overlay(project_dir: Path, agent_id: str, project_slug: str) -> dict[str, Any]:
    path = project_dir / ".command_center" / "heartbeat.json"
    payload = load_json(path)
    if not isinstance(payload, dict):
        payload = {}

    generated_at = _clean_str(payload.get("generated_at"))
    dt = _parse_dt(generated_at)
    age_seconds: int | None = None
    if dt:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_seconds = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
    is_fresh = bool(age_seconds is not None and age_seconds <= HEARTBEAT_FRESH_SECONDS)

    return {
        "available": bool(payload),
        "version": _safe_int(payload.get("version"), 0),
        "agent_id": _clean_str(payload.get("agent_id")) or agent_id,
        "project_slug": _clean_str(payload.get("project_slug")) or project_slug,
        "generated_at": generated_at,
        "age_seconds": age_seconds if age_seconds is not None else -1,
        "is_fresh": is_fresh,
        "loop_state": _clean_str(payload.get("loop_state")) or "idle",
        "summary": _clean_str(payload.get("summary")),
        "top_risks": _to_str_list(payload.get("top_risks"), limit=5),
        "next_actions": _to_str_list(payload.get("next_actions"), limit=5),
        "confidence": _safe_float(payload.get("confidence"), 0.0),
        "pending_questions": _safe_int(payload.get("pending_questions"), 0),
        "last_user_message_at": _clean_str(payload.get("last_user_message_at")),
        "last_agent_reply_at": _clean_str(payload.get("last_agent_reply_at")),
    }


def _computed_risks(snapshot: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    critical = snapshot.get("critical_path", {}) if isinstance(snapshot.get("critical_path"), dict) else {}
    blockers = critical.get("top_blockers", []) if isinstance(critical.get("top_blockers"), list) else []
    for blocker in blockers:
        if isinstance(blocker, str) and blocker.strip():
            risks.append(f"{blocker.strip()} blocking progress")
    if _safe_int(snapshot.get("rfis", {}).get("blocking_open"), 0) > 0:  # type: ignore[arg-type]
        risks.append("Blocking open RFIs")
    if _safe_int(snapshot.get("submittals", {}).get("rejected"), 0) > 0:  # type: ignore[arg-type]
        risks.append("Rejected submittals require resubmission")
    if _safe_int(snapshot.get("decisions", {}).get("pending_change_orders"), 0) > 0:  # type: ignore[arg-type]
        risks.append("Pending change orders awaiting decision")
    if _safe_int(snapshot.get("scope_risk", {}).get("gaps"), 0) > 0:  # type: ignore[arg-type]
        risks.append("Scope gap exposure detected")
    return risks[:5]


def _computed_next_actions(snapshot: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    critical = snapshot.get("critical_path", {}) if isinstance(snapshot.get("critical_path"), dict) else {}
    blockers = critical.get("top_blockers", []) if isinstance(critical.get("top_blockers"), list) else []
    if blockers:
        actions.append(f"Resolve blocker {blockers[0]}")
    if _safe_int(snapshot.get("rfis", {}).get("open"), 0) > 0:  # type: ignore[arg-type]
        actions.append("Review open RFIs and escalate blockers")
    if _safe_int(snapshot.get("submittals", {}).get("pending_review"), 0) > 0:  # type: ignore[arg-type]
        actions.append("Follow up on pending submittal reviews")
    if not actions:
        actions.append("Continue monitoring project telemetry")
    return actions[:5]


def _status_report(snapshot: dict[str, Any], heartbeat: dict[str, Any]) -> dict[str, Any]:
    health = snapshot.get("health", {}) if isinstance(snapshot.get("health"), dict) else {}
    critical = snapshot.get("critical_path", {}) if isinstance(snapshot.get("critical_path"), dict) else {}
    rfis = snapshot.get("rfis", {}) if isinstance(snapshot.get("rfis"), dict) else {}
    submittals = snapshot.get("submittals", {}) if isinstance(snapshot.get("submittals"), dict) else {}
    decisions = snapshot.get("decisions", {}) if isinstance(snapshot.get("decisions"), dict) else {}
    scope = snapshot.get("scope_risk", {}) if isinstance(snapshot.get("scope_risk"), dict) else {}

    computed_summary = (
        f"{_safe_int(health.get('percent_complete'), 0)}% complete · "
        f"SPI {_safe_float(health.get('schedule_performance_index'), 1.0):.2f} · "
        f"variance {_safe_int(health.get('variance_days'), 0)}d · "
        f"blockers {_safe_int(critical.get('blocker_count'), 0)}"
    )

    fresh_heartbeat = bool(heartbeat.get("is_fresh"))
    source = "heartbeat" if fresh_heartbeat else "computed"
    summary = _clean_str(heartbeat.get("summary")) if fresh_heartbeat else ""
    if not summary:
        source = "computed"
        summary = computed_summary

    top_risks = _to_str_list(heartbeat.get("top_risks"), limit=5) if source == "heartbeat" else []
    if not top_risks:
        top_risks = _computed_risks(snapshot)

    next_actions = _to_str_list(heartbeat.get("next_actions"), limit=5) if source == "heartbeat" else []
    if not next_actions:
        next_actions = _computed_next_actions(snapshot)

    return {
        "source": source,
        "stale": bool(heartbeat.get("available")) and not bool(heartbeat.get("is_fresh")),
        "summary": summary,
        "loop_state": (
            _clean_str(heartbeat.get("loop_state"))
            if source == "heartbeat"
            else _clean_str(snapshot.get("agent_status")) or "idle"
        ),
        "confidence": _safe_float(heartbeat.get("confidence"), 0.0) if source == "heartbeat" else 0.0,
        "pending_questions": _safe_int(heartbeat.get("pending_questions"), 0),
        "top_risks": top_risks,
        "next_actions": next_actions,
        "metrics": {
            "attention_score": _safe_int(snapshot.get("attention_score"), 0),
            "spi": _safe_float(health.get("schedule_performance_index"), 1.0),
            "variance_days": _safe_int(health.get("variance_days"), 0),
            "blocker_count": _safe_int(critical.get("blocker_count"), 0),
            "open_rfis": _safe_int(rfis.get("open"), 0),
            "rejected_submittals": _safe_int(submittals.get("rejected"), 0),
            "pending_change_orders": _safe_int(decisions.get("pending_change_orders"), 0),
            "scope_gaps": _safe_int(scope.get("gaps"), 0),
        },
    }


def compute_attention_score(snapshot: dict[str, Any]) -> int:
    """Compute a normalized attention score (0-100)."""
    score = 0

    health = snapshot.get("health", {}) if isinstance(snapshot.get("health"), dict) else {}
    rfis = snapshot.get("rfis", {}) if isinstance(snapshot.get("rfis"), dict) else {}
    submittals = snapshot.get("submittals", {}) if isinstance(snapshot.get("submittals"), dict) else {}
    decisions = snapshot.get("decisions", {}) if isinstance(snapshot.get("decisions"), dict) else {}
    scope = snapshot.get("scope_risk", {}) if isinstance(snapshot.get("scope_risk"), dict) else {}

    spi = _safe_float(health.get("schedule_performance_index"), 1.0)
    variance_days = _safe_int(health.get("variance_days"), 0)

    if spi < 1.0:
        score += 25
    if variance_days <= -3:
        score += 15
    if _safe_int(rfis.get("blocking_open"), 0) > 0:
        score += 20
    if _safe_int(submittals.get("rejected"), 0) > 0:
        score += 15
    if _safe_int(decisions.get("pending_change_orders"), 0) > 0:
        score += 10
    if _safe_int(scope.get("gaps"), 0) > 0:
        score += 10
    if _safe_int(health.get("weather_delays"), 0) > 0:
        score += 5

    return max(0, min(100, score))


def build_project_snapshot(project_dir: Path) -> dict[str, Any]:
    """Build a normalized project snapshot for Command Center fleet cards."""
    project_data = load_json(project_dir / "project.json")
    index_data = load_json(project_dir / "index.json")
    schedule_current = load_json(project_dir / "schedule" / "current_update.json")
    schedule_lookahead = load_json(project_dir / "schedule" / "lookahead.json")
    rfis_log = load_json(project_dir / "rfis" / "log.json")
    submittals_log = load_json(project_dir / "submittals" / "log.json")
    decisions_log = load_json(project_dir / "comms" / "decisions.json")
    scope_matrix = load_json(project_dir / "contracts" / "scope_matrix.json")

    name = _project_name(project_dir, project_data)
    slug = _project_slug(project_dir, project_data)

    total_pages = _safe_int(project_data.get("total_pages"), 0)
    if total_pages == 0 and isinstance(index_data, dict):
        total_pages = _safe_int(index_data.get("summary", {}).get("page_count"), 0)

    pointer_count = _safe_int(project_data.get("index_summary", {}).get("pointer_count"), 0)
    if pointer_count == 0 and isinstance(index_data, dict):
        pointer_count = _safe_int(index_data.get("summary", {}).get("pointer_count"), 0)

    health = {
        "percent_complete": _safe_int(schedule_current.get("percent_complete"), 0),
        "schedule_performance_index": _safe_float(schedule_current.get("schedule_performance_index"), 1.0),
        "variance_days": _derive_variance_days(schedule_current),
        "weather_delays": _safe_int(schedule_current.get("weather_delays"), 0),
    }

    top_blockers = _derive_top_blockers(schedule_current, schedule_lookahead, rfis_log, submittals_log)

    upcoming_critical = schedule_current.get("upcoming_critical_activities") if isinstance(
        schedule_current.get("upcoming_critical_activities"), list
    ) else []
    constraints = schedule_lookahead.get("constraints") if isinstance(schedule_lookahead.get("constraints"), list) else []
    blocker_count = len(top_blockers)
    if blocker_count == 0:
        blocker_count = sum(
            len(item.get("blockers", []))
            for item in upcoming_critical if isinstance(item, dict)
        )
    if blocker_count == 0:
        blocker_count = len(constraints)

    critical_path = {
        "critical_activity_count": len(schedule_current.get("critical_path_activities", []))
        if isinstance(schedule_current.get("critical_path_activities"), list)
        else 0,
        "upcoming_critical_count": len(upcoming_critical),
        "blocker_count": blocker_count,
        "top_blockers": top_blockers,
    }

    rfis = _compute_rfi_metrics(rfis_log)
    submittals = _compute_submittal_metrics(submittals_log)
    decisions = _compute_decision_metrics(decisions_log)
    scope_risk = _compute_scope_metrics(scope_matrix)

    last_updated = _collect_timestamps(
        project_data,
        schedule_current,
        schedule_lookahead,
        rfis_log,
        submittals_log,
        decisions_log,
        scope_matrix,
    )

    agent_id = f"maestro-project-{slug}"
    snapshot = {
        "slug": slug,
        "project_name": name,
        "name": name,
        "agent_id": agent_id,
        "node_display_name": name,
        "node_handle": "",
        "node_identity_source": "project",
        "status": "active" if total_pages > 0 else "setup",
        "last_updated": last_updated,
        "superintendent": "Unknown",
        "page_count": total_pages,
        "pointer_count": pointer_count,
        "health": health,
        "critical_path": critical_path,
        "rfis": rfis,
        "submittals": submittals,
        "decisions": decisions,
        "scope_risk": scope_risk,
        # Tactical UI support fields.
        "agent_status": "computing" if critical_path["blocker_count"] > 0 else "idle",
        "current_task": (
            f"Resolving blocker {critical_path['top_blockers'][0]}"
            if critical_path["top_blockers"]
            else "Monitoring project telemetry"
        ),
        "comms": (
            f"Attention score {compute_attention_score({'health': health, 'rfis': rfis, 'submittals': submittals, 'decisions': decisions, 'scope_risk': scope_risk})}"
        ),
    }
    snapshot["attention_score"] = compute_attention_score(snapshot)
    heartbeat = _heartbeat_overlay(project_dir, agent_id, slug)
    snapshot["heartbeat"] = heartbeat
    snapshot["status_report"] = _status_report(snapshot, heartbeat)
    snapshot["conversation_preview"] = {
        "last_message_at": "",
        "last_user_at": "",
        "last_assistant_at": "",
        "last_user_text": "",
        "last_assistant_text": "",
        "message_count": 0,
    }

    return snapshot


def _top_open_rfis(rfis_log: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    rfis = rfis_log.get("rfis") if isinstance(rfis_log.get("rfis"), list) else []
    open_items = [item for item in rfis if isinstance(item, dict) and _status_is_open(item.get("status"))]

    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        high = 1 if "high" in str(item.get("risk_level", "")).lower() else 0
        blocking = 1 if item.get("blocking_activity") else 0
        days = _safe_int(item.get("days_outstanding"), 0)
        return (high + blocking, days)

    open_items.sort(key=sort_key, reverse=True)
    return open_items[:limit]


def _top_submittals(submittals_log: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    submittals = submittals_log.get("submittals") if isinstance(submittals_log.get("submittals"), list) else []
    hot_items = []
    for item in submittals:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).lower()
        risk = str(item.get("risk_level", "")).lower()
        if "reject" in status or "pending" in status or "not submitted" in status:
            hot_items.append(item)
        elif "high" in risk:
            hot_items.append(item)

    def sort_key(item: dict[str, Any]) -> tuple[int, int, int]:
        rejected = 1 if "reject" in str(item.get("status", "")).lower() else 0
        high = 1 if "high" in str(item.get("risk_level", "")).lower() else 0
        lead = _safe_int(item.get("lead_time_weeks"), 0)
        return (rejected, high, lead)

    hot_items.sort(key=sort_key, reverse=True)
    return hot_items[:limit]


def build_project_detail(project_dir: Path) -> dict[str, Any]:
    """Build node-intelligence drawer payload for one project."""
    snapshot = build_project_snapshot(project_dir)

    schedule_baseline = load_json(project_dir / "schedule" / "baseline.json")
    schedule_current = load_json(project_dir / "schedule" / "current_update.json")
    schedule_lookahead = load_json(project_dir / "schedule" / "lookahead.json")
    rfis_log = load_json(project_dir / "rfis" / "log.json")
    submittals_log = load_json(project_dir / "submittals" / "log.json")
    decisions_log = load_json(project_dir / "comms" / "decisions.json")
    scope_matrix = load_json(project_dir / "contracts" / "scope_matrix.json")

    decisions_summary = decisions_log.get("summary") if isinstance(decisions_log.get("summary"), dict) else {}
    exposure_risks = decisions_summary.get("exposure_risks") if isinstance(decisions_summary.get("exposure_risks"), list) else []

    drawers = {
        "operational_health": {
            "contract_duration_days": _safe_int(schedule_baseline.get("contract_duration_days"), 0),
            "substantial_completion": schedule_current.get("updated_substantial_completion")
            or schedule_baseline.get("substantial_completion")
            or "",
            "final_completion": schedule_current.get("updated_final_completion")
            or schedule_baseline.get("final_completion")
            or "",
            "percent_complete": snapshot["health"]["percent_complete"],
            "schedule_performance_index": snapshot["health"]["schedule_performance_index"],
            "variance_days": snapshot["health"]["variance_days"],
            "variance_notes": schedule_current.get("variance_notes", ""),
            "weather_delays": snapshot["health"]["weather_delays"],
        },
        "critical_path": {
            "critical_activities": schedule_current.get("critical_path_activities", []),
            "upcoming_critical_activities": schedule_current.get("upcoming_critical_activities", []),
            "constraints": schedule_lookahead.get("constraints", []),
            "material_deliveries": schedule_lookahead.get("material_deliveries", []),
            "inspections_required": schedule_lookahead.get("inspections_required", []),
        },
        "rfi_submittal_control": {
            "rfi_metrics": snapshot["rfis"],
            "submittal_metrics": snapshot["submittals"],
            "top_open_rfis": _top_open_rfis(rfis_log),
            "top_submittals": _top_submittals(submittals_log),
        },
        "commercial_exposure": {
            "decision_metrics": snapshot["decisions"],
            "pending_change_orders": snapshot["decisions"].get("pending_change_orders", 0),
            "total_exposure_usd": snapshot["decisions"].get("total_exposure_usd", 0),
            "exposure_risks": exposure_risks,
            "decisions": decisions_log.get("decisions", []),
        },
        "scope_watchlist": {
            "metrics": snapshot["scope_risk"],
            "identified_gaps": scope_matrix.get("identified_gaps", []),
            "identified_overlaps": scope_matrix.get("identified_overlaps", []),
        },
    }

    return {
        "snapshot": snapshot,
        "drawers": drawers,
    }


def load_directives(store_root: Path) -> list[dict[str, Any]]:
    """Load active directive feed from normalized system directives."""
    return list_active_directive_feed(store_root)


def build_command_center_state(store_root: Path) -> dict[str, Any]:
    """Build fleet-level state for command center cards."""
    root = Path(store_root)
    projects: list[dict[str, Any]] = []

    for project_dir in discover_project_dirs(root):
        snapshot = build_project_snapshot(project_dir)
        projects.append(snapshot)

    projects.sort(key=lambda p: p.get("attention_score", 0), reverse=True)

    directives = load_directives(root)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    fleet_status = "online"
    if not projects:
        fleet_status = "idle"
    elif any((p.get("attention_score", 0) >= 60 for p in projects)):
        fleet_status = "elevated"

    return {
        "updated_at": now_iso,
        "store_root": str(root),
        "commander": {
            "name": "The Commander",
            "lastSeen": "Online (Telegram)",
        },
        "orchestrator": {
            "id": "CM-01",
            "name": "The Commander",
            "status": fleet_status.title(),
            "currentAction": (
                f"Monitoring {len(projects)} project node(s) for schedule/risk/commercial signals."
                if projects
                else "Awaiting project telemetry."
            ),
        },
        "directives": directives,
        "projects": projects,
    }
