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
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .agent_role import is_company_role
from .config import (
    HIGHLIGHT_MODEL,
    IMAGE_GEN_MODEL,
    get_store_path,
    load_dotenv,
)
from .control_plane import resolve_network_urls
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

NUMERIC_SIGNAL_RE = re.compile(
    r"(?<!\w)(\d+(?:\.\d+)?)\s*(\"|inches|inch|in\.|feet|foot|ft|mm|cm|m|degrees|degree|°|ga|gauge)\b",
    re.IGNORECASE,
)

CONFLICT_CUE_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("single-stage", "two-stage", "staging_conflict"),
    ("single stage", "two stage", "staging_conflict"),
    ("install", "remove", "scope_conflict"),
    ("new", "existing", "scope_conflict"),
    ("demolish", "install", "scope_conflict"),
    ("prior to", "after", "sequence_conflict"),
    ("before", "after", "sequence_conflict"),
)


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


def _query_terms(query: str) -> tuple[str, list[str]]:
    phrase = str(query or "").strip().lower()
    if not phrase:
        return "", []
    normalized = "".join(ch if ch.isalnum() else " " for ch in phrase)
    terms: list[str] = []
    seen: set[str] = set()
    for token in normalized.split():
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    if not terms:
        terms = [phrase]
    return phrase, terms


def _match_strength(text: Any, full_query: str, terms: list[str]) -> int:
    blob = str(text or "").lower()
    if not blob:
        return 0
    matched_terms = sum(1 for term in terms if term in blob)
    if full_query and full_query in blob:
        return max(matched_terms, len(terms))
    return matched_terms


def _normalize_unit(unit: str) -> str:
    token = str(unit or "").strip().lower()
    aliases = {
        '"': "in",
        "inch": "in",
        "inches": "in",
        "in.": "in",
        "foot": "ft",
        "feet": "ft",
        "degree": "deg",
        "degrees": "deg",
        "°": "deg",
        "gauge": "ga",
    }
    return aliases.get(token, token)


def _extract_numeric_signals(text: Any) -> list[dict[str, str]]:
    blob = str(text or "")
    signals: list[dict[str, str]] = []
    for match in NUMERIC_SIGNAL_RE.finditer(blob):
        value, unit = match.groups()
        signals.append({
            "value": value,
            "unit": _normalize_unit(unit),
            "raw": match.group(0),
        })
    return signals


def _extract_conflict_cues(text: Any) -> set[str]:
    blob = str(text or "").lower()
    cues: set[str] = set()
    for left, right, _kind in CONFLICT_CUE_PAIRS:
        if left in blob:
            cues.add(left)
        if right in blob:
            cues.add(right)
    return cues


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


# ── Project Access Guard ──────────────────────────────────────────────────────

