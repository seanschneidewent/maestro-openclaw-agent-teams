"""
Maestro Knowledge Tools — query engine for ingested construction plans.

Provides search, sheet summaries, region details, cross-references,
workspace management, Gemini highlighting, and image generation.

Usage (CLI):
    maestro tools <command> [args]

Usage (Python):
    from maestro.tools import MaestroTools
    tools = MaestroTools(store_path="knowledge_store")
    results = tools.search("waterproofing")
"""

from __future__ import annotations

import functools
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_role import is_company_role
from .config import (
    HIGHLIGHT_MODEL,
    IMAGE_GEN_MODEL,
    get_store_path,
    load_dotenv,
)
from .license import LicenseError, validate_project_key, verify_knowledge_store
from .loader import load_project, resolve_page
from .prompts import HIGHLIGHT_PROMPT
from .utils import (
    collect_text_only,
    load_json,
    normalize_bbox,
    parse_json_list,
    save_json,
    slugify_underscore,
)


# ── Schedule Constants ───────────────────────────────────────────────────────

MANAGED_SCHEDULE_FILE = "maestro_schedule.json"
SCHEDULE_ITEM_TYPES = {"activity", "milestone", "constraint", "inspection", "delivery", "task"}
SCHEDULE_ITEM_STATUSES = {"pending", "in_progress", "blocked", "done", "cancelled"}
CLOSED_SCHEDULE_ITEM_STATUSES = {"done", "cancelled"}


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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _derive_schedule_variance_days(current_update: dict[str, Any]) -> int:
    activity_updates = current_update.get("activity_updates") if isinstance(current_update.get("activity_updates"), list) else []
    delays: list[int] = []
    for act in activity_updates:
        if not isinstance(act, dict):
            continue
        raw = act.get("variance_days")
        if raw is None:
            continue
        val = _safe_int(raw, 0)
        # Source schedule files often use positive days as delayed.
        if val > 0:
            val = -val
        delays.append(val)
    return min(delays) if delays else 0


# ── License Enforcement ───────────────────────────────────────────────────────

