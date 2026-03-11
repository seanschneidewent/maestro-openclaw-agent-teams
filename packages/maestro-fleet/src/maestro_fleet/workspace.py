"""Fleet workspace sync owners.

This module owns workspace-specific runtime shaping for Commander and project
Maestro workspaces. Shared markdown rendering stays in ``maestro.workspace_templates``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

import maestro.workspace_templates as shared_workspace_templates
from maestro.workspace_templates import (
    provider_env_key_for_model,
    render_company_agents_md,
    render_project_agents_md,
    render_project_tools_md,
    render_tools_md,
    render_workspace_awareness_md,
    should_refresh_generic_project_file,
    should_remove_generic_project_bootstrap,
)

ResolveNetworkUrlsFn = Callable[..., dict[str, Any]]
NATIVE_PLUGIN_ID = "maestro-native-tools"


def skill_template_source(skill_name: str, template_root: Path | None = None) -> Path | None:
    if template_root is not None:
        candidate = template_root / "skills" / skill_name
        if candidate.exists():
            return candidate

    package_root = Path(__file__).resolve().parent
    shared_root = Path(shared_workspace_templates.__file__).resolve().parent
    repo_root = package_root.parents[3]
    candidates = [
        package_root / "agent" / "skills" / skill_name,
        shared_root / "agent" / "skills" / skill_name,
        repo_root / "agent" / "skills" / skill_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def native_extension_source() -> Path | None:
    package_root = Path(__file__).resolve().parent
    shared_root = Path(shared_workspace_templates.__file__).resolve().parent
    repo_root = package_root.parents[3]
    candidates = [
        package_root / "agent" / "extensions" / NATIVE_PLUGIN_ID,
        shared_root / "agent" / "extensions" / NATIVE_PLUGIN_ID,
        repo_root / "agent" / "extensions" / NATIVE_PLUGIN_ID,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _snapshot(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if not path.is_file():
            continue
        snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


def _sync_bundle(*, workspace: Path, destination_root: Path, source: Path | None, dry_run: bool) -> bool:
    if source is None:
        return False
    desired = _snapshot(source)
    current = _snapshot(destination_root) if destination_root.exists() else None
    if current == desired:
        return False
    if not dry_run:
        if destination_root.exists():
            shutil.rmtree(destination_root)
        destination_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination_root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return True


def _remove_bundle(*, destination_root: Path, dry_run: bool) -> bool:
    if not destination_root.exists():
        return False
    if not dry_run:
        shutil.rmtree(destination_root)
    return True


def sync_workspace_native_extension(*, workspace: Path, dry_run: bool = False) -> bool:
    return _sync_bundle(
        workspace=workspace,
        destination_root=workspace / ".openclaw" / "extensions" / NATIVE_PLUGIN_ID,
        source=native_extension_source(),
        dry_run=dry_run,
    )


def sync_company_workspace_skill_bundles(
    *,
    workspace: Path,
    template_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, bool]:
    return {
        "commander_skill_synced": _sync_bundle(
            workspace=workspace,
            destination_root=workspace / "skills" / "commander",
            source=skill_template_source("commander", template_root=template_root),
            dry_run=dry_run,
        ),
        "maestro_skill_removed": _remove_bundle(
            destination_root=workspace / "skills" / "maestro",
            dry_run=dry_run,
        ),
    }


def sync_project_workspace_skill_bundles(
    *,
    workspace: Path,
    template_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, bool]:
    return {
        "maestro_skill_synced": _sync_bundle(
            workspace=workspace,
            destination_root=workspace / "skills" / "maestro",
            source=skill_template_source("maestro", template_root=template_root),
            dry_run=dry_run,
        ),
        "commander_skill_removed": _remove_bundle(
            destination_root=workspace / "skills" / "commander",
            dry_run=dry_run,
        ),
    }


def sync_workspace_awareness_file(
    *,
    workspace: Path,
    model: str,
    store_root: str | Path,
    route_path: str,
    resolve_network_urls_fn: ResolveNetworkUrlsFn,
    surface_label: str = "Workspace",
    generated_by: str = "maestro",
    command_runner: Any | None = None,
    web_port: int | None = None,
    dry_run: bool = False,
) -> bool:
    resolver_kwargs: dict[str, Any] = {"route_path": route_path}
    if command_runner is not None:
        resolver_kwargs["command_runner"] = command_runner
    if web_port is not None:
        resolver_kwargs["web_port"] = web_port
    urls = resolve_network_urls_fn(**resolver_kwargs)
    desired = render_workspace_awareness_md(
        model=model,
        preferred_url=str(urls.get("recommended_url", "")).strip(),
        local_url=str(urls.get("localhost_url", "")).strip(),
        tailnet_url=str(urls.get("tailnet_url") or "").strip(),
        store_root=store_root,
        surface_label=surface_label,
        generated_by=generated_by,
    )
    awareness_path = workspace / "AWARENESS.md"
    current = awareness_path.read_text(encoding="utf-8") if awareness_path.exists() else ""
    if current == desired:
        return False
    if not dry_run:
        workspace.mkdir(parents=True, exist_ok=True)
        awareness_path.write_text(desired, encoding="utf-8")
    return True


def sync_company_workspace_runtime_files(
    *,
    workspace: Path,
    model: str,
    company_name: str,
    store_root: str | Path,
    generated_by: str,
    resolve_network_urls_fn: ResolveNetworkUrlsFn,
    template_root: Path | None = None,
    active_provider_env_key: str | None = None,
    command_runner: Any | None = None,
    web_port: int | None = None,
    dry_run: bool = False,
) -> dict[str, bool]:
    if not dry_run:
        workspace.mkdir(parents=True, exist_ok=True)

    skill_sync = sync_company_workspace_skill_bundles(
        workspace=workspace,
        template_root=template_root,
        dry_run=dry_run,
    )
    native_extension_synced = sync_workspace_native_extension(workspace=workspace, dry_run=dry_run)
    awareness_updated = sync_workspace_awareness_file(
        workspace=workspace,
        model=model,
        store_root=store_root,
        route_path="/command-center",
        resolve_network_urls_fn=resolve_network_urls_fn,
        surface_label="Command Center",
        generated_by=generated_by,
        command_runner=command_runner,
        web_port=web_port,
        dry_run=dry_run,
    )

    desired_agents = render_company_agents_md()
    desired_tools = render_tools_md(
        company_name=company_name,
        active_provider_env_key=active_provider_env_key,
    )
    agents_path = workspace / "AGENTS.md"
    current_agents = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    agents_updated = current_agents != desired_agents
    if agents_updated and not dry_run:
        agents_path.write_text(desired_agents, encoding="utf-8")

    tools_path = workspace / "TOOLS.md"
    current_tools = tools_path.read_text(encoding="utf-8") if tools_path.exists() else ""
    tools_updated = current_tools != desired_tools
    if tools_updated and not dry_run:
        tools_path.write_text(desired_tools, encoding="utf-8")

    return {
        "awareness_updated": awareness_updated,
        "agents_updated": agents_updated,
        "tools_updated": tools_updated,
        "commander_skill_synced": bool(skill_sync.get("commander_skill_synced")),
        "maestro_skill_removed": bool(skill_sync.get("maestro_skill_removed")),
        "native_extension_synced": native_extension_synced,
    }


def sync_project_workspace_runtime_files(
    *,
    project_workspace: Path,
    project_slug: str,
    model: str,
    store_root: str | Path,
    generated_by: str,
    resolve_network_urls_fn: ResolveNetworkUrlsFn,
    command_runner: Any | None = None,
    web_port: int | None = None,
    dry_run: bool = False,
) -> dict[str, bool]:
    if not dry_run:
        project_workspace.mkdir(parents=True, exist_ok=True)

    skill_sync = sync_project_workspace_skill_bundles(
        workspace=project_workspace,
        dry_run=dry_run,
    )
    native_extension_synced = sync_workspace_native_extension(
        workspace=project_workspace,
        dry_run=dry_run,
    )
    awareness_updated = sync_workspace_awareness_file(
        workspace=project_workspace,
        model=model,
        store_root=store_root,
        route_path=f"/{project_slug}/",
        resolve_network_urls_fn=resolve_network_urls_fn,
        surface_label="Workspace",
        generated_by=generated_by,
        command_runner=command_runner,
        web_port=web_port,
        dry_run=dry_run,
    )

    agents_path = project_workspace / "AGENTS.md"
    current_agents = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    agents_updated = (not agents_path.exists()) or should_refresh_generic_project_file("AGENTS.md", current_agents)
    if agents_updated and not dry_run:
        agents_path.write_text(render_project_agents_md(), encoding="utf-8")

    tools_path = project_workspace / "TOOLS.md"
    current_tools = tools_path.read_text(encoding="utf-8") if tools_path.exists() else ""
    tools_updated = (not tools_path.exists()) or should_refresh_generic_project_file("TOOLS.md", current_tools)
    if tools_updated and not dry_run:
        tools_path.write_text(
            render_project_tools_md(provider_env_key_for_model(model)),
            encoding="utf-8",
        )

    bootstrap_removed = False
    bootstrap_path = project_workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        bootstrap_content = bootstrap_path.read_text(encoding="utf-8")
        if should_remove_generic_project_bootstrap(bootstrap_content):
            if not dry_run:
                bootstrap_path.unlink()
            bootstrap_removed = True

    return {
        "awareness_updated": awareness_updated,
        "agents_updated": agents_updated,
        "tools_updated": tools_updated,
        "bootstrap_removed": bootstrap_removed,
        "maestro_skill_synced": bool(skill_sync.get("maestro_skill_synced")),
        "commander_skill_removed": bool(skill_sync.get("commander_skill_removed")),
        "native_extension_synced": native_extension_synced,
    }