def requires_license(func):
    """Compatibility decorator retained after project-license removal."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)
    return wrapper


class MaestroTools:
    """
    Stateful tool interface for querying a Maestro knowledge store.

    Loads a project once and provides all query/workspace/highlight methods.
    
    Project access is direct. Fleet project maestros do not require a
    separate project license to use tools.
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
        self._workspace_root = self._infer_workspace_root(workspace_root)
        self._project: dict[str, Any] | None = None
        self.licensed = True
        
        # Load environment variables
        if workspace_root:
            load_dotenv(workspace_root)
        else:
            load_dotenv()

        if is_company_role(self._workspace_root):
            raise RuntimeError(
                "Company Maestro is control-plane only. "
                "Project knowledge tools are disabled in this workspace."
            )

    def _infer_workspace_root(self, workspace_root: Path | None) -> Path | None:
        if workspace_root:
            return Path(workspace_root)

        try:
            resolved_store = self._store_path.resolve()
        except Exception:
            resolved_store = self._store_path

        if resolved_store.name == "knowledge_store":
            return resolved_store.parent

        cwd = Path.cwd()
        if (cwd / ".env").exists():
            return cwd
        return None

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

    def _workspace_route_path(self) -> str:
        workspace_root = self._workspace_root
        if workspace_root and is_company_role(workspace_root):
            return "/command-center"
        if workspace_root:
            parts = workspace_root.resolve().parts
            if "projects" in parts:
                index = parts.index("projects")
                if index + 1 < len(parts):
                    slug = str(parts[index + 1]).strip()
                    if slug:
                        return f"/{slug}/"
        return "/workspace"

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
            notes = self._text(item.get("notes") or item.get("description"))
            normalized_items.append({
                "id": item_id,
                "title": self._text(item.get("title")),
                "type": self._normalize_schedule_type(item.get("type")),
                "status": self._normalize_schedule_status(item.get("status")),
                "due_date": self._text(item.get("due_date")),
                "owner": self._text(item.get("owner")),
                "activity_id": self._text(item.get("activity_id")),
                "impact": self._text(item.get("impact")),
                "notes": notes,
                "description": notes,
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

    @staticmethod
    def _parse_schedule_day(value: Any) -> date | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        candidate = raw[:10]
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.date()

    @staticmethod
    def _week_start_monday(day: date) -> date:
        return day - timedelta(days=day.weekday())

    @staticmethod
    def _month_key(day: date) -> str:
        return f"{day.year:04d}-{day.month:02d}"

    @staticmethod
    def _month_bounds(month: str) -> tuple[date, date]:
        raw = str(month or "").strip()
        if len(raw) != 7 or raw[4] != "-":
            raise ValueError("month must be in YYYY-MM format.")
        try:
            year = int(raw[:4])
            month_num = int(raw[5:7])
            start = date(year, month_num, 1)
        except (TypeError, ValueError):
            raise ValueError("month must be in YYYY-MM format.") from None

        if month_num == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month_num + 1, 1) - timedelta(days=1)
        return start, end

    @staticmethod
    def _month_label(day: date) -> str:
        return f"{day:%B} {day.year}"

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

    def _score_pages_for_query(self, query: str) -> tuple[str, list[str], list[dict[str, Any]], dict[str, Any]]:
        full_query, query_terms = _query_terms(query)
        if not full_query:
            return "", [], [], {"materials": [], "keywords": [], "pointer_hits": [], "page_hits": []}

        page_scores: dict[str, dict[str, Any]] = {}
        evidence = {
            "materials": [],
            "keywords": [],
            "pointer_hits": [],
            "page_hits": [],
        }

        def ensure_page(page_name: str) -> dict[str, Any]:
            current = page_scores.get(page_name)
            if current is None:
                page = self.project.get("pages", {}).get(page_name, {})
                current = {
                    "page_name": page_name,
                    "score": 0,
                    "reasons": [],
                    "discipline": str(page.get("discipline", "") or "General"),
                    "summary": str(page.get("sheet_reflection", "") or ""),
                    "matched_terms": set(),
                }
                page_scores[page_name] = current
            return current

        def apply_page_score(page_name: str, score: int, reason: str, matched_terms: list[str] | None = None):
            if not page_name or score <= 0:
                return
            row = ensure_page(page_name)
            row["score"] += score
            if reason not in row["reasons"]:
                row["reasons"].append(reason)
            for term in matched_terms or []:
                row["matched_terms"].add(term)

        idx = self.project.get("index", {}) if isinstance(self.project.get("index", {}), dict) else {}

        for material, sources in idx.get("materials", {}).items():
            strength = _match_strength(material, full_query, query_terms)
            if strength <= 0:
                continue
            material_text = str(material)
            matched_terms = [term for term in query_terms if term in material_text.lower()]
            evidence["materials"].append({
                "text": material_text,
                "strength": strength,
                "matched_terms": matched_terms,
                "found_in": sources if isinstance(sources, list) else [],
            })
            for source in sources if isinstance(sources, list) else []:
                page_name = str(source.get("page", "") or "")
                apply_page_score(page_name, strength * 6, f"material:{material_text}", matched_terms)

        for keyword, sources in idx.get("keywords", {}).items():
            strength = _match_strength(keyword, full_query, query_terms)
            if strength <= 0:
                continue
            keyword_text = str(keyword)
            matched_terms = [term for term in query_terms if term in keyword_text.lower()]
            evidence["keywords"].append({
                "text": keyword_text,
                "strength": strength,
                "matched_terms": matched_terms,
                "found_in": sources if isinstance(sources, list) else [],
            })
            for source in sources if isinstance(sources, list) else []:
                page_name = str(source.get("page", "") or "")
                apply_page_score(page_name, strength * 5, f"keyword:{keyword_text}", matched_terms)

        for page_name, page in self.project.get("pages", {}).items():
            page_name_strength = _match_strength(page_name, full_query, query_terms)
            if page_name_strength > 0:
                matched_terms = [term for term in query_terms if term in page_name.lower()]
                evidence["page_hits"].append({
                    "page_name": page_name,
                    "kind": "page_name",
                    "strength": page_name_strength,
                    "matched_terms": matched_terms,
                })
                apply_page_score(page_name, page_name_strength, "page_name", matched_terms)

            reflection = str(page.get("sheet_reflection", "") or "")
            reflection_strength = _match_strength(reflection, full_query, query_terms)
            if reflection_strength > 0:
                matched_terms = [term for term in query_terms if term in reflection.lower()]
                evidence["page_hits"].append({
                    "page_name": page_name,
                    "kind": "sheet_reflection",
                    "strength": reflection_strength,
                    "matched_terms": matched_terms,
                    "excerpt": reflection[:240],
                })
                apply_page_score(page_name, reflection_strength * 4, "sheet_reflection", matched_terms)

            for pointer_id, pointer in page.get("pointers", {}).items():
                detail = str(pointer.get("content_markdown", "") or "")
                pointer_strength = _match_strength(detail, full_query, query_terms)
                if pointer_strength <= 0:
                    continue
                matched_terms = [term for term in query_terms if term in detail.lower()]
                evidence["pointer_hits"].append({
                    "page_name": page_name,
                    "region_id": pointer_id,
                    "strength": pointer_strength,
                    "matched_terms": matched_terms,
                    "excerpt": detail[:240],
                })
                apply_page_score(page_name, pointer_strength * 3, f"pointer:{pointer_id}", matched_terms)

        ranked_pages = sorted(
            (
                {
                    **row,
                    "reasons": row["reasons"][:6],
                    "matched_terms": sorted(row["matched_terms"]),
                }
                for row in page_scores.values()
            ),
            key=lambda row: (-int(row["score"]), -len(row["matched_terms"]), str(row["page_name"]).lower()),
        )

        evidence["materials"] = sorted(
            evidence["materials"],
            key=lambda row: (-int(row["strength"]), -len(row["matched_terms"]), str(row["text"]).lower()),
        )
        evidence["keywords"] = sorted(
            evidence["keywords"],
            key=lambda row: (-int(row["strength"]), -len(row["matched_terms"]), str(row["text"]).lower()),
        )
        evidence["pointer_hits"] = sorted(
            evidence["pointer_hits"],
            key=lambda row: (-int(row["strength"]), str(row["page_name"]).lower(), str(row["region_id"]).lower()),
        )
        evidence["page_hits"] = sorted(
            evidence["page_hits"],
            key=lambda row: (-int(row["strength"]), str(row["page_name"]).lower(), str(row.get("kind", "")).lower()),
        )
        return full_query, query_terms, ranked_pages, evidence

    def _evidence_snippets(
        self,
        ranked_pages: list[dict[str, Any]],
        evidence: dict[str, Any],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        page_names = [str(row.get("page_name") or "") for row in ranked_pages[: max(1, limit)]]
        page_lookup = {str(row.get("page_name") or ""): row for row in ranked_pages}
        snippets: list[dict[str, Any]] = []

        for page_name in page_names:
            if not page_name:
                continue
            row = page_lookup.get(page_name, {})
            summary = str(row.get("summary") or "").strip()
            if summary:
                snippets.append({
                    "page_name": page_name,
                    "discipline": row.get("discipline") or "General",
                    "source": "sheet_reflection",
                    "matched_terms": row.get("matched_terms") or [],
                    "text": summary,
                })

        seen_regions: set[tuple[str, str]] = set()
        for hit in evidence.get("pointer_hits", []):
            page_name = str(hit.get("page_name") or "")
            region_id = str(hit.get("region_id") or "")
            if page_name not in page_names or not region_id:
                continue
            key = (page_name, region_id)
            if key in seen_regions:
                continue
            seen_regions.add(key)
            row = page_lookup.get(page_name, {})
            snippets.append({
                "page_name": page_name,
                "discipline": row.get("discipline") or "General",
                "source": "pointer",
                "region_id": region_id,
                "matched_terms": hit.get("matched_terms") or [],
                "text": str(hit.get("excerpt") or "").strip(),
            })
            if len(snippets) >= max(limit * 2, 10):
                break
        return snippets

    def _page_evidence_flags(self, reasons: list[str]) -> dict[str, bool]:
        items = {str(reason) for reason in reasons or []}
        return {
            "material": any(reason.startswith("material:") for reason in items),
            "keyword": any(reason.startswith("keyword:") for reason in items),
            "reflection": "sheet_reflection" in items,
            "pointer": any(reason.startswith("pointer:") for reason in items),
            "page_name": "page_name" in items,
        }

    def _concept_conflicts(
        self,
        ranked_pages: list[dict[str, Any]],
        evidence: dict[str, Any],
        *,
        limit: int = 8,
    ) -> dict[str, Any]:
        snippets = self._evidence_snippets(ranked_pages, evidence, limit=limit)
        numeric_index: dict[str, dict[str, list[dict[str, Any]]]] = {}
        cue_index: dict[str, list[dict[str, Any]]] = {}
        disciplines: set[str] = set()

        for snippet in snippets:
            discipline = str(snippet.get("discipline") or "General")
            disciplines.add(discipline)
            text = str(snippet.get("text") or "")
            for signal in _extract_numeric_signals(text):
                bucket = numeric_index.setdefault(signal["unit"], {})
                bucket.setdefault(signal["value"], []).append({
                    "page_name": snippet["page_name"],
                    "discipline": discipline,
                    "source": snippet.get("source") or "sheet_reflection",
                    "raw": signal["raw"],
                    "text": text[:240],
                })
            for cue in _extract_conflict_cues(text):
                cue_index.setdefault(cue, []).append({
                    "page_name": snippet["page_name"],
                    "discipline": discipline,
                    "source": snippet.get("source") or "sheet_reflection",
                    "text": text[:240],
                })

        conflicts: list[dict[str, Any]] = []
        for unit, values in numeric_index.items():
            distinct_values = [value for value, rows in values.items() if rows]
            if len(distinct_values) < 2:
                continue
            evidence_rows = [row for value in distinct_values[:3] for row in values[value][:2]]
            conflicts.append({
                "kind": "dimension_mismatch",
                "severity": "medium",
                "summary": f"Potential {unit} mismatch across supporting evidence.",
                "values": distinct_values[:4],
                "evidence": evidence_rows,
            })

        for left, right, kind in CONFLICT_CUE_PAIRS:
            left_rows = cue_index.get(left, [])
            right_rows = cue_index.get(right, [])
            if not left_rows or not right_rows:
                continue
            conflicts.append({
                "kind": kind,
                "severity": "medium",
                "summary": f"Potential instruction tension between '{left}' and '{right}'.",
                "signals": [left, right],
                "evidence": left_rows[:2] + right_rows[:2],
            })

        coordination_flags: list[dict[str, Any]] = []
        if len(disciplines) >= 2:
            top_pages = ranked_pages[: max(2, min(limit, 6))]
            coordination_flags.append({
                "kind": "cross_discipline_coordination",
                "summary": "The concept spans multiple disciplines and should be verified across governing sheets before acting.",
                "disciplines": sorted(disciplines),
                "supporting_pages": [
                    {
                        "page_name": row.get("page_name"),
                        "discipline": row.get("discipline"),
                        "reasons": row.get("reasons") or [],
                    }
                    for row in top_pages
                ],
            })

        return {
            "conflicts": conflicts,
            "coordination_flags": coordination_flags,
            "snippets": snippets,
        }

    @requires_license
    def search(self, query: str) -> list[dict[str, Any]] | str:
        query_lower, _, ranked_pages, evidence = self._score_pages_for_query(query)
        if not query_lower:
            return "Search query is required"
        results: list[dict[str, Any]] = []
        for row in evidence["materials"][:20]:
            results.append({"type": "material", "match": row["text"], "strength": row["strength"], "matched_terms": row["matched_terms"], "found_in": row["found_in"]})
        for row in evidence["keywords"][:20]:
            results.append({"type": "keyword", "match": row["text"], "strength": row["strength"], "matched_terms": row["matched_terms"], "found_in": row["found_in"]})
        for row in evidence["page_hits"][:15]:
            results.append({"type": "page", "match": row["page_name"], "context": row["kind"], "strength": row["strength"], "matched_terms": row["matched_terms"], "excerpt": row.get("excerpt", "")})
        for row in evidence["pointer_hits"][:20]:
            results.append({"type": "pointer", "match": f"{row['page_name']}/{row['region_id']}", "context": "content_markdown", "strength": row["strength"], "matched_terms": row["matched_terms"], "excerpt": row.get("excerpt", "")})
        if results:
            return results
        if ranked_pages:
            return [
                {
                    "type": "page",
                    "match": row["page_name"],
                    "context": "ranked_page",
                    "score": row["score"],
                    "reasons": row["reasons"],
                    "matched_terms": row["matched_terms"],
                }
                for row in ranked_pages[:20]
            ]
        return f"No results for '{query}'"

    @requires_license
    def concept_trace(self, query: str, limit: int = 8) -> dict[str, Any] | str:
        full_query, query_terms, ranked_pages, evidence = self._score_pages_for_query(query)
        if not full_query:
            return "Concept query is required"

        top_pages = ranked_pages[: max(1, min(limit, 12))]
        explicit_claims: list[dict[str, Any]] = []
        inferred_claims: list[dict[str, Any]] = []
        for row in top_pages:
            claim = {
                "page_name": row["page_name"],
                "discipline": row["discipline"],
                "matched_terms": row["matched_terms"],
                "reasons": row["reasons"],
                "summary": str(row["summary"] or "")[:420],
            }
            if any(reason.startswith("material:") or reason.startswith("keyword:") or reason == "sheet_reflection" for reason in row["reasons"]):
                explicit_claims.append(claim)
            else:
                inferred_claims.append(claim)

        supporting_regions: list[dict[str, Any]] = []
        seen_regions: set[tuple[str, str]] = set()
        for hit in evidence["pointer_hits"]:
            key = (str(hit["page_name"]), str(hit["region_id"]))
            if key in seen_regions:
                continue
            seen_regions.add(key)
            supporting_regions.append({
                "page_name": hit["page_name"],
                "region_id": hit["region_id"],
                "matched_terms": hit["matched_terms"],
                "excerpt": hit.get("excerpt", ""),
            })
            if len(supporting_regions) >= max(4, limit):
                break

        evidence_terms = [row["text"] for row in evidence["materials"][:6]] + [row["text"] for row in evidence["keywords"][:6]]
        confidence = "low"
        if explicit_claims and len(top_pages) >= 3 and (len(evidence["materials"]) + len(evidence["keywords"])) >= 4:
            confidence = "high"
        elif explicit_claims or len(top_pages) >= 2:
            confidence = "medium"

        gaps: list[str] = []
        if not evidence["pointer_hits"]:
            gaps.append("No region-level evidence matched directly; answer relies on sheet-level/index evidence.")
        if not evidence["materials"]:
            gaps.append("No material hits matched directly; concept is currently driven more by keywords and summaries.")
        if len(top_pages) < 2:
            gaps.append("Concept is supported by very few sheets; verify before turning it into a workspace or schedule decision.")

        return {
            "query": full_query,
            "matched_terms": query_terms,
            "confidence": confidence,
            "concept_evidence": {
                "materials": evidence["materials"][:8],
                "keywords": evidence["keywords"][:8],
                "supporting_regions": supporting_regions,
                "top_pages": [
                    {
                        "page_name": row["page_name"],
                        "discipline": row["discipline"],
                        "score": row["score"],
                        "matched_terms": row["matched_terms"],
                        "reasons": row["reasons"],
                        "summary": str(row["summary"] or "")[:420],
                    }
                    for row in top_pages
                ],
            },
            "claims": {
                "explicit": explicit_claims[:6],
                "inferred": inferred_claims[:6],
            },
            "gaps": gaps,
            "next_moves": [
                "Use the top pages to inspect sheet summaries and region details before rendering a workspace.",
                "If the concept will drive execution, compare evidence across details/spec language and record any unresolved gap as a note or schedule item.",
            ],
            "evidence_terms": evidence_terms,
        }

    @requires_license
    def governing_scope(self, query: str, limit: int = 6) -> dict[str, Any] | str:
        full_query, query_terms, ranked_pages, evidence = self._score_pages_for_query(query)
        if not full_query:
            return "Scope query is required"

        capped_limit = max(1, min(limit, 12))
        scoped_pages: list[dict[str, Any]] = []
        for row in ranked_pages[:capped_limit]:
            flags = self._page_evidence_flags(row.get("reasons") or [])
            governance_score = int(row.get("score") or 0)
            if flags["pointer"]:
                governance_score += 6
            if flags["material"]:
                governance_score += 5
            if flags["keyword"]:
                governance_score += 4
            if flags["reflection"]:
                governance_score += 3
            governance_score += len(row.get("matched_terms") or [])

            role = "supporting"
            if flags["pointer"] and (flags["material"] or flags["keyword"] or flags["reflection"]):
                role = "governing"
            elif not (flags["material"] or flags["keyword"] or flags["reflection"]):
                role = "locator"

            scoped_pages.append({
                "page_name": row.get("page_name"),
                "discipline": row.get("discipline") or "General",
                "governance_score": governance_score,
                "role": role,
                "matched_terms": row.get("matched_terms") or [],
                "reasons": row.get("reasons") or [],
                "summary": str(row.get("summary") or "")[:420],
            })

        scoped_pages.sort(key=lambda row: (-int(row["governance_score"]), str(row["page_name"]).lower()))
        governing_pages = [row for row in scoped_pages if row["role"] == "governing"][: max(2, min(capped_limit, 4))]
        supporting_pages = [row for row in scoped_pages if row["role"] != "governing"][:capped_limit]

        governing_names = {str(row["page_name"]) for row in governing_pages}
        governing_regions: list[dict[str, Any]] = []
        for hit in evidence["pointer_hits"]:
            page_name = str(hit.get("page_name") or "")
            if page_name not in governing_names:
                continue
            governing_regions.append({
                "page_name": page_name,
                "region_id": hit.get("region_id") or "",
                "matched_terms": hit.get("matched_terms") or [],
                "excerpt": hit.get("excerpt") or "",
            })
            if len(governing_regions) >= max(4, capped_limit):
                break

        disciplines = sorted({str(row.get("discipline") or "General") for row in scoped_pages})
        confidence = "low"
        if len(governing_pages) >= 2 and governing_regions:
            confidence = "high"
        elif scoped_pages:
            confidence = "medium"

        gaps: list[str] = []
        if not governing_pages:
            gaps.append("No clearly governing pages emerged yet; inspect the top supporting sheets before creating a workspace.")
        if not governing_regions:
            gaps.append("No governing regions matched directly; verify the governing scope with region details before relying on it in the field.")

        return {
            "query": full_query,
            "matched_terms": query_terms,
            "confidence": confidence,
            "governing_scope": {
                "governing_pages": governing_pages,
                "supporting_pages": supporting_pages,
                "governing_regions": governing_regions,
                "disciplines": disciplines,
            },
            "gaps": gaps,
            "next_moves": [
                "Read the governing sheets and regions first; use supporting pages to fill in trade coordination and execution context.",
                "Only render a workspace after the governing scope feels stable enough to guide field decisions.",
            ],
        }

    @requires_license
    def detect_conflicts(self, query: str, limit: int = 8) -> dict[str, Any] | str:
        full_query, query_terms, ranked_pages, evidence = self._score_pages_for_query(query)
        if not full_query:
            return "Conflict query is required"

        capped_limit = max(2, min(limit, 12))
        analysis = self._concept_conflicts(ranked_pages, evidence, limit=capped_limit)
        conflicts = analysis["conflicts"]
        coordination_flags = analysis["coordination_flags"]
        confidence = "low"
        if conflicts:
            confidence = "high"
        elif coordination_flags or ranked_pages[:2]:
            confidence = "medium"

        gaps: list[str] = []
        if not conflicts:
            gaps.append("No direct contradiction cues were found; verify against governing details before assuming the concept is conflict-free.")
        if not analysis["snippets"]:
            gaps.append("Very little evidence text matched directly; widen the concept trace before using this as a field decision.")

        return {
            "query": full_query,
            "matched_terms": query_terms,
            "confidence": confidence,
            "potential_conflicts": conflicts,
            "coordination_flags": coordination_flags,
            "supporting_evidence": analysis["snippets"][: max(6, capped_limit)],
            "next_moves": [
                "Inspect the cited sheets and regions before changing the field plan.",
                "If the tension is real, convert it into a note, RFI candidate, or schedule constraint after verification.",
            ],
            "gaps": gaps,
        }

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
    def get_access_urls(self) -> dict[str, Any]:
        urls = resolve_network_urls(route_path=self._workspace_route_path())
        return {
            "recommended_url": str(urls.get("recommended_url", "")).strip(),
            "localhost_url": str(urls.get("localhost_url", "")).strip(),
            "tailnet_url": str(urls.get("tailnet_url") or "").strip(),
        }

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
    def get_schedule_timeline(
        self,
        month: str | None = None,
        include_empty_days: bool = True,
    ) -> dict[str, Any] | str:
        payload = self._load_managed_schedule()
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []

        today = datetime.now().date()
        try:
            month_start, month_end = self._month_bounds(month or self._month_key(today))
        except ValueError as exc:
            return str(exc)

        day_map: dict[date, list[dict[str, Any]]] = {}
        unscheduled: list[dict[str, Any]] = []

        if include_empty_days:
            cursor = month_start
            while cursor <= month_end:
                day_map[cursor] = []
                cursor += timedelta(days=1)

        for item in items:
            if not isinstance(item, dict):
                continue
            due_date = self._text(item.get("due_date"))
            day = self._parse_schedule_day(due_date)
            timeline_item = {
                "id": self._text(item.get("id")),
                "title": self._text(item.get("title")),
                "description": self._text(item.get("notes") or item.get("description")),
                "date": due_date,
                "due_date": due_date,
                "status": self._normalize_schedule_status(item.get("status"), default="pending"),
                "owner": self._text(item.get("owner")),
                "type": self._normalize_schedule_type(item.get("type"), default="activity"),
                "activity_id": self._text(item.get("activity_id")),
                "updated_at": self._text(item.get("updated_at")),
            }

            if day is None:
                unscheduled.append(timeline_item)
                continue
            if day < month_start or day > month_end:
                continue
            day_map.setdefault(day, []).append(timeline_item)

        if not day_map:
            fallback_day = today if month_start <= today <= month_end else month_start
            day_map[fallback_day] = []

        for day_items in day_map.values():
            day_items.sort(
                key=lambda item: (
                    str(item.get("status") in CLOSED_SCHEDULE_ITEM_STATUSES),
                    str(item.get("title") or item.get("id") or ""),
                ),
            )

        days: list[dict[str, Any]] = []
        for day in sorted(day_map.keys(), reverse=True):
            week_start = self._week_start_monday(day)
            day_items = day_map.get(day, [])
            days.append({
                "date": day.isoformat(),
                "label": f"{day:%a, %b} {day.day}, {day.year}",
                "is_today": day == today,
                "is_future": day > today,
                "is_past": day < today,
                "week_start": week_start.isoformat(),
                "week_end": (week_start + timedelta(days=6)).isoformat(),
                "week_label": f"Week of {week_start:%b} {week_start.day}, {week_start.year}",
                "item_count": len(day_items),
                "items": day_items,
            })

        unscheduled.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("id") or "")), reverse=True)

        return {
            "today": today.isoformat(),
            "month": self._month_key(month_start),
            "month_label": self._month_label(month_start),
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat(),
            "previous_month": self._month_key(month_start - timedelta(days=1)),
            "next_month": self._month_key(month_end + timedelta(days=1)),
            "include_empty_days": bool(include_empty_days),
            "week_starts_on": "monday",
            "sort_order": "future_to_past",
            "updated_at": self._text(payload.get("updated_at")),
            "day_count": len(days),
            "item_count": sum(int(day.get("item_count", 0)) for day in days) + len(unscheduled),
            "days": days,
            "unscheduled": unscheduled,
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
        date: str | None = None,
        owner: str | None = None,
        activity_id: str | None = None,
        impact: str | None = None,
        notes: str | None = None,
        description: str | None = None,
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

        effective_due_date = due_date if due_date is not None else date
        effective_notes = notes if notes is not None else description

        if effective_due_date is not None:
            existing["due_date"] = self._text(effective_due_date)
        if owner is not None:
            existing["owner"] = self._text(owner)
        if activity_id is not None:
            existing["activity_id"] = self._text(activity_id)
        if impact is not None:
            existing["impact"] = self._text(impact)
        if effective_notes is not None:
            existing["notes"] = self._text(effective_notes)

        if existing["status"] in CLOSED_SCHEDULE_ITEM_STATUSES:
            if not self._text(existing.get("closed_at")):
                existing["closed_at"] = _iso_now()
        else:
            existing["closed_at"] = ""
            existing["close_reason"] = ""

        existing["updated_at"] = _iso_now()
        self._save_managed_schedule({"version": payload.get("version", 1), "items": items})

        item_payload = {**existing, "description": self._text(existing.get("notes"))}
        return {
            "status": "created" if creating else "updated",
            "item": item_payload,
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
        item_payload = {**target, "description": self._text(target.get("notes"))}
        return {
            "status": "closed",
            "item": item_payload,
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
    def delete_workspace(self, slug: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        ws_path = self._workspaces_dir() / slug
        if ws_path.exists():
            shutil.rmtree(ws_path)
        self._save_index()
        return {
            "status": "deleted",
            "workspace": slug,
            "page_count": len(ws.get("pages", [])),
            "note_count": len(ws.get("notes", [])),
        }

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