def requires_license(func):
    """
    Decorator to enforce project license on tool methods.
    
    Checks self.licensed flag before executing.
    If not licensed, returns an error message instead of executing the tool.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not getattr(self, "licensed", False):
            return (
                f"[X] License required to use {func.__name__}.\n"
                f"Set MAESTRO_LICENSE_KEY environment variable with a valid project license.\n"
                f"Generate a test key with: maestro license generate-project"
            )
        return func(self, *args, **kwargs)
    return wrapper


class MaestroTools:
    """
    Stateful tool interface for querying a Maestro knowledge store.

    Loads a project once and provides all query/workspace/highlight methods.
    
    License enforcement: validates MAESTRO_LICENSE_KEY on init.
    """

    def __init__(
        self,
        store_path: str | Path | None = None,
        project_name: str | None = None,
        workspace_root: Path | None = None,
        skip_license_check: bool = False,
    ):
        self._store_path = Path(store_path) if store_path else get_store_path()
        self._project_name = project_name
        self._workspace_root = workspace_root
        self._project: dict[str, Any] | None = None
        self.licensed = False
        
        # Load environment variables
        if workspace_root:
            load_dotenv(workspace_root)
        else:
            load_dotenv()

        if is_company_role(workspace_root):
            raise RuntimeError(
                "Company Maestro is control-plane only. "
                "Project knowledge tools are disabled in this workspace."
            )

        # Validate license (unless explicitly skipped for testing)
        if not skip_license_check:
            self._validate_license()
    
    def _validate_license(self) -> None:
        """
        Validate project license from MAESTRO_LICENSE_KEY environment variable.
        
        Sets self.licensed = True if valid, False otherwise.
        Prints warning if license is invalid but doesn't raise.
        """
        license_key = os.environ.get("MAESTRO_LICENSE_KEY")
        
        if not license_key:
            print("[!] No MAESTRO_LICENSE_KEY found in environment")
            print("    Tools will be disabled. Set a valid project license to enable.")
            self.licensed = False
            return
        
        # We need project_slug to validate - derive from project metadata
        try:
            project = self.project
            project_slug = project.get("slug")
            if not project_slug:
                # Try to derive from project name
                project_name = project.get("name", "")
                from .utils import slugify_underscore
                project_slug = slugify_underscore(project_name)
            
            # Validate the license key
            validate_project_key(license_key, project_slug, str(self._store_path))
            
            # Verify knowledge store stamp matches
            verify_knowledge_store(str(self._store_path), license_key, project_slug)
            
            self.licensed = True
            
        except LicenseError as e:
            print(f"[X] License validation failed: {e}")
            print(f"    Tools will be disabled.")
            self.licensed = False
        except Exception as e:
            print(f"[!] Could not validate license: {e}")
            print(f"    Tools will be disabled.")
            self.licensed = False

    @property
    def project(self) -> dict[str, Any]:
        if self._project is None:
            self._project = load_project(
                store_path=self._store_path,
                project_name=self._project_name,
            )
            if self._project is None:
                raise RuntimeError("No project loaded. Run: maestro ingest <folder>")
        return self._project

    def _resolve_page(self, page_name: str) -> dict[str, Any] | None:
        return resolve_page(self.project, page_name)

    @staticmethod
    def _normalize_schedule_type(value: Any, default: str = "activity") -> str:
        raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return raw if raw in SCHEDULE_ITEM_TYPES else default

    @staticmethod
    def _normalize_schedule_status(value: Any, default: str = "pending") -> str:
        raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return raw if raw in SCHEDULE_ITEM_STATUSES else default

    @staticmethod
    def _text(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    def _project_dir(self) -> Path:
        project_path = self.project.get("_dir")
        if isinstance(project_path, str) and project_path.strip():
            return Path(project_path)
        return self._store_path / str(self.project.get("name", "default"))

    def _schedule_dir(self) -> Path:
        schedule_dir = self._project_dir() / "schedule"
        schedule_dir.mkdir(parents=True, exist_ok=True)
        return schedule_dir

    def _managed_schedule_path(self) -> Path:
        return self._schedule_dir() / MANAGED_SCHEDULE_FILE

    def _load_managed_schedule(self) -> dict[str, Any]:
        path = self._managed_schedule_path()
        payload = load_json(path)
        if not isinstance(payload, dict):
            payload = {}
        items = payload.get("items")
        if not isinstance(items, list):
            items = []

        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = slugify_underscore(self._text(item.get("id")))
            if not item_id:
                continue
            normalized_items.append({
                "id": item_id,
                "title": self._text(item.get("title")),
                "type": self._normalize_schedule_type(item.get("type")),
                "status": self._normalize_schedule_status(item.get("status")),
                "due_date": self._text(item.get("due_date")),
                "owner": self._text(item.get("owner")),
                "activity_id": self._text(item.get("activity_id")),
                "impact": self._text(item.get("impact")),
                "notes": self._text(item.get("notes")),
                "created_at": self._text(item.get("created_at")),
                "updated_at": self._text(item.get("updated_at")),
                "closed_at": self._text(item.get("closed_at")),
                "close_reason": self._text(item.get("close_reason")),
            })

        return {
            "version": _safe_int(payload.get("version"), 1),
            "updated_at": self._text(payload.get("updated_at")),
            "items": normalized_items,
        }

    def _save_managed_schedule(self, payload: dict[str, Any]):
        data = {
            "version": _safe_int(payload.get("version"), 1),
            "updated_at": _iso_now(),
            "items": payload.get("items", []),
        }
        save_json(self._managed_schedule_path(), data)

    @staticmethod
    def _sort_schedule_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def _key(item: dict[str, Any]) -> tuple[str, str, str]:
            return (
                str(item.get("due_date", "") or "9999-12-31"),
                str(item.get("updated_at", "") or ""),
                str(item.get("id", "") or ""),
            )

        return sorted(items, key=_key)

    def _build_schedule_summary(self, current_update: dict[str, Any], lookahead: dict[str, Any], managed_items: list[dict[str, Any]]) -> str:
        percent_complete = _safe_int(current_update.get("percent_complete"), 0)
        spi = _safe_float(current_update.get("schedule_performance_index"), 1.0)
        variance_days = _derive_schedule_variance_days(current_update)
        blockers = sum(1 for item in managed_items if item.get("status") == "blocked")
        constraints = len(lookahead.get("constraints", [])) if isinstance(lookahead.get("constraints"), list) else 0
        return (
            f"{percent_complete}% complete · SPI {spi:.2f} · variance {variance_days}d · "
            f"managed blockers {blockers} · lookahead constraints {constraints}"
        )

    # ── Knowledge Queries ─────────────────────────────────────────────────────

    @requires_license
    def list_disciplines(self) -> list[str]:
        return self.project.get("disciplines", [])

    @requires_license
    def list_pages(self, discipline: str | None = None) -> list[dict[str, Any]]:
        pages = []
        for name, page in self.project.get("pages", {}).items():
            page_disc = str(page.get("discipline", ""))
            if discipline and page_disc.lower() != discipline.lower():
                continue
            pages.append({
                "name": name,
                "type": page.get("page_type", "unknown"),
                "discipline": page_disc,
                "region_count": len(page.get("regions", [])),
            })
        return sorted(pages, key=lambda p: p["name"].lower())

    @requires_license
    def get_sheet_summary(self, page_name: str) -> str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found. Use list_pages to see available pages."
        return page.get("sheet_reflection", "No summary available")

    @requires_license
    def get_sheet_index(self, page_name: str) -> dict[str, Any] | str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        return page.get("index", {})

    @requires_license
    def list_regions(self, page_name: str) -> list[dict[str, Any]] | str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        pointers = page.get("pointers", {})
        return [{
            "id": r.get("id", ""),
            "type": r.get("type"),
            "label": r.get("label"),
            "detail_number": r.get("detail_number"),
            "has_pass2": bool(r.get("id") and r.get("id") in pointers),
        } for r in page.get("regions", []) if isinstance(r, dict)]

    @requires_license
    def get_region_detail(self, page_name: str, region_id: str) -> str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        pointer = page.get("pointers", {}).get(region_id)
        if not pointer:
            return f"Region '{region_id}' not found on '{page.get('name', page_name)}'."
        return pointer.get("content_markdown", "No detail available")

    @requires_license
    def search(self, query: str) -> list[dict[str, Any]] | str:
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        idx = self.project.get("index", {})

        if isinstance(idx, dict):
            for material, sources in idx.get("materials", {}).items():
                if query_lower in str(material).lower():
                    results.append({"type": "material", "match": material, "found_in": sources})
            for keyword, sources in idx.get("keywords", {}).items():
                if query_lower in str(keyword).lower():
                    results.append({"type": "keyword", "match": keyword, "found_in": sources})

        for page_name, page in self.project.get("pages", {}).items():
            if query_lower in str(page.get("sheet_reflection", "")).lower():
                results.append({"type": "page", "match": page_name, "context": "sheet_reflection"})
            for pointer_id, pointer in page.get("pointers", {}).items():
                if query_lower in str(pointer.get("content_markdown", "")).lower():
                    results.append({"type": "pointer", "match": f"{page_name}/{pointer_id}", "context": "content_markdown"})

        return results if results else f"No results for '{query}'"

    @requires_license
    def find_cross_references(self, page_name: str) -> dict[str, Any] | str:
        page = self.project.get("pages", {}).get(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        idx = self.project.get("index", {})
        cross_refs = idx.get("cross_refs", {}) if isinstance(idx, dict) else {}
        return {
            "references_from_this_page": page.get("cross_references", []),
            "pages_that_reference_this": cross_refs.get(page_name, []),
        }

    @requires_license
    def list_modifications(self) -> list[dict[str, Any]]:
        idx = self.project.get("index", {})
        return idx.get("modifications", []) if isinstance(idx, dict) else []

    @requires_license
    def check_gaps(self) -> list[dict[str, Any]] | str:
        gaps: list[dict[str, Any]] = []
        idx = self.project.get("index", {})
        if isinstance(idx, dict):
            for ref in idx.get("broken_refs", []):
                gaps.append({"type": "broken_ref", "detail": ref})
        for page_name, page in self.project.get("pages", {}).items():
            pointers = page.get("pointers", {})
            for region in page.get("regions", []):
                if not isinstance(region, dict):
                    continue
                rid = region.get("id", "")
                if rid and rid not in pointers:
                    gaps.append({
                        "type": "missing_pass2",
                        "page": page_name,
                        "region": rid,
                        "label": region.get("label", ""),
                    })
        return gaps if gaps else "No gaps found"

    # ── Schedule Management ───────────────────────────────────────────────────

    @requires_license
    def get_schedule_status(self) -> dict[str, Any]:
        schedule_dir = self._schedule_dir()
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

        managed = self._load_managed_schedule()
        managed_items = managed.get("items", []) if isinstance(managed.get("items"), list) else []
        status_counts = {status: 0 for status in sorted(SCHEDULE_ITEM_STATUSES)}
        for item in managed_items:
            if not isinstance(item, dict):
                continue
            status = self._normalize_schedule_status(item.get("status"))
            status_counts[status] = status_counts.get(status, 0) + 1

        upcoming_critical = current_update.get("upcoming_critical_activities")
        if not isinstance(upcoming_critical, list):
            upcoming_critical = []
        constraints = lookahead.get("constraints")
        if not isinstance(constraints, list):
            constraints = []

        return {
            "schedule_root": str(schedule_dir),
            "files": {
                "current_update": current_path.exists(),
                "lookahead": lookahead_path.exists(),
                "baseline": baseline_path.exists(),
                "managed_schedule": self._managed_schedule_path().exists(),
            },
            "current": {
                "data_date": self._text(current_update.get("data_date")),
                "percent_complete": _safe_int(current_update.get("percent_complete"), 0),
                "schedule_performance_index": _safe_float(current_update.get("schedule_performance_index"), 1.0),
                "variance_days": _derive_schedule_variance_days(current_update),
                "weather_delays": _safe_int(current_update.get("weather_delays"), 0),
                "updated_substantial_completion": self._text(current_update.get("updated_substantial_completion")),
                "updated_final_completion": self._text(current_update.get("updated_final_completion")),
            },
            "lookahead": {
                "generated": self._text(lookahead.get("generated")),
                "constraint_count": len(constraints),
                "upcoming_critical_count": len(upcoming_critical),
                "next_critical_ids": [
                    self._text(item.get("id"))
                    for item in upcoming_critical
                    if isinstance(item, dict) and self._text(item.get("id"))
                ][:5],
            },
            "baseline": {
                "contract_duration_days": _safe_int(baseline.get("contract_duration_days"), 0),
                "substantial_completion": self._text(baseline.get("substantial_completion")),
                "final_completion": self._text(baseline.get("final_completion")),
            },
            "managed": {
                "updated_at": self._text(managed.get("updated_at")),
                "item_count": len(managed_items),
                "status_counts": status_counts,
                "active_count": sum(
                    1 for item in managed_items
                    if isinstance(item, dict) and self._normalize_schedule_status(item.get("status")) not in CLOSED_SCHEDULE_ITEM_STATUSES
                ),
            },
            "summary": self._build_schedule_summary(current_update, lookahead, managed_items),
        }

    @requires_license
    def list_schedule_items(self, status: str | None = None) -> list[dict[str, Any]] | str:
        payload = self._load_managed_schedule()
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
        target_status = None
        if status is not None:
            normalized = self._normalize_schedule_status(status, default="")
            if not normalized:
                valid = ", ".join(sorted(SCHEDULE_ITEM_STATUSES))
                return f"Invalid status '{status}'. Valid statuses: {valid}."
            target_status = normalized
        if target_status:
            items = [
                item for item in items
                if isinstance(item, dict) and self._normalize_schedule_status(item.get("status")) == target_status
            ]
        return self._sort_schedule_items([item for item in items if isinstance(item, dict)])

    @requires_license
    def upsert_schedule_item(
        self,
        item_id: str | None = None,
        *,
        title: str | None = None,
        item_type: str | None = None,
        status: str | None = None,
        due_date: str | None = None,
        owner: str | None = None,
        activity_id: str | None = None,
        impact: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | str:
        payload = self._load_managed_schedule()
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []

        normalized_id = slugify_underscore(self._text(item_id))
        if not normalized_id:
            title_for_id = self._text(title)
            normalized_id = slugify_underscore(title_for_id)
        if not normalized_id:
            return "item_id or title is required to upsert a schedule item."

        existing = None
        for item in items:
            if isinstance(item, dict) and self._text(item.get("id")) == normalized_id:
                existing = item
                break

        creating = existing is None
        if creating:
            clean_title = self._text(title)
            if not clean_title:
                return "title is required when creating a schedule item."
            existing = {
                "id": normalized_id,
                "title": clean_title,
                "type": "activity",
                "status": "pending",
                "due_date": "",
                "owner": "",
                "activity_id": "",
                "impact": "",
                "notes": "",
                "created_at": _iso_now(),
                "updated_at": _iso_now(),
                "closed_at": "",
                "close_reason": "",
            }
            items.append(existing)

        if title is not None:
            existing["title"] = self._text(title)
        current_type = self._normalize_schedule_type(existing.get("type"), default="activity")
        if item_type is not None:
            existing["type"] = self._normalize_schedule_type(item_type, default=current_type)
        else:
            existing["type"] = current_type

        current_status = self._normalize_schedule_status(existing.get("status"), default="pending")
        if status is not None:
            existing["status"] = self._normalize_schedule_status(status, default=current_status)
        else:
            existing["status"] = current_status

        if due_date is not None:
            existing["due_date"] = self._text(due_date)
        if owner is not None:
            existing["owner"] = self._text(owner)
        if activity_id is not None:
            existing["activity_id"] = self._text(activity_id)
        if impact is not None:
            existing["impact"] = self._text(impact)
        if notes is not None:
            existing["notes"] = self._text(notes)

        if existing["status"] in CLOSED_SCHEDULE_ITEM_STATUSES:
            if not self._text(existing.get("closed_at")):
                existing["closed_at"] = _iso_now()
        else:
            existing["closed_at"] = ""
            existing["close_reason"] = ""

        existing["updated_at"] = _iso_now()
        self._save_managed_schedule({"version": payload.get("version", 1), "items": items})

        return {
            "status": "created" if creating else "updated",
            "item": existing,
            "managed_item_count": len([i for i in items if isinstance(i, dict)]),
        }

    @requires_license
    def set_schedule_constraint(
        self,
        constraint_id: str,
        description: str,
        *,
        activity_id: str | None = None,
        impact: str | None = None,
        due_date: str | None = None,
        owner: str | None = None,
        status: str = "blocked",
    ) -> dict[str, Any] | str:
        clean_description = self._text(description)
        if not clean_description:
            return "description is required."
        return self.upsert_schedule_item(
            constraint_id,
            title=clean_description,
            item_type="constraint",
            status=status,
            due_date=due_date,
            owner=owner,
            activity_id=activity_id,
            impact=impact,
        )

    @requires_license
    def close_schedule_item(self, item_id: str, reason: str | None = None, status: str = "done") -> dict[str, Any] | str:
        normalized_id = slugify_underscore(self._text(item_id))
        if not normalized_id:
            return "item_id is required."

        normalized_status = self._normalize_schedule_status(status, default="")
        if normalized_status not in CLOSED_SCHEDULE_ITEM_STATUSES:
            return "close status must be one of: done, cancelled."

        payload = self._load_managed_schedule()
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []

        target = None
        for item in items:
            if isinstance(item, dict) and self._text(item.get("id")) == normalized_id:
                target = item
                break

        if not isinstance(target, dict):
            return f"Schedule item '{normalized_id}' not found."

        target["status"] = normalized_status
        target["close_reason"] = self._text(reason)
        target["closed_at"] = _iso_now()
        target["updated_at"] = _iso_now()
        self._save_managed_schedule({"version": payload.get("version", 1), "items": items})
        return {
            "status": "closed",
            "item": target,
        }

    # ── Workspace Management ──────────────────────────────────────────────────

    def _workspaces_dir(self) -> Path:
        project_path = self.project.get("_dir")
        if project_path:
            ws_dir = Path(project_path) / "workspaces"
        else:
            ws_dir = self._store_path / self.project.get("name", "default") / "workspaces"
        ws_dir.mkdir(exist_ok=True)
        return ws_dir

    def _load_workspace(self, slug: str) -> dict[str, Any] | None:
        ws_path = self._workspaces_dir() / slug / "workspace.json"
        return load_json(ws_path) if ws_path.exists() else None

    def _save_workspace(self, ws: dict[str, Any]):
        slug = ws["slug"]
        ws_dir = self._workspaces_dir() / slug
        ws_dir.mkdir(exist_ok=True)
        save_json(ws_dir / "workspace.json", ws)

    def _all_workspaces(self) -> list[dict[str, Any]]:
        ws_dir = self._workspaces_dir()
        workspaces = []
        for d in sorted(ws_dir.iterdir()):
            if d.is_dir():
                ws = self._load_workspace(d.name)
                if ws:
                    workspaces.append(ws)
        return workspaces

    def _save_index(self):
        workspaces = self._all_workspaces()
        index = [{
            "slug": ws["slug"],
            "title": ws.get("title", ""),
            "description": ws.get("description", ""),
            "page_count": len(ws.get("pages", [])),
            "note_count": len(ws.get("notes", [])),
        } for ws in workspaces]
        save_json(self._workspaces_dir() / "_index.json", index)

    @requires_license
    def create_workspace(self, title: str, description: str) -> dict[str, Any] | str:
        if not title.strip():
            return "Workspace title is required."
        if not description.strip():
            return "Workspace description is required."

        slug = slugify_underscore(title)
        if self._load_workspace(slug):
            return f"Workspace '{slug}' already exists."

        ws = {
            "slug": slug,
            "title": title.strip(),
            "description": description.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pages": [],
            "notes": [],
        }
        self._save_workspace(ws)
        self._save_index()
        return {"status": "created", "slug": slug, "title": ws["title"]}

    @requires_license
    def list_workspaces(self) -> list[dict[str, Any]]:
        return [{
            "slug": ws["slug"],
            "title": ws.get("title", ""),
            "description": ws.get("description", ""),
            "page_count": len(ws.get("pages", [])),
            "note_count": len(ws.get("notes", [])),
        } for ws in self._all_workspaces()]

    @requires_license
    def get_workspace(self, slug: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."
        return ws

    @requires_license
    def add_workspace_page(self, slug: str, page_name: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found in knowledge store."
        resolved_name = page.get("name", page_name)

        for p in ws.get("pages", []):
            if p.get("page_name") == resolved_name:
                return f"Page '{resolved_name}' is already in workspace '{slug}'."

        ws.setdefault("pages", []).append({
            "page_name": resolved_name,
            "description": "",
            "selected_pointers": [],
            "highlights": [],
        })
        self._save_workspace(ws)
        self._save_index()
        return {"status": "added", "workspace": slug, "page": resolved_name}

    @requires_license
    def remove_workspace_page(self, slug: str, page_name: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        pages = ws.get("pages", [])
        new_pages = [p for p in pages if p.get("page_name") != page_name]
        if len(new_pages) == len(pages):
            return f"Page '{page_name}' is not in workspace '{slug}'."

        ws["pages"] = new_pages
        self._save_workspace(ws)
        self._save_index()
        return {"status": "removed", "workspace": slug, "page": page_name}

    @requires_license
    def select_pointers(self, slug: str, page_name: str, pointer_ids: list[str]) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        target_page = None
        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                target_page = p
                break

        if not target_page:
            page_data = self._resolve_page(page_name)
            if page_data:
                resolved_name = page_data.get("name", page_name)
                for p in ws.get("pages", []):
                    if p.get("page_name") == resolved_name:
                        target_page = p
                        page_name = resolved_name
                        break

        if not target_page:
            return f"Page '{page_name}' is not in workspace '{slug}'. Add it first with add_page."

        ks_page = self.project.get("pages", {}).get(page_name, {})
        valid_ids = {r.get("id") for r in ks_page.get("regions", []) if isinstance(r, dict)}

        invalid = [pid for pid in pointer_ids if pid not in valid_ids]
        if invalid:
            return f"Invalid pointer IDs: {invalid}. Use list_regions to see available pointers."

        existing = set(target_page.get("selected_pointers", []))
        existing.update(pointer_ids)
        target_page["selected_pointers"] = sorted(existing)

        self._save_workspace(ws)
        return {
            "status": "selected",
            "workspace": slug,
            "page": page_name,
            "selected_pointers": target_page["selected_pointers"],
        }

    @requires_license
    def deselect_pointers(self, slug: str, page_name: str, pointer_ids: list[str]) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        target_page = None
        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                target_page = p
                break

        if not target_page:
            return f"Page '{page_name}' is not in workspace '{slug}'."

        existing = set(target_page.get("selected_pointers", []))
        existing -= set(pointer_ids)
        target_page["selected_pointers"] = sorted(existing)

        self._save_workspace(ws)
        return {
            "status": "deselected",
            "workspace": slug,
            "page": page_name,
            "selected_pointers": target_page["selected_pointers"],
        }

    @requires_license
    def add_note(self, slug: str, text: str, source_page: str | None = None) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."
        if not text.strip():
            return "Note text is required."

        note = {
            "text": text.strip(),
            "source_page": source_page,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ws.setdefault("notes", []).append(note)
        self._save_workspace(ws)
        return {"status": "added", "workspace": slug, "note": note}

    @requires_license
    def add_page_description(self, slug: str, page_name: str, description: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                p["description"] = description.strip()
                self._save_workspace(ws)
                return {"status": "updated", "workspace": slug, "page": page_name}

        return f"Page '{page_name}' is not in workspace '{slug}'."

    # ── Highlight (Gemini Vision) ─────────────────────────────────────────────

    @requires_license
    def highlight(self, slug: str, page_name: str, query: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found in knowledge store."
        resolved_name = page.get("name", page_name)

        page_path = page.get("path")
        if not page_path:
            return f"No path found for page '{resolved_name}'."
        png_path = Path(page_path) / "page.png"
        if not png_path.exists():
            return f"No PNG found at {png_path}."

        # Ensure page is in workspace
        ws_page = None
        for p in ws.get("pages", []):
            if p.get("page_name") == resolved_name:
                ws_page = p
                break
        if not ws_page:
            ws.setdefault("pages", []).append({
                "page_name": resolved_name,
                "description": "",
                "selected_pointers": [],
                "custom_highlights": [],
            })
            ws_page = ws["pages"][-1]

        if self._workspace_root:
            load_dotenv(self._workspace_root)
        else:
            load_dotenv()

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "GEMINI_API_KEY not set. Set it in .env or environment."

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        png_bytes = png_path.read_bytes()
        prompt = HIGHLIGHT_PROMPT.format(query=query)

        response = client.models.generate_content(
            model=HIGHLIGHT_MODEL,
            contents=[types.Content(parts=[
                types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
                types.Part.from_text(text=prompt),
            ])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
                tools=[types.Tool(code_execution=types.ToolCodeExecution)],
            ),
        )

        raw = collect_text_only(response)
        if not raw:
            return "Empty response from Gemini."

        highlights = parse_json_list(raw, list_key="highlights")
        if highlights is None:
            return f"Failed to parse Gemini response: {raw[:500]}"

        custom_highlights = []
        for h in highlights:
            raw_box = h.get("box_2d") or h.get("bbox", [])
            bbox = normalize_bbox(raw_box)
            if bbox["x1"] <= bbox["x0"] or bbox["y1"] <= bbox["y0"]:
                continue
            custom_highlights.append({
                "label": h.get("label", ""),
                "bbox": bbox,
                "query": query,
                "confidence": h.get("confidence", 0.0),
            })

        ws_page.setdefault("custom_highlights", []).extend(custom_highlights)
        self._save_workspace(ws)
        self._save_index()

        return {
            "status": "highlighted",
            "workspace": slug,
            "page": resolved_name,
            "highlights_added": len(custom_highlights),
            "total_highlights": len(ws_page.get("custom_highlights", [])),
            "labels": [h["label"] for h in custom_highlights],
        }

    @requires_license
    def clear_highlights(self, slug: str, page_name: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                p["custom_highlights"] = []
                self._save_workspace(ws)
                return {"status": "cleared", "workspace": slug, "page": page_name}

        return f"Page '{page_name}' is not in workspace '{slug}'."

    # ── Image Generation ──────────────────────────────────────────────────────

    @requires_license
    def generate_image(
        self,
        slug: str,
        prompt: str,
        reference_pages: list[str] | None = None,
        reference_image_path: str | None = None,
        aspect_ratio: str = "1:1",
        image_size: str = "2K",
    ) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        if self._workspace_root:
            load_dotenv(self._workspace_root)
        else:
            load_dotenv()

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "GEMINI_API_KEY not set. Set it in .env or environment."

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        parts = []

        for pn in (reference_pages or []):
            page = self._resolve_page(pn)
            if page:
                png_path = Path(page["path"]) / "page.png"
                if png_path.exists():
                    parts.append(types.Part.from_bytes(
                        data=png_path.read_bytes(), mime_type="image/png"
                    ))

        if reference_image_path:
            ref_path = Path(reference_image_path)
            if ref_path.exists():
                suffix = ref_path.suffix.lower()
                mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
                parts.append(types.Part.from_bytes(data=ref_path.read_bytes(), mime_type=mime))
            else:
                return f"Reference image not found: {reference_image_path}"

        parts.append(types.Part.from_text(text=prompt))

        try:
            response = client.models.generate_content(
                model=IMAGE_GEN_MODEL,
                contents=[types.Content(parts=parts)],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                    ),
                ),
            )
        except Exception as e:
            return f"Gemini API error: {e}"

        image_data = None
        description_parts = []
        candidates = getattr(response, "candidates", []) or []
        for candidate in candidates:
            content_parts = getattr(getattr(candidate, "content", None), "parts", []) or []
            for part in content_parts:
                if getattr(part, "text", None):
                    description_parts.append(part.text)
                elif getattr(part, "inline_data", None):
                    image_data = part.inline_data.data

        if not image_data:
            desc = " ".join(description_parts).strip()
            return f"No image generated. Response: {desc[:500]}" if desc else "No image generated — empty response."

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        image_filename = f"gen_{timestamp}.png"

        img_dir = self._workspaces_dir() / slug / "generated_images"
        img_dir.mkdir(parents=True, exist_ok=True)
        image_path = img_dir / image_filename

        if isinstance(image_data, (bytes, bytearray)):
            image_path.write_bytes(image_data)
        else:
            import base64
            image_path.write_bytes(base64.b64decode(image_data))

        description = " ".join(description_parts).strip()
        gen_entry = {
            "type": "generated",
            "filename": image_filename,
            "prompt": prompt,
            "reference_pages": reference_pages or [],
            "description": description,
            "aspect_ratio": aspect_ratio,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ws.setdefault("generated_images", []).append(gen_entry)
        self._save_workspace(ws)
        self._save_index()

        return {
            "status": "generated",
            "workspace": slug,
            "filename": image_filename,
            "description": description,
            "total_generated": len(ws.get("generated_images", [])),
        }

    @requires_license
    def delete_image(self, slug: str, filename: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        images = ws.get("generated_images", [])
        found = None
        for i, img in enumerate(images):
            if img.get("filename") == filename:
                found = i
                break

        if found is None:
            return f"Image '{filename}' not found in workspace '{slug}'."

        removed = images.pop(found)
        self._save_workspace(ws)
        self._save_index()

        img_path = self._workspaces_dir() / slug / "generated_images" / filename
        if img_path.exists():
            img_path.unlink()

        return {
            "status": "deleted",
            "workspace": slug,
            "filename": filename,
            "prompt": removed.get("prompt", ""),
        }
