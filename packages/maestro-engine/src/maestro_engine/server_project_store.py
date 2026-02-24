"""Project store loading helpers for server runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import load_json, slugify


def load_page(proj: dict[str, Any], page_dir: Path) -> dict[str, Any] | None:
    page_name = page_dir.name
    page: dict[str, Any] = {
        "name": page_name,
        "path": str(page_dir),
        "page_type": "unknown",
        "discipline": "General",
        "sheet_reflection": "",
        "index": {},
        "cross_references": [],
        "regions": [],
        "pointers": {},
    }

    pass1 = load_json(page_dir / "pass1.json")
    if isinstance(pass1, dict):
        page["page_type"] = pass1.get("page_type", "unknown")
        page["discipline"] = pass1.get("discipline", "General") or "General"
        page["sheet_reflection"] = pass1.get("sheet_reflection", "")
        page["index"] = pass1.get("index", {}) if isinstance(pass1.get("index"), dict) else {}
        page["cross_references"] = pass1.get("cross_references", []) if isinstance(pass1.get("cross_references"), list) else []
        page["regions"] = pass1.get("regions", []) if isinstance(pass1.get("regions"), list) else []
        page["sheet_info"] = pass1.get("sheet_info", {})

    pointers_dir = page_dir / "pointers"
    if pointers_dir.exists():
        for pointer_dir in sorted(pointers_dir.iterdir(), key=lambda p: p.name.lower()):
            if not pointer_dir.is_dir():
                continue
            region_id = pointer_dir.name
            pass2_path = pointer_dir / "pass2.json"
            if pass2_path.exists():
                try:
                    pointer_data = load_json(pass2_path)
                    if not isinstance(pointer_data, dict):
                        pointer_data = {}
                    pointer_data.setdefault("content_markdown", "")
                    page["pointers"][region_id] = pointer_data
                except Exception:
                    pass

    proj["pages"][page_name] = page
    proj["disciplines"] = sorted(
        {
            str(p.get("discipline", "General")).strip() or "General"
            for p in proj["pages"].values()
        }
    )
    return page


def load_project(project_dir: Path, slug: str) -> dict[str, Any]:
    project_meta = load_json(project_dir / "project.json")
    project_name = project_dir.name
    if isinstance(project_meta, dict):
        maybe_name = project_meta.get("name")
        if isinstance(maybe_name, str) and maybe_name.strip():
            project_name = maybe_name.strip()

    proj: dict[str, Any] = {
        "name": project_name,
        "slug": slug,
        "path": str(project_dir),
        "pages": {},
    }

    pages_dir = project_dir / "pages"
    if pages_dir.exists():
        for page_dir in sorted(pages_dir.iterdir(), key=lambda p: p.name.lower()):
            if not page_dir.is_dir():
                continue
            if not (page_dir / "pass1.json").exists():
                continue
            load_page(proj, page_dir)

    proj["disciplines"] = sorted(
        {
            str(p.get("discipline", "General")).strip() or "General"
            for p in proj["pages"].values()
        }
    )

    return proj


def _is_project_dir(path: Path) -> bool:
    return path.is_dir() and (path / "project.json").exists()


def _discover_project_dirs(store_path: Path) -> list[Path]:
    root = Path(store_path)
    if not root.exists():
        return []
    if _is_project_dir(root):
        return [root]
    projects: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if _is_project_dir(child):
            projects.append(child)
    return projects


def load_all_projects(store_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    projects: dict[str, dict[str, Any]] = {}
    project_dir_slug_index: dict[str, str] = {}

    if not store_path.exists():
        return projects, project_dir_slug_index

    for project_dir in _discover_project_dirs(store_path):
        project_meta = load_json(project_dir / "project.json")
        if isinstance(project_meta, dict):
            raw = str(project_meta.get("slug", "")).strip()
            slug = slugify(raw) if raw else slugify(project_dir.name)
        else:
            slug = slugify(project_dir.name)
        project_dir_slug_index[project_dir.name] = slug
        projects[slug] = load_project(project_dir, slug)

    return projects, project_dir_slug_index
