#!/usr/bin/env python3
"""Audit and sanitize Maestro knowledge-store datasets."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CANONICAL_TOP_LEVEL_DIRS = {"pages", "workspaces", "notes", "schedule"}
CANONICAL_TOP_LEVEL_FILES = {"project.json", "index.json", "license.json"}
SCHEDULE_FILES = {
    "maestro_schedule.json",
    "current_update.json",
    "lookahead.json",
    "baseline.json",
    "calendar_sync.json",
}


@dataclass
class ProjectScan:
    project_dir: Path
    project_name: str
    page_count: int
    pointer_count: int
    workspace_count: int
    workspace_page_refs: int
    missing_workspace_pages: int
    missing_selected_pointers: int
    missing_pass1: int
    missing_page_png: int
    missing_pass2: int
    missing_crop: int
    extra_top_level_dirs: list[str]
    extra_top_level_files: list[str]
    notes_present: bool
    schedule_files_present: list[str]
    total_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "project_name": self.project_name,
            "page_count": self.page_count,
            "pointer_count": self.pointer_count,
            "workspace_count": self.workspace_count,
            "workspace_page_refs": self.workspace_page_refs,
            "missing_workspace_pages": self.missing_workspace_pages,
            "missing_selected_pointers": self.missing_selected_pointers,
            "missing_pass1": self.missing_pass1,
            "missing_page_png": self.missing_page_png,
            "missing_pass2": self.missing_pass2,
            "missing_crop": self.missing_crop,
            "extra_top_level_dirs": self.extra_top_level_dirs,
            "extra_top_level_files": self.extra_top_level_files,
            "notes_present": self.notes_present,
            "schedule_files_present": self.schedule_files_present,
            "total_bytes": self.total_bytes,
        }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _iter_project_dirs(store_or_project: Path) -> list[Path]:
    if (store_or_project / "project.json").exists():
        return [store_or_project]
    projects: list[Path] = []
    if not store_or_project.exists():
        return projects
    for child in sorted(store_or_project.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir() and (child / "project.json").exists():
            projects.append(child)
    return projects


def _total_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            file_path = Path(root) / name
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    return total


def _scan_project(project_dir: Path) -> ProjectScan:
    project_meta = _load_json(project_dir / "project.json")
    project_name = str(project_meta.get("name", project_dir.name)).strip() or project_dir.name

    pages_dir = project_dir / "pages"
    page_dirs = [d for d in sorted(pages_dir.iterdir(), key=lambda p: p.name.lower())] if pages_dir.exists() else []
    ingest_pages = [d for d in page_dirs if d.is_dir() and (d / "pass1.json").exists()]

    missing_pass1 = 0
    missing_page_png = 0
    pointer_count = 0
    missing_pass2 = 0
    missing_crop = 0

    pointer_ids_by_page: dict[str, set[str]] = {}
    for page_dir in ingest_pages:
        if not (page_dir / "pass1.json").exists():
            missing_pass1 += 1
        if not (page_dir / "page.png").exists():
            missing_page_png += 1

        ptr_ids: set[str] = set()
        pointers_dir = page_dir / "pointers"
        if pointers_dir.exists():
            for pointer_dir in sorted(pointers_dir.iterdir(), key=lambda p: p.name.lower()):
                if not pointer_dir.is_dir():
                    continue
                pointer_count += 1
                region_id = pointer_dir.name
                if not (pointer_dir / "pass2.json").exists():
                    missing_pass2 += 1
                else:
                    ptr_ids.add(region_id)
                if not (pointer_dir / "crop.png").exists():
                    missing_crop += 1
        pointer_ids_by_page[page_dir.name] = ptr_ids

    workspace_count = 0
    workspace_page_refs = 0
    missing_workspace_pages = 0
    missing_selected_pointers = 0

    workspaces_root = project_dir / "workspaces"
    if workspaces_root.exists():
        for ws_file in sorted(workspaces_root.glob("*/workspace.json")):
            workspace_count += 1
            workspace = _load_json(ws_file)
            pages = workspace.get("pages", [])
            if not isinstance(pages, list):
                continue
            for page_entry in pages:
                if not isinstance(page_entry, dict):
                    continue
                workspace_page_refs += 1
                page_name = str(page_entry.get("page_name", "")).strip()
                if not page_name or page_name not in pointer_ids_by_page:
                    missing_workspace_pages += 1
                    continue
                selected = page_entry.get("selected_pointers", [])
                if not isinstance(selected, list):
                    continue
                valid_ids = pointer_ids_by_page.get(page_name, set())
                for pointer_id in selected:
                    if str(pointer_id) not in valid_ids:
                        missing_selected_pointers += 1

    extra_top_level_dirs: list[str] = []
    extra_top_level_files: list[str] = []
    for entry in sorted(project_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name not in CANONICAL_TOP_LEVEL_DIRS:
                extra_top_level_dirs.append(entry.name)
        elif entry.is_file():
            if entry.name not in CANONICAL_TOP_LEVEL_FILES:
                extra_top_level_files.append(entry.name)

    notes_present = (project_dir / "notes" / "project_notes.json").exists()
    schedule_files_present = sorted(
        [name for name in SCHEDULE_FILES if (project_dir / "schedule" / name).exists()]
    )

    return ProjectScan(
        project_dir=project_dir,
        project_name=project_name,
        page_count=len(ingest_pages),
        pointer_count=pointer_count,
        workspace_count=workspace_count,
        workspace_page_refs=workspace_page_refs,
        missing_workspace_pages=missing_workspace_pages,
        missing_selected_pointers=missing_selected_pointers,
        missing_pass1=missing_pass1,
        missing_page_png=missing_page_png,
        missing_pass2=missing_pass2,
        missing_crop=missing_crop,
        extra_top_level_dirs=extra_top_level_dirs,
        extra_top_level_files=extra_top_level_files,
        notes_present=notes_present,
        schedule_files_present=schedule_files_present,
        total_bytes=_total_bytes(project_dir),
    )


def _print_human_scan(scan: ProjectScan):
    print(f"Project: {scan.project_name}")
    print(f"Path:    {scan.project_dir}")
    print(f"Size:    {scan.total_bytes:,} bytes")
    print(
        "Core:    "
        f"{scan.page_count} pages, {scan.pointer_count} pointers, "
        f"{scan.workspace_count} workspaces"
    )
    print(
        "Health:  "
        f"missing_pass1={scan.missing_pass1}, "
        f"missing_page_png={scan.missing_page_png}, "
        f"missing_pass2={scan.missing_pass2}, "
        f"missing_crop={scan.missing_crop}"
    )
    print(
        "Links:   "
        f"workspace_page_refs={scan.workspace_page_refs}, "
        f"missing_workspace_pages={scan.missing_workspace_pages}, "
        f"missing_selected_pointers={scan.missing_selected_pointers}"
    )
    extras = ", ".join(scan.extra_top_level_dirs + scan.extra_top_level_files) or "(none)"
    print(f"Extras:  {extras}")
    notes = "yes" if scan.notes_present else "no"
    schedule = ", ".join(scan.schedule_files_present) if scan.schedule_files_present else "(none)"
    print(f"Notes:   {notes}")
    print(f"Sched:   {schedule}")
    print("")


def _copy_file(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_project_canonical(source_project: Path, output_project: Path, keep_schedule: bool):
    for filename in ("project.json", "index.json", "license.json"):
        src = source_project / filename
        if src.exists():
            _copy_file(src, output_project / filename)

    pages_src = source_project / "pages"
    pages_out = output_project / "pages"
    if pages_src.exists():
        for page_dir in sorted(pages_src.iterdir(), key=lambda p: p.name.lower()):
            if not page_dir.is_dir():
                continue
            pass1 = page_dir / "pass1.json"
            if not pass1.exists():
                continue
            _copy_file(pass1, pages_out / page_dir.name / "pass1.json")
            page_png = page_dir / "page.png"
            if page_png.exists():
                _copy_file(page_png, pages_out / page_dir.name / "page.png")

            pointers_src = page_dir / "pointers"
            if pointers_src.exists():
                for pointer_dir in sorted(pointers_src.iterdir(), key=lambda p: p.name.lower()):
                    if not pointer_dir.is_dir():
                        continue
                    pass2 = pointer_dir / "pass2.json"
                    if pass2.exists():
                        _copy_file(
                            pass2,
                            pages_out / page_dir.name / "pointers" / pointer_dir.name / "pass2.json",
                        )
                    crop = pointer_dir / "crop.png"
                    if crop.exists():
                        _copy_file(
                            crop,
                            pages_out / page_dir.name / "pointers" / pointer_dir.name / "crop.png",
                        )

    workspaces_src = source_project / "workspaces"
    workspaces_out = output_project / "workspaces"
    if workspaces_src.exists():
        index_path = workspaces_src / "_index.json"
        if index_path.exists():
            _copy_file(index_path, workspaces_out / "_index.json")

        for workspace_json in sorted(workspaces_src.glob("*/workspace.json")):
            ws_dir = workspace_json.parent
            ws_slug = ws_dir.name
            ws_payload = _load_json(workspace_json)
            _copy_file(workspace_json, workspaces_out / ws_slug / "workspace.json")

            generated_dir = ws_dir / "generated_images"
            if not generated_dir.exists():
                continue

            referenced_files: set[str] = set()
            generated_images = ws_payload.get("generated_images", [])
            if isinstance(generated_images, list):
                for entry in generated_images:
                    if not isinstance(entry, dict):
                        continue
                    filename = str(entry.get("filename", "")).strip()
                    if filename:
                        referenced_files.add(filename)

            if referenced_files:
                for filename in sorted(referenced_files):
                    src = generated_dir / filename
                    if src.exists() and src.is_file():
                        _copy_file(
                            src,
                            workspaces_out / ws_slug / "generated_images" / filename,
                        )
            else:
                for src in sorted(generated_dir.iterdir(), key=lambda p: p.name.lower()):
                    if src.is_file() and not src.name.startswith("."):
                        _copy_file(
                            src,
                            workspaces_out / ws_slug / "generated_images" / src.name,
                        )

    notes_file = source_project / "notes" / "project_notes.json"
    if notes_file.exists():
        _copy_file(notes_file, output_project / "notes" / "project_notes.json")

    if keep_schedule:
        schedule_src = source_project / "schedule"
        if schedule_src.exists():
            for filename in sorted(SCHEDULE_FILES):
                src = schedule_src / filename
                if src.exists():
                    _copy_file(src, output_project / "schedule" / filename)


def _sanitize_store(
    source: Path,
    output: Path,
    keep_schedule: bool,
    force: bool,
):
    source_projects = _iter_project_dirs(source)
    if not source_projects:
        raise SystemExit(f"No project.json found under: {source}")

    if output.exists():
        if not force:
            raise SystemExit(f"Output exists: {output} (use --force to replace)")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    source_is_project = (source / "project.json").exists()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "output": str(output),
        "keep_schedule": keep_schedule,
        "projects": [],
    }

    for source_project in source_projects:
        target_project = output if source_is_project else output / source_project.name
        _copy_project_canonical(source_project, target_project, keep_schedule=keep_schedule)
        scan = _scan_project(target_project)
        report["projects"].append(scan.as_dict())

    (output / "SANITIZE_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote sanitized store: {output}")
    print(f"Report: {output / 'SANITIZE_REPORT.json'}")


def _cmd_audit(args: argparse.Namespace) -> int:
    source = Path(args.path).expanduser().resolve()
    projects = _iter_project_dirs(source)
    if not projects:
        print(f"No project.json found under: {source}")
        return 1

    scans = [_scan_project(project_dir) for project_dir in projects]
    if args.json:
        print(json.dumps({"path": str(source), "projects": [scan.as_dict() for scan in scans]}, indent=2))
    else:
        print(f"Store: {source}")
        print(f"Projects detected: {len(scans)}\n")
        for scan in scans:
            _print_human_scan(scan)
    return 0


def _cmd_sanitize(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    _sanitize_store(
        source=source,
        output=output,
        keep_schedule=bool(args.keep_schedule),
        force=bool(args.force),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit/sanitize Maestro knowledge stores.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit knowledge-store structure and integrity.")
    audit.add_argument("path", help="Store root or project root path.")
    audit.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    audit.set_defaults(func=_cmd_audit)

    sanitize = sub.add_parser("sanitize", help="Create a trimmed, canonical store copy.")
    sanitize.add_argument("source", help="Source store root or project root.")
    sanitize.add_argument("output", help="Output path for sanitized copy.")
    sanitize.add_argument(
        "--keep-schedule",
        action="store_true",
        help="Preserve schedule/*.json files used by schedule APIs.",
    )
    sanitize.add_argument(
        "--force",
        action="store_true",
        help="Replace output path if it already exists.",
    )
    sanitize.set_defaults(func=_cmd_sanitize)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
