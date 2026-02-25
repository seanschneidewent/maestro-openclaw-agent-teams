"""Workspace data helpers for workspace API routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import load_json, slugify_underscore


PROJECT_NOTES_FILE = "project_notes.json"
NOTE_COLORS = {"slate", "blue", "green", "amber", "red", "purple"}


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered in {"1", "true", "yes", "y", "on"}
    return False


def _normalize_note_color(value: Any) -> str:
    color = _text(value).lower()
    return color if color in NOTE_COLORS else "slate"


def _dedupe_source_pages(source_pages: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in source_pages:
        page_name = _text(item.get("page_name"))
        workspace_slug = _text(item.get("workspace_slug"))
        if not page_name:
            continue
        key = (page_name, workspace_slug)
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, str] = {"page_name": page_name}
        if workspace_slug:
            payload["workspace_slug"] = workspace_slug
        deduped.append(payload)
    return deduped


def _normalize_source_pages(raw_note: dict[str, Any]) -> list[dict[str, str]]:
    source_pages: list[dict[str, str]] = []
    raw_source_pages = raw_note.get("source_pages")
    if isinstance(raw_source_pages, list):
        for item in raw_source_pages:
            if isinstance(item, str):
                page_name = _text(item)
                if page_name:
                    source_pages.append({"page_name": page_name})
                continue
            if isinstance(item, dict):
                page_name = _text(item.get("page_name") or item.get("source_page") or item.get("name"))
                workspace_slug = _text(item.get("workspace_slug") or item.get("ws_slug") or item.get("workspace"))
                if page_name:
                    row: dict[str, str] = {"page_name": page_name}
                    if workspace_slug:
                        row["workspace_slug"] = workspace_slug
                    source_pages.append(row)

    legacy_source_page = _text(raw_note.get("source_page"))
    if legacy_source_page:
        row = {"page_name": legacy_source_page}
        legacy_workspace = _text(raw_note.get("workspace_slug"))
        if legacy_workspace:
            row["workspace_slug"] = legacy_workspace
        source_pages.append(row)

    return _dedupe_source_pages(source_pages)


def workspaces_dir(proj: dict[str, Any]) -> Path:
    ws_dir = Path(proj["path"]) / "workspaces"
    ws_dir.mkdir(parents=True, exist_ok=True)
    return ws_dir


def load_workspace(proj: dict[str, Any], ws_slug: str) -> dict[str, Any] | None:
    ws_path = workspaces_dir(proj) / ws_slug / "workspace.json"
    data = load_json(ws_path)
    return data if isinstance(data, dict) else None


def load_all_workspaces(proj: dict[str, Any]) -> list[dict[str, Any]]:
    ws_dir = workspaces_dir(proj)
    workspaces: list[dict[str, Any]] = []
    for d in sorted(ws_dir.iterdir(), key=lambda p: p.name.lower()) if ws_dir.exists() else []:
        if d.is_dir():
            ws = load_workspace(proj, d.name)
            if ws:
                workspaces.append(ws)
    return workspaces


def project_notes_dir(proj: dict[str, Any]) -> Path:
    notes_dir = Path(proj["path"]) / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    return notes_dir


def project_notes_path(proj: dict[str, Any]) -> Path:
    return project_notes_dir(proj) / PROJECT_NOTES_FILE


def load_project_notes(proj: dict[str, Any]) -> dict[str, Any]:
    raw = load_json(project_notes_path(proj))
    payload = raw if isinstance(raw, dict) else {}

    categories: list[dict[str, Any]] = []
    categories_by_id: dict[str, dict[str, Any]] = {}

    for idx, entry in enumerate(payload.get("categories", []) if isinstance(payload.get("categories"), list) else []):
        if not isinstance(entry, dict):
            continue
        category_id = slugify_underscore(_text(entry.get("id")) or _text(entry.get("name")), "category")
        if not category_id:
            continue
        category = {
            "id": category_id,
            "name": _text(entry.get("name")) or category_id.replace("_", " ").title(),
            "color": _normalize_note_color(entry.get("color")),
            "order": int(entry.get("order")) if isinstance(entry.get("order"), int) else idx * 10,
            "created_at": _text(entry.get("created_at")),
            "updated_at": _text(entry.get("updated_at")),
        }
        categories_by_id[category_id] = category
        categories.append(category)

    if "general" not in categories_by_id:
        general = {
            "id": "general",
            "name": "General",
            "color": "slate",
            "order": 0,
            "created_at": "",
            "updated_at": "",
        }
        categories.insert(0, general)
        categories_by_id["general"] = general

    notes: list[dict[str, Any]] = []
    seen_note_ids: set[str] = set()
    raw_notes = payload.get("notes", []) if isinstance(payload.get("notes"), list) else []
    for idx, entry in enumerate(raw_notes):
        if not isinstance(entry, dict):
            continue
        text = _text(entry.get("text"))
        if not text:
            continue
        note_id = slugify_underscore(_text(entry.get("id") or entry.get("note_id")), "")
        if not note_id:
            note_id = f"note_{idx + 1}"
        if note_id in seen_note_ids:
            note_id = f"{note_id}_{idx + 1}"
        seen_note_ids.add(note_id)

        category_id = slugify_underscore(_text(entry.get("category_id") or entry.get("category")), "general")
        if category_id not in categories_by_id:
            categories_by_id[category_id] = {
                "id": category_id,
                "name": _text(entry.get("category_name")) or category_id.replace("_", " ").title(),
                "color": _normalize_note_color(entry.get("category_color") or entry.get("color")),
                "order": len(categories_by_id) * 10,
                "created_at": "",
                "updated_at": "",
            }
            categories.append(categories_by_id[category_id])

        source_pages = _normalize_source_pages(entry)
        legacy_source_page = source_pages[0]["page_name"] if source_pages else ""
        status = _text(entry.get("status")).lower() or "open"
        if status not in {"open", "archived"}:
            status = "open"

        notes.append(
            {
                "id": note_id,
                "text": text,
                "category_id": category_id,
                "source_pages": source_pages,
                "source_page": legacy_source_page,
                "pinned": _bool(entry.get("pinned")),
                "status": status,
                "created_at": _text(entry.get("created_at")),
                "updated_at": _text(entry.get("updated_at")),
            }
        )

    categories.sort(key=lambda c: (int(c.get("order", 0)), _text(c.get("name")).lower()))

    return {
        "version": int(payload.get("version")) if isinstance(payload.get("version"), int) else 1,
        "updated_at": _text(payload.get("updated_at")),
        "categories": categories,
        "notes": notes,
    }


def save_project_notes(proj: dict[str, Any], payload: dict[str, Any]) -> None:
    categories = payload.get("categories", []) if isinstance(payload.get("categories"), list) else []
    notes = payload.get("notes", []) if isinstance(payload.get("notes"), list) else []
    out_categories: list[dict[str, Any]] = []
    seen_category_ids: set[str] = set()
    for idx, entry in enumerate(categories):
        if not isinstance(entry, dict):
            continue
        category_id = slugify_underscore(_text(entry.get("id")) or _text(entry.get("name")), "category")
        if category_id in seen_category_ids:
            continue
        seen_category_ids.add(category_id)
        out_categories.append(
            {
                "id": category_id,
                "name": _text(entry.get("name")) or category_id.replace("_", " ").title(),
                "color": _normalize_note_color(entry.get("color")),
                "order": int(entry.get("order")) if isinstance(entry.get("order"), int) else idx * 10,
                "created_at": _text(entry.get("created_at")),
                "updated_at": _text(entry.get("updated_at")),
            }
        )
    if "general" not in seen_category_ids:
        out_categories.insert(
            0,
            {"id": "general", "name": "General", "color": "slate", "order": 0, "created_at": "", "updated_at": ""},
        )

    out_notes: list[dict[str, Any]] = []
    seen_note_ids: set[str] = set()
    for idx, entry in enumerate(notes):
        if not isinstance(entry, dict):
            continue
        text = _text(entry.get("text"))
        if not text:
            continue
        note_id = slugify_underscore(_text(entry.get("id") or entry.get("note_id")), "")
        if not note_id:
            note_id = f"note_{idx + 1}"
        if note_id in seen_note_ids:
            note_id = f"{note_id}_{idx + 1}"
        seen_note_ids.add(note_id)

        category_id = slugify_underscore(_text(entry.get("category_id") or entry.get("category")), "general")
        source_pages = _normalize_source_pages(entry)
        status = _text(entry.get("status")).lower() or "open"
        if status not in {"open", "archived"}:
            status = "open"
        out_notes.append(
            {
                "id": note_id,
                "text": text,
                "category_id": category_id,
                "source_pages": source_pages,
                "source_page": source_pages[0]["page_name"] if source_pages else "",
                "pinned": _bool(entry.get("pinned")),
                "status": status,
                "created_at": _text(entry.get("created_at")),
                "updated_at": _text(entry.get("updated_at")),
            }
        )

    project_notes_path(proj).write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": _text(payload.get("updated_at")),
                "categories": out_categories,
                "notes": out_notes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def get_page_bboxes(proj: dict[str, Any], page_name: str, pointer_ids: list[str]) -> list[dict[str, Any]]:
    page = proj.get("pages", {}).get(page_name, {})
    regions = page.get("regions", [])
    bboxes: list[dict[str, Any]] = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        if region.get("id") in pointer_ids:
            bboxes.append(
                {
                    "id": region["id"],
                    "label": region.get("label", ""),
                    "type": region.get("type", ""),
                    "bbox": region.get("bbox", {}),
                }
            )
    return bboxes
