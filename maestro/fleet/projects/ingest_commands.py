"""Project ingest/index command builders and control payloads."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Callable

DEFAULT_INPUT_PLACEHOLDER = "<ABS_PATH_TO_PLAN_PDFS>"

SyncFleetRegistryFn = Callable[[Path], dict[str, Any]]
FindRegistryProjectFn = Callable[[dict[str, Any], str], dict[str, Any] | None]
WorkspaceRoutesFn = Callable[[str, dict[str, Any] | None], dict[str, str]]


def quote_path(path: str | Path) -> str:
    return shlex.quote(str(path))


def workspace_routes(project_slug: str, project_entry: dict[str, Any] | None = None) -> dict[str, str]:
    entry = project_entry if isinstance(project_entry, dict) else {}
    agent_id = str(entry.get("maestro_agent_id", "")).strip() or f"maestro-project-{project_slug}"
    return {
        "project_slug": project_slug,
        "agent_id": agent_id,
        "project_workspace_url": f"/{project_slug}/",
        "agent_workspace_url": f"/agents/{agent_id}/workspace/",
    }


def resolve_input_root(path: str | None) -> Path | None:
    if not isinstance(path, str) or not path.strip():
        return None
    return Path(path).expanduser().resolve()


def build_ingest_preflight(
    store_root: Path,
    project_entry: dict[str, Any],
    input_root_override: str | None = None,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    checks: list[dict[str, Any]] = []

    project_store_path = Path(str(project_entry.get("project_store_path", ""))).expanduser()
    if not project_store_path.is_absolute():
        project_store_path = (root / project_store_path).resolve()

    checks.append({
        "name": "store_root_exists",
        "ok": root.exists() and root.is_dir(),
        "detail": str(root),
    })
    checks.append({
        "name": "project_store_exists",
        "ok": project_store_path.exists() and project_store_path.is_dir(),
        "detail": str(project_store_path),
    })

    input_root_raw = input_root_override or str(project_entry.get("ingest_input_root", "")).strip()
    input_root = resolve_input_root(input_root_raw)
    checks.append({
        "name": "ingest_input_configured",
        "ok": bool(input_root),
        "detail": str(input_root) if input_root else "Set ingest input path for this project",
    })

    pdf_count = 0
    if input_root:
        input_exists = input_root.exists()
        input_is_dir = input_root.is_dir()
        if input_exists and input_is_dir:
            pdf_count = len(list(input_root.rglob("*.pdf")))
        checks.append({
            "name": "ingest_input_exists",
            "ok": input_exists,
            "detail": str(input_root),
        })
        checks.append({
            "name": "ingest_input_is_dir",
            "ok": input_is_dir,
            "detail": str(input_root),
        })
        checks.append({
            "name": "ingest_input_has_pdfs",
            "ok": pdf_count > 0,
            "detail": f"{pdf_count} pdf(s) discovered",
        })

    ready = all(bool(item.get("ok")) for item in checks)
    return {
        "ready": ready,
        "checks": checks,
        "resolved_input_root": str(input_root) if input_root else "",
        "pdf_count": pdf_count,
    }


def build_ingest_command(
    store_root: Path,
    project_entry: dict[str, Any],
    input_root_override: str | None = None,
    dpi: int = 200,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    project_name = str(project_entry.get("project_name", project_entry.get("project_slug", ""))).strip()
    project_store_path = str(project_entry.get("project_store_path", "")).strip()
    input_root_raw = input_root_override or str(project_entry.get("ingest_input_root", "")).strip()
    resolved_input = resolve_input_root(input_root_raw)

    if resolved_input:
        input_token = quote_path(resolved_input)
        needs_input_path = False
    else:
        input_token = DEFAULT_INPUT_PLACEHOLDER
        needs_input_path = True

    store_token = quote_path(Path(project_store_path).resolve()) if project_store_path else quote_path(root)
    command = (
        f"maestro ingest {input_token} "
        f"--project-name {quote_path(project_name)} "
        f"--store {store_token} "
        f"--dpi {int(dpi)}"
    )
    return {
        "command": command,
        "needs_input_path": needs_input_path,
        "resolved_input_root": str(resolved_input) if resolved_input else "",
    }


def build_index_command(project_entry: dict[str, Any]) -> str:
    project_store_path = str(project_entry.get("project_store_path", "")).strip()
    return f"maestro index {quote_path(project_store_path)}"


def project_control_payload(
    store_root: Path,
    project_slug: str,
    *,
    sync_fleet_registry_fn: SyncFleetRegistryFn,
    find_registry_project_fn: FindRegistryProjectFn,
    workspace_routes_fn: WorkspaceRoutesFn,
    input_root_override: str | None = None,
    dpi: int = 200,
) -> dict[str, Any]:
    registry = sync_fleet_registry_fn(store_root)
    entry = find_registry_project_fn(registry, project_slug)
    if not entry:
        return {"ok": False, "error": f"Project '{project_slug}' is not registered", "project_slug": project_slug}

    ingest = build_ingest_command(store_root, entry, input_root_override=input_root_override, dpi=dpi)
    preflight = build_ingest_preflight(store_root, entry, input_root_override=input_root_override)
    return {
        "ok": True,
        "project": entry,
        "workspace": workspace_routes_fn(project_slug, entry),
        "ingest": ingest,
        "preflight": preflight,
        "index_command": build_index_command(entry),
        "start_command": f"maestro start --store {quote_path(Path(store_root).resolve())}",
    }
