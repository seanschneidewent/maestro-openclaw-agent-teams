"""Fleet registry ownership and normalization helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

REGISTRY_VERSION = 1

DiscoverProjectDirsFn = Callable[[Path], list[Path]]
BuildProjectSnapshotFn = Callable[[Path], dict[str, Any]]
LoadJsonFn = Callable[..., Any]
SaveJsonFn = Callable[[Path, Any], None]
ProjectIndexTimestampFn = Callable[[Path], str]
NowIsoFn = Callable[[], str]


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
    save_json_fn(fleet_registry_path(store_root), registry)


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
    existing = load_fleet_registry(root, load_json_fn=load_json_fn)
    existing_by_slug = {
        item["project_slug"]: item for item in existing.get("projects", []) if isinstance(item, dict)
    }

    synced: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for project_dir in discover_project_dirs_fn(root):
        snapshot = build_project_snapshot_fn(project_dir)
        slug = str(snapshot.get("slug", "")).strip()
        if not slug:
            continue

        project_data = load_json_fn(project_dir / "project.json")
        if not isinstance(project_data, dict):
            project_data = {}

        existing_entry = existing_by_slug.get(slug, {})
        entry = {
            "project_slug": slug,
            "project_name": str(snapshot.get("name", "")).strip() or str(existing_entry.get("project_name", slug)),
            "project_dir_name": project_dir.name,
            "project_store_path": str(project_dir.resolve()),
            "maestro_agent_id": str(existing_entry.get("maestro_agent_id", f"maestro-project-{slug}")),
            "ingest_input_root": str(existing_entry.get("ingest_input_root", "")).strip(),
            "superintendent": str(existing_entry.get("superintendent", "Unknown")).strip() or "Unknown",
            "assignee": str(existing_entry.get("assignee", "Unassigned")).strip() or "Unassigned",
            "status": str(snapshot.get("status", existing_entry.get("status", "active"))),
            "last_ingest_at": (
                str(project_data.get("ingested_at", "")).strip()
                or str(existing_entry.get("last_ingest_at", "")).strip()
            ),
            "last_index_at": project_index_timestamp_fn(project_dir)
            or str(existing_entry.get("last_index_at", "")).strip(),
            "last_updated": (
                str(snapshot.get("last_updated", "")).strip()
                or str(existing_entry.get("last_updated", "")).strip()
            ),
            "telegram_bot_username": normalize_bot_username(existing_entry.get("telegram_bot_username")),
            "telegram_bot_display_name": clean_registry_text(existing_entry.get("telegram_bot_display_name")),
            "last_conversation_at": clean_registry_text(existing_entry.get("last_conversation_at")),
        }
        display_name, source, handle = resolve_node_identity(entry)
        entry["node_display_name"] = display_name
        entry["node_identity_source"] = source
        entry["node_handle"] = handle
        synced.append(entry)
        seen_slugs.add(slug)

    for slug, item in existing_by_slug.items():
        if slug in seen_slugs:
            continue
        archived = dict(item)
        archived["status"] = "archived"
        display_name, source, handle = resolve_node_identity(archived)
        archived["node_display_name"] = display_name
        archived["node_identity_source"] = source
        archived["node_handle"] = handle
        synced.append(archived)

    synced.sort(key=lambda x: x.get("project_name", "").lower())
    core_registry = {
        "version": REGISTRY_VERSION,
        "store_root": str(root),
        "projects": synced,
    }
    changed = not registries_equal(existing, core_registry)
    registry = {
        "version": REGISTRY_VERSION,
        "updated_at": now_iso_fn() if changed else str(existing.get("updated_at", "")),
        "store_root": str(root),
        "projects": synced,
    }
    if not registry["updated_at"]:
        registry["updated_at"] = now_iso_fn()

    if not dry_run and changed:
        save_fleet_registry(root, registry, save_json_fn=save_json_fn)

    return registry


def find_registry_project(registry: dict[str, Any], project_slug: str) -> dict[str, Any] | None:
    needle = project_slug.strip().lower()
    for item in registry.get("projects", []):
        if not isinstance(item, dict):
            continue
        slug = str(item.get("project_slug", "")).strip().lower()
        if slug == needle:
            return item
    return None
