"""
Maestro index builder — aggregates search data across all pages and pointers.

Builds the project-level index.json with materials, keywords, cross-references,
modifications, and broken reference detection.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .utils import load_json, save_json


# ── Helper Functions ──────────────────────────────────────────────────────────

def _flatten_strings(value) -> list[str]:
    """Recursively extract all string values from nested structures."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(k, str) and k.strip():
                out.append(k.strip())
            out.extend(_flatten_strings(v))
        return out
    return []


def _add_term(bucket: dict, term: str, source: dict):
    """Add a term to an inverted index bucket with source tracking."""
    t = term.strip()
    if not t:
        return
    bucket.setdefault(t, [])
    if source not in bucket[t]:
        bucket[t].append(source)


_SHEET_RE = re.compile(r"\b[A-Z]{1,3}-?\d{2,4}(?:\.\d+)?\b")


def _extract_refs(value) -> list[str]:
    """Extract sheet reference identifiers from nested structures."""
    if value is None:
        return []
    if isinstance(value, str):
        m = _SHEET_RE.findall(value.upper())
        return m if m else ([value.strip()] if value.strip() else [])
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_extract_refs(item))
        return out
    if isinstance(value, dict):
        for k in ("sheet", "sheet_number", "target", "page", "ref", "to"):
            if k in value:
                return _extract_refs(value[k])
        out = []
        for v in value.values():
            out.extend(_extract_refs(v))
        return out
    return []


# ── Index Builder ─────────────────────────────────────────────────────────────

def build_index(project_dir: Path) -> dict:
    """
    Build aggregated search index for a project.

    Scans all pages and pointers, collecting materials, keywords,
    cross-references, and modifications into a single index.json.

    Args:
        project_dir: Path to the project directory within knowledge_store

    Returns:
        The complete index dict (also saved to project_dir/index.json)
    """
    pages_dir = project_dir / "pages"
    idx: dict[str, Any] = {
        "materials": {},
        "keywords": {},
        "modifications": [],
        "cross_refs": {},
        "broken_refs": [],
        "pages": {},
        "summary": {
            "page_count": 0,
            "pointer_count": 0,
            "unique_material_count": 0,
            "unique_keyword_count": 0,
            "modification_count": 0,
            "broken_ref_count": 0,
        },
    }
    if not pages_dir.exists():
        return idx

    page_dirs = sorted(
        [d for d in pages_dir.iterdir() if d.is_dir()],
        key=lambda p: p.name.lower(),
    )
    page_names = {d.name for d in page_dirs}

    for pd in page_dirs:
        pn = pd.name
        p1 = load_json(pd / "pass1.json")
        pi = p1.get("index", {}) if isinstance(p1.get("index"), dict) else {}
        regions = p1.get("regions", []) if isinstance(p1.get("regions"), list) else []

        page_info = {
            "discipline": p1.get("discipline", "General"),
            "page_type": p1.get("page_type", "unknown"),
            "region_count": len(regions),
            "pointer_count": 0,
        }
        idx["pages"][pn] = page_info

        # Index page-level materials and keywords
        for mat in _flatten_strings(pi.get("materials", [])):
            _add_term(idx["materials"], mat, {"page": pn})
        for kw in _flatten_strings(pi.get("keywords", [])):
            _add_term(idx["keywords"], kw, {"page": pn})
        for ref in _extract_refs(p1.get("cross_references", [])):
            idx["cross_refs"].setdefault(ref, [])
            if pn not in idx["cross_refs"][ref]:
                idx["cross_refs"][ref].append(pn)

        # Index pointer-level data
        ptrs_dir = pd / "pointers"
        ptr_dirs = (
            sorted([d for d in ptrs_dir.iterdir() if d.is_dir()], key=lambda p: p.name)
            if ptrs_dir.exists()
            else []
        )
        page_info["pointer_count"] = len(ptr_dirs)

        for ptr_dir in ptr_dirs:
            rid = ptr_dir.name
            p2 = load_json(ptr_dir / "pass2.json")
            src = {"page": pn, "region_id": rid}

            for mat in _flatten_strings(p2.get("materials", [])):
                _add_term(idx["materials"], mat, src)
            for field in (
                p2.get("keynotes_referenced", []),
                p2.get("keynotes", []),
                p2.get("specifications", []),
            ):
                for kw in _flatten_strings(field):
                    _add_term(idx["keywords"], kw, src)
            for ref in _extract_refs(p2.get("cross_references", [])):
                idx["cross_refs"].setdefault(ref, [])
                if pn not in idx["cross_refs"][ref]:
                    idx["cross_refs"][ref].append(pn)

            for mod in p2.get("modifications", []) if isinstance(p2.get("modifications"), list) else []:
                if isinstance(mod, dict):
                    entry = {
                        "action": str(mod.get("action", "")),
                        "item": str(mod.get("item", "")),
                        "note": str(mod.get("note", "")),
                        "source": src,
                    }
                elif isinstance(mod, str) and mod.strip():
                    entry = {"action": "", "item": mod.strip(), "note": "", "source": src}
                else:
                    continue
                if entry not in idx["modifications"]:
                    idx["modifications"].append(entry)

    # Detect broken references
    idx["broken_refs"] = sorted(t for t in idx["cross_refs"] if t not in page_names)

    # Summary
    s = idx["summary"]
    s["page_count"] = len(page_names)
    s["pointer_count"] = sum(p["pointer_count"] for p in idx["pages"].values())
    s["unique_material_count"] = len(idx["materials"])
    s["unique_keyword_count"] = len(idx["keywords"])
    s["modification_count"] = len(idx["modifications"])
    s["broken_ref_count"] = len(idx["broken_refs"])

    save_json(project_dir / "index.json", idx)
    return idx
