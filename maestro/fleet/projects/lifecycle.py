"""Fleet project lifecycle helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from ...fleet_constants import (
    DEFAULT_PROJECT_MODEL,
    canonicalize_model,
    default_model_from_agents as default_fleet_model_from_agents,
)

NATIVE_PLUGIN_ID = "maestro-native-tools"
_PROJECT_METADATA_KEY = "maestro"

CreateControlPayloadFn = Callable[[Path, str], dict[str, Any]]
SyncFleetRegistryFn = Callable[[Path], dict[str, Any]]
FindRegistryProjectFn = Callable[[dict[str, Any], str], dict[str, Any] | None]
ResolveNodeIdentityFn = Callable[[dict[str, Any]], tuple[str, str, str]]
RegisterProjectAgentFn = Callable[..., dict[str, Any]]
LoadOpenClawConfigFn = Callable[[Path | None], tuple[dict[str, Any], Path]]
ResolveCompanyAgentFn = Callable[[dict[str, Any]], dict[str, Any]]
OpenClawWorkspaceRootFn = Callable[..., Path]
ResolveProfileFn = Callable[..., str]
EnsureTelegramBindingsFn = Callable[[dict[str, Any]], list[str]]
LoadJsonFn = Callable[[Path], Any]
SaveJsonFn = Callable[[Path, Any], None]
NowIsoFn = Callable[[], str]
SlugifyFn = Callable[[str], str]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_input_root(value: Any) -> str:
    clean = _clean(value)
    if not clean:
        return ""
    return str(Path(clean).expanduser().resolve())


def _load_project_json(project_dir: Path) -> dict[str, Any]:
    project_json_path = project_dir / "project.json"
    if not project_json_path.exists():
        return {}
    try:
        payload = json.loads(project_json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_project_metadata(project_dir: Path, *, save_json_fn: SaveJsonFn, **fields: Any) -> None:
    project_json_path = project_dir / "project.json"
    payload = _load_project_json(project_dir)
    metadata = payload.get(_PROJECT_METADATA_KEY) if isinstance(payload.get(_PROJECT_METADATA_KEY), dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}

    changed = False
    for key, raw_value in fields.items():
        if raw_value is None:
            continue
        value = _normalize_input_root(raw_value) if key == "ingest_input_root" else _clean(raw_value)
        if not value:
            continue
        if metadata.get(key) == value:
            continue
        metadata[key] = value
        changed = True

    if not changed:
        return

    payload[_PROJECT_METADATA_KEY] = metadata
    save_json_fn(project_json_path, payload)


def _ensure_native_plugin_config(config: dict[str, Any]) -> bool:
    changed = False

    plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    entries = plugins.get("entries") if isinstance(plugins.get("entries"), dict) else {}
    entry = entries.get(NATIVE_PLUGIN_ID) if isinstance(entries.get(NATIVE_PLUGIN_ID), dict) else {}
    if entry.get("enabled") is not True:
        entry["enabled"] = True
        changed = True
    entries[NATIVE_PLUGIN_ID] = entry
    plugins["entries"] = entries

    allow = plugins.get("allow")
    if isinstance(allow, list):
        normalized = [str(item).strip() for item in allow if str(item).strip()]
        if NATIVE_PLUGIN_ID not in normalized:
            normalized.append(NATIVE_PLUGIN_ID)
            changed = True
        plugins["allow"] = normalized
    else:
        plugins["allow"] = [NATIVE_PLUGIN_ID]
        changed = True

    config["plugins"] = plugins
    return changed


def _native_extension_source() -> Path | None:
    repo_root = Path(__file__).resolve().parents[3]
    candidate = repo_root / "agent" / "extensions" / NATIVE_PLUGIN_ID
    return candidate if candidate.exists() else None


def _sync_native_extension(workspace_root: Path) -> bool:
    source = _native_extension_source()
    if source is None:
        return False

    destination = workspace_root / ".openclaw" / "extensions" / NATIVE_PLUGIN_ID
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return True


def default_model_from_agents(agent_list: list[dict[str, Any]]) -> str:
    return default_fleet_model_from_agents(agent_list, fallback=DEFAULT_PROJECT_MODEL)


def create_project_node(
    store_root: Path,
    project_name: str,
    *,
    slugify_fn: SlugifyFn,
    now_iso_fn: NowIsoFn,
    save_json_fn: SaveJsonFn,
    sync_fleet_registry_fn: SyncFleetRegistryFn,
    find_registry_project_fn: FindRegistryProjectFn,
    resolve_node_identity_fn: ResolveNodeIdentityFn,
    project_control_payload_fn: CreateControlPayloadFn,
    register_project_agent_fn: RegisterProjectAgentFn,
    project_slug: str | None = None,
    project_dir_name: str | None = None,
    ingest_input_root: str | None = None,
    superintendent: str | None = None,
    assignee: str | None = None,
    register_agent: bool = False,
    home_dir: Path | None = None,
    agent_model: str | None = None,
    telegram_bot_username: str | None = None,
    telegram_bot_display_name: str | None = None,
    normalize_bot_username_fn: Callable[[Any], str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    name = project_name.strip()
    slug = slugify_fn(project_slug or name)
    dir_name = (project_dir_name or slug).strip() or slug
    project_dir = root / dir_name
    now_iso = now_iso_fn()

    if (root / "project.json").exists() and root != project_dir:
        return {
            "ok": False,
            "error": (
                "Store root is currently a single-project layout. "
                "Use existing-project onboarding semantics for this store, "
                "or switch MAESTRO_STORE to a parent directory for multi-project mode."
            ),
            "project_slug": slug,
            "project_name": name,
            "project_dir": str(project_dir.resolve()),
            "dry_run": dry_run,
        }

    created = False
    if not project_dir.exists() and not dry_run:
        (project_dir / "pages").mkdir(parents=True, exist_ok=True)
        (project_dir / "workspaces").mkdir(parents=True, exist_ok=True)
        (project_dir / "schedule").mkdir(parents=True, exist_ok=True)
        (project_dir / "rfis").mkdir(parents=True, exist_ok=True)
        (project_dir / "submittals").mkdir(parents=True, exist_ok=True)
        (project_dir / "comms").mkdir(parents=True, exist_ok=True)
        (project_dir / "contracts").mkdir(parents=True, exist_ok=True)
        created = True

    project_json_path = project_dir / "project.json"
    if (not project_json_path.exists()) and (not dry_run):
        save_json_fn(
            project_json_path,
            {
                "name": name,
                "slug": slug,
                "total_pages": 0,
                "disciplines": [],
                "created_at": now_iso,
                "index_summary": {
                    "page_count": 0,
                    "pointer_count": 0,
                },
            },
        )

    index_json_path = project_dir / "index.json"
    if (not index_json_path.exists()) and (not dry_run):
        save_json_fn(
            index_json_path,
            {
                "summary": {
                    "page_count": 0,
                    "pointer_count": 0,
                    "unique_material_count": 0,
                    "unique_keyword_count": 0,
                },
                "generated": now_iso,
            },
        )

    normalized_username = ""
    if telegram_bot_username and normalize_bot_username_fn is not None:
        normalized_username = normalize_bot_username_fn(telegram_bot_username)
    elif telegram_bot_username:
        normalized_username = _clean(telegram_bot_username)

    if not dry_run:
        _save_project_metadata(
            project_dir,
            save_json_fn=save_json_fn,
            status="setup",
            ingest_input_root=ingest_input_root,
            superintendent=superintendent,
            assignee=assignee,
            telegram_bot_username=normalized_username,
            telegram_bot_display_name=telegram_bot_display_name,
            model=agent_model,
        )

    registry = sync_fleet_registry_fn(root)
    entry = find_registry_project_fn(registry, slug)
    if not entry:
        entry = {
            "project_slug": slug,
            "project_name": name,
            "project_dir_name": dir_name,
            "project_store_path": str(project_dir.resolve()),
            "maestro_agent_id": f"maestro-project-{slug}",
            "ingest_input_root": "",
            "superintendent": "Unknown",
            "assignee": "Unassigned",
            "status": "setup",
            "last_ingest_at": "",
            "last_index_at": "",
            "last_updated": "",
            "telegram_bot_username": "",
            "telegram_bot_display_name": "",
            "last_conversation_at": "",
        }

    if ingest_input_root:
        entry["ingest_input_root"] = str(Path(ingest_input_root).expanduser().resolve())
    if superintendent:
        entry["superintendent"] = superintendent.strip() or "Unknown"
    if assignee:
        entry["assignee"] = assignee.strip() or "Unassigned"
    if normalized_username:
        entry["telegram_bot_username"] = normalized_username
    if telegram_bot_display_name:
        entry["telegram_bot_display_name"] = telegram_bot_display_name.strip()
    display_name, source, handle = resolve_node_identity_fn(entry)
    entry["node_display_name"] = display_name
    entry["node_identity_source"] = source
    entry["node_handle"] = handle

    controls = project_control_payload_fn(root, slug)
    registration = None
    if register_agent:
        registration = register_project_agent_fn(
            store_root=root,
            project_slug=slug,
            project_name=name,
            project_store_path=str(project_dir.resolve()),
            home_dir=home_dir,
            dry_run=dry_run,
            model=agent_model,
        )
    return {
        "ok": True,
        "created_project_dir": created,
        "project_exists": project_dir.exists(),
        "project_dir": str(project_dir.resolve()),
        "project_slug": slug,
        "project_name": name,
        "dry_run": dry_run,
        "project": entry,
        "control": controls,
        "agent_registration": registration,
    }


def onboard_project_store(
    store_root: Path,
    source_path: str,
    *,
    load_json_fn: LoadJsonFn,
    save_json_fn: SaveJsonFn,
    slugify_fn: SlugifyFn,
    now_iso_fn: NowIsoFn,
    sync_fleet_registry_fn: SyncFleetRegistryFn,
    find_registry_project_fn: FindRegistryProjectFn,
    resolve_node_identity_fn: ResolveNodeIdentityFn,
    register_project_agent_fn: RegisterProjectAgentFn,
    build_ingest_command_fn: Callable[[Path, dict[str, Any], str | None, int], dict[str, Any]],
    build_ingest_preflight_fn: Callable[[Path, dict[str, Any], str | None], dict[str, Any]],
    resolve_network_urls_fn: Callable[..., dict[str, Any]],
    quote_path_fn: Callable[[str | Path], str],
    default_web_port: int,
    default_input_placeholder: str,
    project_name: str | None = None,
    project_slug: str | None = None,
    project_dir_name: str | None = None,
    ingest_input_root: str | None = None,
    superintendent: str | None = None,
    assignee: str | None = None,
    register_agent: bool = True,
    move_source: bool = True,
    home_dir: Path | None = None,
    agent_model: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Attach a pre-ingested project store into the active fleet in one operation."""
    root = Path(store_root).resolve()
    source_root = Path(source_path).expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        return {
            "ok": False,
            "error": f"Source path is not a directory: {source_root}",
        }

    source_project_dir = source_root if (source_root / "project.json").exists() else None
    if source_project_dir is None:
        candidates = [
            child for child in source_root.iterdir()
            if child.is_dir() and (child / "project.json").exists()
        ]
        if len(candidates) == 1:
            source_project_dir = candidates[0]
        else:
            return {
                "ok": False,
                "error": (
                    "Source path must contain project.json directly or have exactly one "
                    "child project directory containing project.json"
                ),
            }

    if (root / "project.json").exists() and source_project_dir != root:
        return {
            "ok": False,
            "error": (
                "Store root is currently a single-project layout. Use that project as the store root "
                "or switch MAESTRO_STORE to a parent directory for multi-project mode."
            ),
        }

    source_meta = load_json_fn(source_project_dir / "project.json")
    if not isinstance(source_meta, dict):
        source_meta = {}

    resolved_name = (
        (project_name or str(source_meta.get("name", "")).strip() or source_project_dir.name).strip()
    )
    resolved_slug = slugify_fn(
        (project_slug or str(source_meta.get("slug", "")).strip() or resolved_name)
    )
    resolved_dir_name = (project_dir_name or resolved_slug).strip() or resolved_slug

    if source_project_dir == root:
        destination_dir = root
        relocation_mode = "in_place"
    else:
        destination_dir = (root / resolved_dir_name).resolve()
        relocation_mode = "move" if move_source else "copy"

    if not root.exists() and not dry_run:
        root.mkdir(parents=True, exist_ok=True)

    if destination_dir.exists() and source_project_dir != destination_dir:
        return {
            "ok": False,
            "error": f"Destination already exists: {destination_dir}",
        }

    if source_project_dir != destination_dir and not dry_run:
        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        if move_source:
            shutil.move(str(source_project_dir), str(destination_dir))
        else:
            shutil.copytree(source_project_dir, destination_dir)

    if not dry_run:
        destination_project = load_json_fn(destination_dir / "project.json")
        if not isinstance(destination_project, dict):
            destination_project = {}
        destination_project["name"] = resolved_name
        destination_project["slug"] = resolved_slug
        save_json_fn(destination_dir / "project.json", destination_project)
        _save_project_metadata(
            destination_dir,
            save_json_fn=save_json_fn,
            status="active",
            ingest_input_root=ingest_input_root,
            superintendent=superintendent,
            assignee=assignee,
            model=agent_model,
        )

    registry = sync_fleet_registry_fn(root)
    entry = find_registry_project_fn(registry, resolved_slug)

    if entry is None:
        entry = {
            "project_slug": resolved_slug,
            "project_name": resolved_name,
            "project_dir_name": destination_dir.name,
            "project_store_path": str(destination_dir),
            "maestro_agent_id": f"maestro-project-{resolved_slug}",
            "ingest_input_root": "",
            "superintendent": "Unknown",
            "assignee": "Unassigned",
            "status": "active",
            "last_ingest_at": "",
            "last_index_at": "",
            "last_updated": now_iso_fn(),
            "telegram_bot_username": "",
            "telegram_bot_display_name": "",
            "last_conversation_at": "",
        }
    else:
        entry_changed = False

    if ingest_input_root:
        resolved_ingest = str(Path(ingest_input_root).expanduser().resolve())
        if entry.get("ingest_input_root") != resolved_ingest:
            entry["ingest_input_root"] = resolved_ingest
            entry_changed = True
    if superintendent:
        clean_super = superintendent.strip() or "Unknown"
        if entry.get("superintendent") != clean_super:
            entry["superintendent"] = clean_super
            entry_changed = True
    if assignee:
        clean_assignee = assignee.strip() or "Unassigned"
        if entry.get("assignee") != clean_assignee:
            entry["assignee"] = clean_assignee
            entry_changed = True
    if entry.get("status") in ("archived", "setup"):
        entry["status"] = "active"
        entry_changed = True
    if entry.get("project_name") != resolved_name:
        entry["project_name"] = resolved_name
        entry_changed = True
    if entry.get("project_slug") != resolved_slug:
        entry["project_slug"] = resolved_slug
        entry_changed = True
    if entry.get("project_store_path") != str(destination_dir):
        entry["project_store_path"] = str(destination_dir)
        entry_changed = True
    if entry.get("project_dir_name") != destination_dir.name:
        entry["project_dir_name"] = destination_dir.name
        entry_changed = True
    display_name, source, handle = resolve_node_identity_fn(entry)
    if entry.get("node_display_name") != display_name:
        entry["node_display_name"] = display_name
        entry_changed = True
    if entry.get("node_identity_source") != source:
        entry["node_identity_source"] = source
        entry_changed = True
    if entry.get("node_handle") != handle:
        entry["node_handle"] = handle
        entry_changed = True

    registration = None
    if register_agent:
        registration = register_project_agent_fn(
            store_root=root,
            project_slug=resolved_slug,
            project_name=resolved_name,
            project_store_path=str(destination_dir),
            home_dir=home_dir,
            dry_run=dry_run,
            model=agent_model,
        )

    ingest = build_ingest_command_fn(
        root,
        entry,
        ingest_input_root,
        200,
    )
    preflight = build_ingest_preflight_fn(
        root,
        entry,
        ingest_input_root,
    )
    network = resolve_network_urls_fn(web_port=default_web_port)

    return {
        "ok": True,
        "dry_run": dry_run,
        "source_project_path": str(source_project_dir),
        "destination_project_path": str(destination_dir),
        "relocation_mode": relocation_mode,
        "final_registry_entry": entry,
        "agent_registration": registration,
        "start_command": f"maestro start --store {quote_path_fn(root)}",
        "command_center_url": network["recommended_url"],
        "ingest_preflight_payload": {
            "project_slug": resolved_slug,
            "input_path": ingest.get("resolved_input_root") or default_input_placeholder,
            "command": ingest.get("command"),
            "ready": preflight.get("ready", False),
            "checks": preflight.get("checks", []),
        },
    }


