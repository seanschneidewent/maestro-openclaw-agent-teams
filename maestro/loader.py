"""
Maestro knowledge store loader — reads ingested plan data into memory.

Loads the knowledge_store directory structure into a single in-memory dict
for fast querying by the tools module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .config import get_store_path
from .utils import load_json


def load_project(
    store_path: str | Path | None = None,
    project_name: str | None = None,
) -> dict[str, Any] | None:
    """
    Load a project from knowledge_store/ into memory.

    Args:
        store_path: Path to knowledge_store directory. If None, uses config default.
        project_name: Specific project to load. If None, loads the first found.

    Returns:
        Project dict with pages, pointers, index, and metadata. None if not found.
    """
    store = Path(store_path) if store_path else get_store_path()

    if not store.exists():
        print(f"No knowledge_store at {store}. Run: maestro ingest <folder>", file=sys.stderr)
        return None

    if project_name:
        project_dir = store / project_name
        if not project_dir.exists() or not project_dir.is_dir():
            print(f"Project '{project_name}' not found in {store}", file=sys.stderr)
            return None
    else:
        projects = [d for d in sorted(store.iterdir(), key=lambda p: p.name.lower()) if d.is_dir()]
        if not projects:
            print(f"No projects in {store}. Run: maestro ingest <folder>", file=sys.stderr)
            return None
        project_dir = projects[0]

    project = load_json(project_dir / "project.json")
    if not isinstance(project, dict):
        project = {}

    project.setdefault("name", project_dir.name)
    project.setdefault("source_path", "")
    project.setdefault("total_pages", 0)
    project["_dir"] = str(project_dir)

    # Load aggregated index
    index_data = load_json(project_dir / "index.json")
    if not isinstance(index_data, dict):
        index_data = {}
    project["index"] = index_data

    # Load pages
    project["pages"] = {}
    pages_dir = project_dir / "pages"
    if pages_dir.exists():
        for page_dir in sorted(pages_dir.iterdir(), key=lambda p: p.name.lower()):
            if not page_dir.is_dir():
                continue
            _load_page(project, page_dir)

    # Derive disciplines
    derived = sorted({
        str(p.get("discipline", "General")).strip() or "General"
        for p in project["pages"].values()
    })
    existing = project.get("disciplines")
    if isinstance(existing, list) and existing:
        project["disciplines"] = sorted(set(str(d).strip() for d in existing if str(d).strip()))
    else:
        project["disciplines"] = derived

    page_count = len(project["pages"])
    pointer_count = sum(len(p.get("pointers", {})) for p in project["pages"].values())
    print(f"Loaded: {project['name']} — {page_count} pages, {pointer_count} pointers", file=sys.stderr)
    return project


def _load_page(project: dict[str, Any], page_dir: Path):
    """Load a single page directory into the project dict."""
    page_name = page_dir.name
    page: dict[str, Any] = {
        "name": page_name,
        "path": str(page_dir),
        "sheet_reflection": "",
        "page_type": "unknown",
        "discipline": "General",
        "index": {},
        "cross_references": [],
        "regions": [],
        "pointers": {},
    }

    # Load Pass 1 data
    pass1 = load_json(page_dir / "pass1.json")
    if isinstance(pass1, dict):
        page["sheet_reflection"] = pass1.get("sheet_reflection", "")
        page["page_type"] = pass1.get("page_type", "unknown")
        page["discipline"] = pass1.get("discipline", "General") or "General"
        page["index"] = pass1.get("index", {}) if isinstance(pass1.get("index"), dict) else {}
        page["cross_references"] = (
            pass1.get("cross_references", [])
            if isinstance(pass1.get("cross_references"), list)
            else []
        )
        page["regions"] = (
            pass1.get("regions", [])
            if isinstance(pass1.get("regions"), list)
            else []
        )
        page["sheet_info"] = pass1.get("sheet_info", {})

    # Load Pass 2 pointers
    pointers_dir = page_dir / "pointers"
    if pointers_dir.exists():
        for pointer_dir in sorted(pointers_dir.iterdir(), key=lambda p: p.name.lower()):
            if not pointer_dir.is_dir():
                continue
            region_id = pointer_dir.name
            pointer_data = load_json(pointer_dir / "pass2.json")
            if not isinstance(pointer_data, dict):
                pointer_data = {}
            pointer_data.setdefault("content_markdown", "")
            pointer_data["crop_path"] = str(pointer_dir / "crop.png")
            page["pointers"][region_id] = pointer_data

    project["pages"][page_name] = page


def resolve_page(project: dict[str, Any], page_name: str) -> dict[str, Any] | None:
    """
    Fuzzy-match a page name within a project.

    Tries: exact match → prefix match → substring match.
    Returns None if no match found.
    """
    pages = project.get("pages", {})

    # Exact match
    if page_name in pages:
        return pages[page_name]

    normalized = page_name.replace(".", "_").replace("-", "_").replace(" ", "_").strip("_")

    # Prefix match
    candidates = [
        (n, p) for n, p in pages.items()
        if n.startswith(normalized) or n.startswith(normalized + "_")
    ]
    if len(candidates) == 1:
        return candidates[0][1]

    # Substring match
    if not candidates:
        lower = normalized.lower()
        candidates = [(n, p) for n, p in pages.items() if lower in n.lower()]

    if candidates:
        return candidates[0][1]
    return None
