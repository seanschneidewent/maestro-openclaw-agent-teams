"""Fleet registry ownership and normalization helpers."""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any, Callable

REGISTRY_VERSION = 1

DiscoverProjectDirsFn = Callable[[Path], list[Path]]
BuildProjectSnapshotFn = Callable[[Path], dict[str, Any]]
LoadJsonFn = Callable[..., Any]
SaveJsonFn = Callable[[Path, Any], None]
ProjectIndexTimestampFn = Callable[[Path], str]
NowIsoFn = Callable[[], str]


def _load_package_command_center_module():
    try:
        from maestro_fleet import command_center as command_center_module
        return command_center_module
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[3]
        package_src = repo_root / "packages" / "maestro-fleet" / "src"
        if package_src.exists() and str(package_src) not in sys.path:
            sys.path.insert(0, str(package_src))
        from maestro_fleet import command_center as command_center_module
        return command_center_module


def fleet_registry_path(store_root: Path) -> Path:
    return Path(store_root).resolve() / ".command_center" / "fleet_registry.json"


def default_registry(store_root: Path) -> dict[str, Any]:
    return {
        "version": REGISTRY_VERSION,
        "updated_at": "",
        "store_root": str(Path(store_root).resolve()),
        "projects": [],
    }


def clean_registry_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def normalize_bot_username(value: Any) -> str:
    username = clean_registry_text(value)
    if not username:
        return ""
    if not username.startswith("@"):  # normalize raw usernames for display/routing
        username = f"@{username.lstrip('@')}"
    return username


def resolve_node_identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    username = normalize_bot_username(entry.get("telegram_bot_username"))
    display = clean_registry_text(entry.get("telegram_bot_display_name"))
    assignee = clean_registry_text(entry.get("assignee"))
    project_name = clean_registry_text(entry.get("project_name"))
    slug = clean_registry_text(entry.get("project_slug"))

    if username:
        return username, "telegram_bot", username
    if display:
        return display, "telegram_bot", ""
    if assignee and assignee.lower() != "unassigned":
        return assignee, "assignee", ""
    if project_name:
        return project_name, "project", ""
    return slug or "Project Node", "project", ""


def load_fleet_registry(store_root: Path, *, load_json_fn: LoadJsonFn) -> dict[str, Any]:
    root = Path(store_root).resolve()
    fallback_registry = default_registry(root)
    path = fleet_registry_path(root)
    payload = load_json_fn(path, default=fallback_registry)
    if not isinstance(payload, dict):
        return fallback_registry

    projects = payload.get("projects")
    if not isinstance(projects, list):
        projects = []

    normalized: list[dict[str, Any]] = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        slug = item.get("project_slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        name = item.get("project_name")
        dir_name = item.get("project_dir_name")
        store_path = item.get("project_store_path")
        normalized_entry = {
            "project_slug": slug.strip(),
            "project_name": name.strip() if isinstance(name, str) and name.strip() else slug.strip(),
            "project_dir_name": dir_name.strip() if isinstance(dir_name, str) and dir_name.strip() else slug.strip(),
            "project_store_path": (
                store_path.strip()
                if isinstance(store_path, str) and store_path.strip()
                else str(root / (dir_name if isinstance(dir_name, str) and dir_name.strip() else slug.strip()))
            ),
            "maestro_agent_id": (
                item.get("maestro_agent_id")
                if isinstance(item.get("maestro_agent_id"), str) and item.get("maestro_agent_id").strip()
                else f"maestro-project-{slug.strip()}"
            ),
            "ingest_input_root": (
                item.get("ingest_input_root").strip()
                if isinstance(item.get("ingest_input_root"), str) and item.get("ingest_input_root").strip()
                else ""
            ),
            "superintendent": (
                item.get("superintendent").strip()
                if isinstance(item.get("superintendent"), str) and item.get("superintendent").strip()
                else "Unknown"
            ),
            "assignee": (
                item.get("assignee").strip()
                if isinstance(item.get("assignee"), str) and item.get("assignee").strip()
                else "Unassigned"
            ),
            "status": (
                item.get("status").strip()
                if isinstance(item.get("status"), str) and item.get("status").strip()
                else "active"
            ),
            "last_ingest_at": (
                item.get("last_ingest_at").strip()
                if isinstance(item.get("last_ingest_at"), str) and item.get("last_ingest_at").strip()
                else ""
            ),
            "last_index_at": (
                item.get("last_index_at").strip()
                if isinstance(item.get("last_index_at"), str) and item.get("last_index_at").strip()
                else ""
            ),
            "last_updated": (
                item.get("last_updated").strip()
                if isinstance(item.get("last_updated"), str) and item.get("last_updated").strip()
                else ""
            ),
            "telegram_bot_username": normalize_bot_username(item.get("telegram_bot_username")),
            "telegram_bot_display_name": clean_registry_text(item.get("telegram_bot_display_name")),
            "last_conversation_at": clean_registry_text(item.get("last_conversation_at")),
        }
        display_name, source, handle = resolve_node_identity(normalized_entry)
        normalized_entry["node_display_name"] = display_name
        normalized_entry["node_identity_source"] = source
        normalized_entry["node_handle"] = handle
        normalized.append(normalized_entry)

    return {
        "version": int(payload.get("version", REGISTRY_VERSION)),
        "updated_at": payload.get("updated_at", ""),
        "store_root": str(root),
        "projects": sorted(normalized, key=lambda x: x["project_name"].lower()),
    }


def registries_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_core = {
        "version": int(left.get("version", REGISTRY_VERSION)),
        "store_root": str(left.get("store_root", "")),
        "projects": left.get("projects", []),
    }
    right_core = {
        "version": int(right.get("version", REGISTRY_VERSION)),
        "store_root": str(right.get("store_root", "")),
        "projects": right.get("projects", []),
    }
    return json.dumps(left_core, sort_keys=True) == json.dumps(right_core, sort_keys=True)


def save_fleet_registry(store_root: Path, registry: dict[str, Any], *, save_json_fn: SaveJsonFn):
    _ = (store_root, registry, save_json_fn)
    warnings.warn(
        "save_fleet_registry() is deprecated; Fleet registry state is now derived from OpenClaw config, workspace env, and project.json metadata.",
        DeprecationWarning,
        stacklevel=2,
    )


def sync_fleet_registry(
    store_root: Path,
    *,
    discover_project_dirs_fn: DiscoverProjectDirsFn,
    build_project_snapshot_fn: BuildProjectSnapshotFn,
    load_json_fn: LoadJsonFn,
    save_json_fn: SaveJsonFn,
    project_index_timestamp_fn: ProjectIndexTimestampFn,
    now_iso_fn: NowIsoFn,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    _ = (
        discover_project_dirs_fn,
        build_project_snapshot_fn,
        load_json_fn,
        save_json_fn,
        project_index_timestamp_fn,
        now_iso_fn,
        dry_run,
    )
    command_center_module = _load_package_command_center_module()
    return command_center_module.build_derived_registry(root)


def find_registry_project(registry: dict[str, Any], project_slug: str) -> dict[str, Any] | None:
    needle = project_slug.strip().lower()
    for item in registry.get("projects", []):
        if not isinstance(item, dict):
            continue
        slug = str(item.get("project_slug", "")).strip().lower()
        if slug == needle:
            return item
    return None