def move_project_store(
    store_root: Path,
    project_slug: str,
    new_dir_name: str,
    *,
    sync_fleet_registry_fn: SyncFleetRegistryFn,
    find_registry_project_fn: FindRegistryProjectFn,
    quote_path_fn: Callable[[str | Path], str],
    dry_run: bool = True,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    registry = sync_fleet_registry_fn(root)
    entry = find_registry_project_fn(registry, project_slug)
    if not entry:
        return {"ok": False, "error": f"Project '{project_slug}' is not registered"}

    src = Path(str(entry.get("project_store_path", ""))).expanduser().resolve()
    dst = (root / new_dir_name.strip()).resolve()

    checks = [
        {"name": "source_exists", "ok": src.exists() and src.is_dir(), "detail": str(src)},
        {"name": "destination_available", "ok": not dst.exists(), "detail": str(dst)},
        {"name": "destination_under_store_root", "ok": dst.parent == root, "detail": str(dst)},
    ]
    ready = all(item["ok"] for item in checks)
    mv_command = f"mv {quote_path_fn(src)} {quote_path_fn(dst)}"

    if ready and not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        registry = sync_fleet_registry_fn(root)
        entry = find_registry_project_fn(registry, project_slug) or entry

    return {
        "ok": ready,
        "dry_run": dry_run,
        "checks": checks,
        "command": mv_command,
        "source": str(src),
        "destination": str(dst),
        "project": entry,
    }


def register_project_agent(
    store_root: Path,
    project_slug: str,
    project_name: str,
    project_store_path: str,
    *,
    load_openclaw_config_fn: LoadOpenClawConfigFn,
    resolve_company_agent_fn: ResolveCompanyAgentFn,
    openclaw_workspace_root_fn: OpenClawWorkspaceRootFn,
    resolve_profile_fn: ResolveProfileFn,
    ensure_telegram_account_bindings_fn: EnsureTelegramBindingsFn,
    save_json_fn: SaveJsonFn,
    default_fleet_openclaw_profile: str,
    profile_fleet: str,
    home_dir: Path | None = None,
    dry_run: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    config, config_path = load_openclaw_config_fn(home_dir=home_dir)
    if not config_path.exists():
        return {
            "ok": False,
            "error": f"OpenClaw config not found: {config_path}",
            "agent_id": f"maestro-project-{project_slug}",
        }

    if not isinstance(config.get("agents"), dict):
        config["agents"] = {}
    if not isinstance(config["agents"].get("list"), list):
        config["agents"]["list"] = []
    agent_list = config["agents"]["list"]

    company_agent = resolve_company_agent_fn(config)
    company_workspace = str(company_agent.get("workspace", "")).strip()
    workspace_root = (
        Path(company_workspace).expanduser().resolve()
        if company_workspace
        else openclaw_workspace_root_fn(
            home_dir=home_dir,
            default_profile=(
                default_fleet_openclaw_profile
                if resolve_profile_fn(home_dir=home_dir) == profile_fleet
                else ""
            ),
        ).resolve()
    )
    project_workspace = workspace_root / "projects" / project_slug
    project_agent_id = f"maestro-project-{project_slug}"

    selected_model = canonicalize_model(
        model.strip() if isinstance(model, str) and model.strip() else default_model_from_agents(agent_list),
        fallback=DEFAULT_PROJECT_MODEL,
    )

    desired_agent = {
        "id": project_agent_id,
        "name": f"Maestro ({project_name})",
        "default": False,
        "model": selected_model,
        "workspace": str(project_workspace),
    }

    existing = next(
        (item for item in agent_list if isinstance(item, dict) and item.get("id") == project_agent_id),
        None,
    )
    changed = False
    if existing is None:
        agent_list.append(desired_agent)
        changed = True
    else:
        for key, value in desired_agent.items():
            if existing.get(key) != value:
                existing[key] = value
                changed = True

    binding_changes = ensure_telegram_account_bindings_fn(config)
    if binding_changes:
        changed = True
    if _ensure_native_plugin_config(config):
        changed = True

    if not dry_run:
        if changed:
            save_json_fn(config_path, config)
        project_workspace.mkdir(parents=True, exist_ok=True)
        env_path = project_workspace / ".env"
        desired_env_line = f"MAESTRO_STORE={project_store_path}\n"
        role_line = "MAESTRO_AGENT_ROLE=project\n"
        slug_line = f"MAESTRO_PROJECT_SLUG={project_slug}\n"
        if not env_path.exists():
            env_path.write_text(desired_env_line + role_line + slug_line, encoding="utf-8")
        else:
            current_lines = env_path.read_text(encoding="utf-8").splitlines()
            updated_lines: list[str] = []
            saw_store = False
            saw_role = False
            saw_slug = False
            for raw in current_lines:
                line = raw.rstrip("\n")
                if line.startswith("MAESTRO_STORE="):
                    updated_lines.append(desired_env_line.rstrip("\n"))
                    saw_store = True
                    continue
                if line.startswith("MAESTRO_AGENT_ROLE="):
                    updated_lines.append(role_line.rstrip("\n"))
                    saw_role = True
                    continue
                if line.startswith("MAESTRO_PROJECT_SLUG="):
                    updated_lines.append(slug_line.rstrip("\n"))
                    saw_slug = True
                    continue
                updated_lines.append(line)
            if not saw_store:
                updated_lines.append(desired_env_line.rstrip("\n"))
            if not saw_role:
                updated_lines.append(role_line.rstrip("\n"))
            if not saw_slug:
                updated_lines.append(slug_line.rstrip("\n"))
            normalized = "\n".join(updated_lines).rstrip("\n") + "\n"
            env_path.write_text(normalized, encoding="utf-8")
        _sync_native_extension(project_workspace)

    return {
        "ok": True,
        "changed": changed,
        "dry_run": dry_run,
        "config_path": str(config_path),
        "agent_id": project_agent_id,
        "workspace": str(project_workspace),
        "model": selected_model,
        "binding_changes": binding_changes,
    }
