"""Fleet-native command-center action hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import maestro.control_plane_core as legacy_control_plane
from maestro.fleet.projects import ingest_commands as legacy_ingest_commands
from maestro.fleet.projects import lifecycle as legacy_lifecycle
from maestro.fleet.projects import registry as legacy_registry
from maestro.server_actions import run_command_center_action as legacy_run_command_center_action

from .command_center import build_derived_registry
from .doctor import build_doctor_report as build_fleet_doctor_report

_PROJECT_METADATA_KEY = "maestro"


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _derived_registry(store_root: Path) -> dict[str, Any]:
    return build_derived_registry(Path(store_root).resolve())


def _lookup_project_entry(store_root: Path, project_slug: str) -> dict[str, Any] | None:
    return legacy_registry.find_registry_project(_derived_registry(store_root), project_slug)


def _normalize_input_root(value: str | None) -> str:
    clean = _clean(value)
    if not clean:
        return ""
    return str(Path(clean).expanduser().resolve())


def _load_project_json(project_dir: Path) -> dict[str, Any]:
    payload = legacy_control_plane.load_json(project_dir / "project.json")
    return payload if isinstance(payload, dict) else {}


def _save_project_metadata(project_dir: Path, **fields: Any) -> None:
    project_json_path = project_dir / "project.json"
    payload = _load_project_json(project_dir)
    metadata = payload.get(_PROJECT_METADATA_KEY) if isinstance(payload.get(_PROJECT_METADATA_KEY), dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}

    changed = False
    for key, raw_value in fields.items():
        if raw_value is None:
            continue
        if key == "ingest_input_root":
            value = _normalize_input_root(raw_value)
        else:
            value = _clean(raw_value)
        if not value:
            continue
        if metadata.get(key) == value:
            continue
        metadata[key] = value
        changed = True

    if not changed:
        return

    payload[_PROJECT_METADATA_KEY] = metadata
    legacy_control_plane.save_json(project_json_path, payload)


def _ensure_workspace_slug_env(project_workspace: Path, project_slug: str) -> None:
    env_path = project_workspace / ".env"
    if not env_path.exists():
        return

    desired = f"MAESTRO_PROJECT_SLUG={project_slug}"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    saw_slug = False
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("MAESTRO_PROJECT_SLUG="):
            updated.append(desired)
            saw_slug = True
            continue
        updated.append(line)
    if not saw_slug:
        updated.append(desired)
    env_path.write_text("\n".join(updated).rstrip("\n") + "\n", encoding="utf-8")


def project_control_payload(
    store_root: Path,
    project_slug: str,
    input_root_override: str | None = None,
    dpi: int = 200,
) -> dict[str, Any]:
    return legacy_ingest_commands.project_control_payload(
        Path(store_root).resolve(),
        project_slug,
        sync_fleet_registry_fn=_derived_registry,
        find_registry_project_fn=legacy_registry.find_registry_project,
        workspace_routes_fn=legacy_ingest_commands.workspace_routes,
        input_root_override=input_root_override,
        dpi=dpi,
    )


def register_project_agent(
    store_root: Path,
    project_slug: str,
    project_name: str,
    project_store_path: str,
    *,
    home_dir: Path | None = None,
    dry_run: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    result = legacy_lifecycle.register_project_agent(
        store_root=Path(store_root).resolve(),
        project_slug=project_slug,
        project_name=project_name,
        project_store_path=project_store_path,
        load_openclaw_config_fn=legacy_control_plane._load_openclaw_config,
        resolve_company_agent_fn=legacy_control_plane._resolve_company_agent,
        openclaw_workspace_root_fn=legacy_control_plane.openclaw_workspace_root,
        resolve_profile_fn=legacy_control_plane.resolve_profile,
        ensure_telegram_account_bindings_fn=legacy_control_plane.ensure_telegram_account_bindings,
        save_json_fn=legacy_control_plane.save_json,
        default_fleet_openclaw_profile=legacy_control_plane.DEFAULT_FLEET_OPENCLAW_PROFILE,
        profile_fleet=legacy_control_plane.PROFILE_FLEET,
        home_dir=home_dir,
        dry_run=dry_run,
        model=model,
    )

    if bool(result.get("ok")) and not dry_run:
        workspace = _clean(result.get("workspace"))
        if workspace:
            _ensure_workspace_slug_env(Path(workspace).expanduser().resolve(), project_slug)
        project_store = Path(project_store_path).expanduser().resolve()
        _save_project_metadata(project_store, model=_clean(result.get("model") or model))
    return result


def create_project_node(
    store_root: Path,
    project_name: str,
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
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    result = legacy_lifecycle.create_project_node(
        root,
        project_name,
        slugify_fn=legacy_control_plane.slugify,
        now_iso_fn=legacy_control_plane._now_iso,
        save_json_fn=legacy_control_plane.save_json,
        sync_fleet_registry_fn=_derived_registry,
        find_registry_project_fn=legacy_registry.find_registry_project,
        resolve_node_identity_fn=legacy_registry.resolve_node_identity,
        project_control_payload_fn=lambda path, slug: project_control_payload(path, project_slug=slug),
        register_project_agent_fn=register_project_agent,
        project_slug=project_slug,
        project_dir_name=project_dir_name,
        ingest_input_root=ingest_input_root,
        superintendent=superintendent,
        assignee=assignee,
        register_agent=register_agent,
        home_dir=home_dir,
        agent_model=agent_model,
        telegram_bot_username=telegram_bot_username,
        telegram_bot_display_name=telegram_bot_display_name,
        normalize_bot_username_fn=legacy_registry.normalize_bot_username,
        dry_run=dry_run,
    )
    if not bool(result.get("ok")):
        return result

    slug = _clean(result.get("project_slug"))
    project_dir = Path(str(result.get("project_dir", "")).strip() or (root / (project_dir_name or slug))).expanduser().resolve()
    if not dry_run:
        _save_project_metadata(
            project_dir,
            ingest_input_root=ingest_input_root,
            superintendent=superintendent,
            assignee=assignee,
            telegram_bot_username=telegram_bot_username,
            telegram_bot_display_name=telegram_bot_display_name,
        )
        entry = _lookup_project_entry(root, slug)
        if entry is not None:
            result["project"] = entry
        result["control"] = project_control_payload(root, project_slug=slug)
    return result


def onboard_project_store(
    store_root: Path,
    source_path: str,
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
    root = Path(store_root).resolve()
    result = legacy_lifecycle.onboard_project_store(
        root,
        source_path,
        load_json_fn=legacy_control_plane.load_json,
        save_json_fn=legacy_control_plane.save_json,
        slugify_fn=legacy_control_plane.slugify,
        now_iso_fn=legacy_control_plane._now_iso,
        sync_fleet_registry_fn=_derived_registry,
        find_registry_project_fn=legacy_registry.find_registry_project,
        resolve_node_identity_fn=legacy_registry.resolve_node_identity,
        register_project_agent_fn=register_project_agent,
        build_ingest_command_fn=legacy_ingest_commands.build_ingest_command,
        build_ingest_preflight_fn=legacy_ingest_commands.build_ingest_preflight,
        resolve_network_urls_fn=legacy_control_plane.resolve_network_urls,
        quote_path_fn=legacy_ingest_commands.quote_path,
        default_web_port=legacy_control_plane.DEFAULT_WEB_PORT,
        default_input_placeholder=legacy_ingest_commands.DEFAULT_INPUT_PLACEHOLDER,
        project_name=project_name,
        project_slug=project_slug,
        project_dir_name=project_dir_name,
        ingest_input_root=ingest_input_root,
        superintendent=superintendent,
        assignee=assignee,
        register_agent=register_agent,
        move_source=move_source,
        home_dir=home_dir,
        agent_model=agent_model,
        dry_run=dry_run,
    )
    if not bool(result.get("ok")):
        return result

    if not dry_run:
        destination = Path(str(result.get("destination_project_path", "")).strip()).expanduser().resolve()
        _save_project_metadata(
            destination,
            ingest_input_root=ingest_input_root,
            superintendent=superintendent,
            assignee=assignee,
        )

        entry = result.get("final_registry_entry") if isinstance(result.get("final_registry_entry"), dict) else {}
        slug = _clean(entry.get("project_slug")) or _clean(project_slug)
        refreshed_entry = _lookup_project_entry(root, slug) if slug else None
        if refreshed_entry is not None:
            result["final_registry_entry"] = refreshed_entry
            control = project_control_payload(root, project_slug=slug)
            ingest = control.get("ingest", {}) if isinstance(control.get("ingest"), dict) else {}
            preflight = control.get("preflight", {}) if isinstance(control.get("preflight"), dict) else {}
            result["ingest_preflight_payload"] = {
                "project_slug": slug,
                "input_path": ingest.get("resolved_input_root") or legacy_ingest_commands.DEFAULT_INPUT_PLACEHOLDER,
                "command": ingest.get("command"),
                "ready": bool(preflight.get("ready", False)),
                "checks": preflight.get("checks", []),
            }
    return result


def move_project_store(
    store_root: Path,
    project_slug: str,
    new_dir_name: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    return legacy_lifecycle.move_project_store(
        store_root=Path(store_root).resolve(),
        project_slug=project_slug,
        new_dir_name=new_dir_name,
        sync_fleet_registry_fn=_derived_registry,
        find_registry_project_fn=legacy_registry.find_registry_project,
        quote_path_fn=legacy_ingest_commands.quote_path,
        dry_run=dry_run,
    )


class FleetCommandCenterActionRunner:
    """Package-native action runner for Fleet server mode."""

    async def run_command_center_action(self, payload: dict[str, Any], *, server_module: Any) -> dict[str, Any]:
        return await legacy_run_command_center_action(
            payload,
            store_path=server_module.store_path,
            refresh_all_state=server_module._refresh_all_state,
            broadcast_command_center_update=server_module._broadcast_command_center_update,
            get_fleet_registry=lambda: server_module.fleet_registry,
            get_awareness_state=lambda: server_module.awareness_state,
            doctor_builder=build_fleet_doctor_report,
            create_project_node_fn=create_project_node,
            onboard_project_store_fn=onboard_project_store,
            project_control_payload_fn=project_control_payload,
            move_project_store_fn=move_project_store,
            register_project_agent_fn=register_project_agent,
        )


def install_fleet_action_runner(server_module: Any) -> FleetCommandCenterActionRunner:
    runner = FleetCommandCenterActionRunner()
    setter = getattr(server_module, "set_command_center_action_runner", None)
    if callable(setter):
        setter(runner)
    else:
        server_module.command_center_action_runner = runner
    return runner


__all__ = [
    "FleetCommandCenterActionRunner",
    "create_project_node",
    "install_fleet_action_runner",
    "move_project_store",
    "onboard_project_store",
    "project_control_payload",
    "register_project_agent",
]
