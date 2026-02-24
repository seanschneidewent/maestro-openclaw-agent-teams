"""Legacy migration helpers for Maestro Solo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from maestro_engine.utils import load_json, save_json

from .install_state import load_install_state, save_install_state, solo_home


console = Console()


def _legacy_state_path() -> Path:
    return Path.home() / ".maestro" / "install.json"


def _legacy_openclaw_path() -> Path:
    return Path.home() / ".openclaw" / "openclaw.json"


def _legacy_license_paths() -> tuple[Path, Path]:
    home = Path.home()
    return (
        home / ".maestro" / "license.json",
        home / ".maestro-solo" / "license.json",
    )


def _legacy_workspace_from_openclaw() -> str:
    config = load_json(_legacy_openclaw_path(), default={})
    if not isinstance(config, dict):
        return ""

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    items = agents.get("list", []) if isinstance(agents.get("list"), list) else []

    for agent_id in ("maestro-solo-personal", "maestro-personal", "maestro"):
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "")).strip() == agent_id:
                workspace = str(item.get("workspace", "")).strip()
                if workspace:
                    return workspace

    for item in items:
        if not isinstance(item, dict) or not bool(item.get("default")):
            continue
        workspace = str(item.get("workspace", "")).strip()
        if workspace:
            return workspace

    return ""


def _copy_if_missing(src: Path, dst: Path) -> tuple[bool, str]:
    if not src.exists():
        return False, f"skip: missing {src}"
    if dst.exists():
        return False, f"skip: already exists {dst}"
    payload = load_json(src, default={})
    if not isinstance(payload, dict):
        return False, f"skip: invalid JSON {src}"
    save_json(dst, payload)
    return True, f"copied {src} -> {dst}"


def migrate_legacy(*, dry_run: bool = False) -> dict[str, Any]:
    current = load_install_state()
    legacy_state = load_json(_legacy_state_path(), default={})
    if not isinstance(legacy_state, dict):
        legacy_state = {}

    workspace_root = str(current.get("workspace_root", "")).strip()
    if not workspace_root:
        workspace_root = str(legacy_state.get("workspace_root", "")).strip() or _legacy_workspace_from_openclaw()

    store_root = str(current.get("store_root", "")).strip()
    if not store_root:
        store_root = (
            str(legacy_state.get("store_root", "")).strip()
            or str(legacy_state.get("fleet_store_root", "")).strip()
        )

    active_project_slug = str(current.get("active_project_slug", "")).strip() or str(legacy_state.get("active_project_slug", "")).strip()
    active_project_name = str(current.get("active_project_name", "")).strip() or str(legacy_state.get("active_project_name", "")).strip()

    updates = {
        "workspace_root": workspace_root,
        "store_root": store_root,
        "active_project_slug": active_project_slug,
        "active_project_name": active_project_name,
    }

    changed = False
    merged = dict(current)
    for key, value in updates.items():
        if not value:
            continue
        if str(merged.get(key, "")).strip() == str(value).strip():
            continue
        merged[key] = value
        changed = True

    file_ops: list[str] = []
    copied_files: list[str] = []
    solo_root = solo_home()

    if not dry_run:
        solo_root.mkdir(parents=True, exist_ok=True)

    for legacy_license in _legacy_license_paths():
        dst = solo_root / "license.json"
        if dry_run:
            if legacy_license.exists() and not dst.exists():
                file_ops.append(f"would copy {legacy_license} -> {dst}")
            continue
        copied, detail = _copy_if_missing(legacy_license, dst)
        file_ops.append(detail)
        if copied:
            copied_files.append(str(dst))
            break

    if changed and not dry_run:
        save_install_state(merged)

    return {
        "changed": changed,
        "dry_run": dry_run,
        "state_path": str(solo_root / "install.json"),
        "state": merged if changed else current,
        "file_ops": file_ops,
        "copied_files": copied_files,
    }


def print_migration_report(report: dict[str, Any]):
    table = Table(show_header=False)
    table.add_row("changed", str(bool(report.get("changed"))))
    table.add_row("dry_run", str(bool(report.get("dry_run"))))
    table.add_row("state_path", str(report.get("state_path", "")))

    state = report.get("state", {}) if isinstance(report.get("state"), dict) else {}
    table.add_row("workspace_root", str(state.get("workspace_root", "")))
    table.add_row("store_root", str(state.get("store_root", "")))
    table.add_row("active_project_slug", str(state.get("active_project_slug", "")))
    table.add_row("active_project_name", str(state.get("active_project_name", "")))
    console.print(table)

    ops = report.get("file_ops", []) if isinstance(report.get("file_ops"), list) else []
    if ops:
        console.print("\nFile operations:")
        for op in ops:
            console.print(f"- {op}")
