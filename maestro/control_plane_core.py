"""Default-agent control plane for command-center awareness and actions.

This module intentionally keeps all orchestration logic deterministic and
filesystem-driven so the default Company Maestro can reason from live state.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .command_center import build_project_snapshot, discover_project_dirs
from .utils import load_json, save_json, slugify


REGISTRY_VERSION = 1
DEFAULT_WEB_PORT = 3000
DEFAULT_INPUT_PLACEHOLDER = "<ABS_PATH_TO_PLAN_PDFS>"
FREE_PROJECT_SLOTS = 1

CommandRunner = Callable[[list[str], int], tuple[bool, str]]
PLACEHOLDER_MARKERS = ("<PASTE_", "PASTE_", "YOUR_KEY_HERE", "CHANGEME")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_runner(args: list[str], timeout: int = 6) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for candidate in (raw, raw.replace("Z", "+00:00"), f"{raw}T00:00:00"):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _parse_tailscale_ipv4(output: str) -> str | None:
    for line in output.splitlines():
        ip = line.strip()
        if ip and "." in ip:
            return ip
    return None


def _project_index_timestamp(project_dir: Path) -> str:
    index_data = load_json(project_dir / "index.json")
    if not isinstance(index_data, dict):
        return ""

    candidates = [
        index_data.get("updated_at"),
        index_data.get("generated"),
    ]
    summary = index_data.get("summary")
    if isinstance(summary, dict):
        candidates.extend([
            summary.get("updated_at"),
            summary.get("generated"),
        ])
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _load_openclaw_config(home_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    home = (home_dir or Path.home()).resolve()
    path = home / ".openclaw" / "openclaw.json"
    payload = load_json(path)
    if not isinstance(payload, dict):
        payload = {}
    return payload, path


def _resolve_company_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    company = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("id") == "maestro-company"),
        None,
    )
    if isinstance(company, dict):
        return company
    default_agent = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("default")),
        None,
    )
    if isinstance(default_agent, dict):
        return default_agent
    legacy = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("id") == "maestro"),
        None,
    )
    return legacy if isinstance(legacy, dict) else {}


def _telegram_configured(config: dict[str, Any]) -> bool:
    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    tg = channels.get("telegram")
    if not isinstance(tg, dict):
        return False
    if tg.get("enabled") and tg.get("botToken"):
        return True
    accounts = tg.get("accounts")
    return isinstance(accounts, dict) and any(
        isinstance(account, dict) and account.get("botToken") for account in accounts.values()
    )


def _is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    text = value.strip()
    if not text:
        return True
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def _gateway_auth_health(config: dict[str, Any]) -> dict[str, Any]:
    gateway = config.get("gateway") if isinstance(config.get("gateway"), dict) else {}
    auth = gateway.get("auth") if isinstance(gateway.get("auth"), dict) else {}
    remote = gateway.get("remote") if isinstance(gateway.get("remote"), dict) else {}
    auth_token = str(auth.get("token", "")).strip()
    remote_token = str(remote.get("token", "")).strip()

    auth_ok = bool(auth_token) and not _is_placeholder_secret(auth_token)
    remote_ok = bool(remote_token) and not _is_placeholder_secret(remote_token)
    aligned = bool(auth_ok and remote_ok and auth_token == remote_token)
    return {
        "auth_token_configured": auth_ok,
        "remote_token_configured": remote_ok,
        "tokens_aligned": aligned,
    }


def _pending_device_pairing(
    *,
    runner: CommandRunner,
    openclaw_installed: bool,
    pairing_required: bool,
) -> dict[str, Any]:
    status = {
        "required": pairing_required,
        "pending_requests": 0,
        "auto_approvable": False,
        "source": "none",
    }
    if not openclaw_installed:
        status["source"] = "openclaw_missing"
        return status
    if not pairing_required:
        status["source"] = "status"
        return status

    ok, out = runner(["openclaw", "devices", "list", "--json"], timeout=8)
    if not ok:
        status["source"] = "devices_list_failed"
        return status
    try:
        payload = json.loads(out)
    except Exception:
        status["source"] = "devices_list_invalid_json"
        return status

    pending = payload.get("pending")
    pending_list = pending if isinstance(pending, list) else []
    count = len(pending_list)
    status["pending_requests"] = count
    status["auto_approvable"] = count == 1
    status["source"] = "devices_list"
    return status


def resolve_network_urls(
    web_port: int = DEFAULT_WEB_PORT,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    runner = command_runner or _default_runner
    localhost = f"http://localhost:{web_port}/command-center"

    tailnet_ip: str | None = None
    if shutil.which("tailscale"):
        ok, out = runner(["tailscale", "ip", "-4"], timeout=5)
        if ok:
            tailnet_ip = _parse_tailscale_ipv4(out)

    tailnet = f"http://{tailnet_ip}:{web_port}/command-center" if tailnet_ip else None
    return {
        "localhost_url": localhost,
        "tailnet_url": tailnet,
        "recommended_url": tailnet or localhost,
        "tailscale_ip": tailnet_ip,
    }


def fleet_registry_path(store_root: Path) -> Path:
    return Path(store_root).resolve() / ".command_center" / "fleet_registry.json"


def _default_registry(store_root: Path) -> dict[str, Any]:
    return {
        "version": REGISTRY_VERSION,
        "updated_at": "",
        "store_root": str(Path(store_root).resolve()),
        "projects": [],
    }


def load_fleet_registry(store_root: Path) -> dict[str, Any]:
    root = Path(store_root).resolve()
    default_registry = _default_registry(root)
    path = fleet_registry_path(root)
    payload = load_json(path, default=default_registry)
    if not isinstance(payload, dict):
        return default_registry

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
        normalized.append(
            {
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
            }
        )

    return {
        "version": int(payload.get("version", REGISTRY_VERSION)),
        "updated_at": payload.get("updated_at", ""),
        "store_root": str(root),
        "projects": sorted(normalized, key=lambda x: x["project_name"].lower()),
    }


def _registries_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
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


def save_fleet_registry(store_root: Path, registry: dict[str, Any]):
    path = fleet_registry_path(store_root)
    save_json(path, registry)


def sync_fleet_registry(store_root: Path, dry_run: bool = False) -> dict[str, Any]:
    """Sync registry with discovered projects under the current store root."""
    root = Path(store_root).resolve()
    existing = load_fleet_registry(root)
    existing_by_slug = {
        item["project_slug"]: item for item in existing.get("projects", []) if isinstance(item, dict)
    }

    synced: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for project_dir in discover_project_dirs(root):
        snapshot = build_project_snapshot(project_dir)
        slug = str(snapshot.get("slug", "")).strip()
        if not slug:
            continue

        project_data = load_json(project_dir / "project.json")
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
            "last_index_at": _project_index_timestamp(project_dir)
            or str(existing_entry.get("last_index_at", "")).strip(),
            "last_updated": (
                str(snapshot.get("last_updated", "")).strip()
                or str(existing_entry.get("last_updated", "")).strip()
            ),
        }
        synced.append(entry)
        seen_slugs.add(slug)

    for slug, item in existing_by_slug.items():
        if slug in seen_slugs:
            continue
        archived = dict(item)
        archived["status"] = "archived"
        synced.append(archived)

    synced.sort(key=lambda x: x.get("project_name", "").lower())
    core_registry = {
        "version": REGISTRY_VERSION,
        "store_root": str(root),
        "projects": synced,
    }
    changed = not _registries_equal(existing, core_registry)
    registry = {
        "version": REGISTRY_VERSION,
        "updated_at": _now_iso() if changed else str(existing.get("updated_at", "")),
        "store_root": str(root),
        "projects": synced,
    }
    if not registry["updated_at"]:
        registry["updated_at"] = _now_iso()

    if not dry_run and changed:
        save_fleet_registry(root, registry)

    return registry


def _find_registry_project(registry: dict[str, Any], project_slug: str) -> dict[str, Any] | None:
    needle = project_slug.strip().lower()
    for item in registry.get("projects", []):
        if not isinstance(item, dict):
            continue
        slug = str(item.get("project_slug", "")).strip().lower()
        if slug == needle:
            return item
    return None


def _quote_path(path: str | Path) -> str:
    return shlex.quote(str(path))


def _resolve_input_root(path: str | None) -> Path | None:
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
    input_root = _resolve_input_root(input_root_raw)
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
    input_root_raw = input_root_override or str(project_entry.get("ingest_input_root", "")).strip()
    resolved_input = _resolve_input_root(input_root_raw)

    if resolved_input:
        input_token = _quote_path(resolved_input)
        needs_input_path = False
    else:
        input_token = DEFAULT_INPUT_PLACEHOLDER
        needs_input_path = True

    command = (
        f"maestro ingest {input_token} "
        f"--project-name {_quote_path(project_name)} "
        f"--store {_quote_path(root)} "
        f"--dpi {int(dpi)}"
    )
    return {
        "command": command,
        "needs_input_path": needs_input_path,
        "resolved_input_root": str(resolved_input) if resolved_input else "",
    }


def build_index_command(project_entry: dict[str, Any]) -> str:
    project_store_path = str(project_entry.get("project_store_path", "")).strip()
    return f"maestro index {_quote_path(project_store_path)}"


def project_control_payload(
    store_root: Path,
    project_slug: str,
    input_root_override: str | None = None,
    dpi: int = 200,
) -> dict[str, Any]:
    registry = sync_fleet_registry(store_root)
    entry = _find_registry_project(registry, project_slug)
    if not entry:
        return {"ok": False, "error": f"Project '{project_slug}' is not registered", "project_slug": project_slug}

    ingest = build_ingest_command(store_root, entry, input_root_override=input_root_override, dpi=dpi)
    preflight = build_ingest_preflight(store_root, entry, input_root_override=input_root_override)
    return {
        "ok": True,
        "project": entry,
        "ingest": ingest,
        "preflight": preflight,
        "index_command": build_index_command(entry),
        "start_command": f"maestro start --store {_quote_path(Path(store_root).resolve())}",
    }


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
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    name = project_name.strip()
    slug = slugify(project_slug or name)
    dir_name = (project_dir_name or slug).strip() or slug
    project_dir = root / dir_name
    now_iso = _now_iso()

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
        save_json(
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
        save_json(
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

    registry = sync_fleet_registry(root, dry_run=dry_run)
    entry = _find_registry_project(registry, slug)
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
        }
        registry.setdefault("projects", []).append(entry)

    if ingest_input_root:
        entry["ingest_input_root"] = str(Path(ingest_input_root).expanduser().resolve())
    if superintendent:
        entry["superintendent"] = superintendent.strip() or "Unknown"
    if assignee:
        entry["assignee"] = assignee.strip() or "Unassigned"

    if not dry_run:
        save_fleet_registry(root, {
            "version": REGISTRY_VERSION,
            "updated_at": _now_iso(),
            "store_root": str(root),
            "projects": sorted(registry.get("projects", []), key=lambda x: x.get("project_name", "").lower()),
        })
        registry = sync_fleet_registry(root)
        entry = _find_registry_project(registry, slug) or entry

    controls = project_control_payload(root, slug, dpi=200)
    registration = None
    if register_agent:
        registration = register_project_agent(
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

    source_meta = load_json(source_project_dir / "project.json")
    if not isinstance(source_meta, dict):
        source_meta = {}

    resolved_name = (
        (project_name or str(source_meta.get("name", "")).strip() or source_project_dir.name).strip()
    )
    resolved_slug = slugify(
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
        destination_project = load_json(destination_dir / "project.json")
        if not isinstance(destination_project, dict):
            destination_project = {}
        destination_project["name"] = resolved_name
        destination_project["slug"] = resolved_slug
        save_json(destination_dir / "project.json", destination_project)

    registry = sync_fleet_registry(root, dry_run=dry_run)
    entry = _find_registry_project(registry, resolved_slug)

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
            "last_updated": _now_iso(),
        }
        registry.setdefault("projects", []).append(entry)
        entry_changed = True
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

    if entry_changed and not dry_run:
        save_fleet_registry(root, {
            "version": REGISTRY_VERSION,
            "updated_at": _now_iso(),
            "store_root": str(root),
            "projects": sorted(registry.get("projects", []), key=lambda x: x.get("project_name", "").lower()),
        })

    registration = None
    if register_agent:
        registration = register_project_agent(
            store_root=root,
            project_slug=resolved_slug,
            project_name=resolved_name,
            project_store_path=str(destination_dir),
            home_dir=home_dir,
            dry_run=dry_run,
            model=agent_model,
        )

    ingest = build_ingest_command(
        root,
        entry,
        input_root_override=ingest_input_root,
        dpi=200,
    )
    preflight = build_ingest_preflight(
        root,
        entry,
        input_root_override=ingest_input_root,
    )
    network = resolve_network_urls(web_port=DEFAULT_WEB_PORT)

    return {
        "ok": True,
        "dry_run": dry_run,
        "source_project_path": str(source_project_dir),
        "destination_project_path": str(destination_dir),
        "relocation_mode": relocation_mode,
        "final_registry_entry": entry,
        "agent_registration": registration,
        "start_command": f"maestro start --store {_quote_path(root)}",
        "command_center_url": network["recommended_url"],
        "ingest_preflight_payload": {
            "project_slug": resolved_slug,
            "input_path": ingest.get("resolved_input_root") or DEFAULT_INPUT_PLACEHOLDER,
            "command": ingest.get("command"),
            "ready": preflight.get("ready", False),
            "checks": preflight.get("checks", []),
        },
    }


def move_project_store(
    store_root: Path,
    project_slug: str,
    new_dir_name: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    root = Path(store_root).resolve()
    registry = sync_fleet_registry(root)
    entry = _find_registry_project(registry, project_slug)
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
    mv_command = f"mv {_quote_path(src)} {_quote_path(dst)}"

    if ready and not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        registry = sync_fleet_registry(root)
        entry = _find_registry_project(registry, project_slug) or entry

    return {
        "ok": ready,
        "dry_run": dry_run,
        "checks": checks,
        "command": mv_command,
        "source": str(src),
        "destination": str(dst),
        "project": entry,
    }


def _default_model_from_agents(agent_list: list[dict[str, Any]]) -> str:
    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        if agent.get("id") == "maestro-company" and isinstance(agent.get("model"), str):
            return str(agent["model"])
    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        if isinstance(agent.get("model"), str) and agent.get("model").strip():
            return str(agent["model"]).strip()
    return "google/gemini-3-pro-preview"


def register_project_agent(
    store_root: Path,
    project_slug: str,
    project_name: str,
    project_store_path: str,
    home_dir: Path | None = None,
    dry_run: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    config, config_path = _load_openclaw_config(home_dir=home_dir)
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

    company_agent = _resolve_company_agent(config)
    company_workspace = str(company_agent.get("workspace", "")).strip()
    home = (home_dir or Path.home()).resolve()
    workspace_root = (
        Path(company_workspace).expanduser().resolve()
        if company_workspace
        else (home / ".openclaw" / "workspace-maestro").resolve()
    )
    project_workspace = workspace_root / "projects" / project_slug
    project_agent_id = f"maestro-project-{project_slug}"

    selected_model = model.strip() if isinstance(model, str) and model.strip() else _default_model_from_agents(agent_list)

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

    if not dry_run:
        if changed:
            save_json(config_path, config)
        project_workspace.mkdir(parents=True, exist_ok=True)
        env_path = project_workspace / ".env"
        desired_env_line = f"MAESTRO_STORE={project_store_path}\n"
        if not env_path.exists():
            env_path.write_text(desired_env_line, encoding="utf-8")
        elif "MAESTRO_STORE=" not in env_path.read_text(encoding="utf-8"):
            with env_path.open("a", encoding="utf-8") as handle:
                handle.write(desired_env_line)

    return {
        "ok": True,
        "changed": changed,
        "dry_run": dry_run,
        "config_path": str(config_path),
        "agent_id": project_agent_id,
        "workspace": str(project_workspace),
        "model": selected_model,
    }


def _service_status(
    command_runner: CommandRunner | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    runner = command_runner or _default_runner
    config, config_path = _load_openclaw_config(home_dir=home_dir)
    agent = _resolve_company_agent(config)

    tailscale_installed = shutil.which("tailscale") is not None
    tailscale_connected = False
    tailscale_ip = None
    if tailscale_installed:
        ok, out = runner(["tailscale", "ip", "-4"], timeout=5)
        if ok:
            tailscale_ip = _parse_tailscale_ipv4(out)
            tailscale_connected = bool(tailscale_ip)

    openclaw_installed = shutil.which("openclaw") is not None
    openclaw_running = False
    pairing_required = False
    status_output = ""
    if openclaw_installed:
        ok, out = runner(["openclaw", "status"], timeout=6)
        status_output = out
        lowered = out.lower()
        openclaw_running = (ok and "running" in lowered) or ("gateway service" in lowered and "running" in lowered)
        pairing_required = "pairing required" in lowered

    gateway_auth = _gateway_auth_health(config)
    device_pairing = _pending_device_pairing(
        runner=runner,
        openclaw_installed=openclaw_installed,
        pairing_required=pairing_required,
    )

    return {
        "config_path": str(config_path),
        "tailscale": {
            "installed": tailscale_installed,
            "connected": tailscale_connected,
            "ip": tailscale_ip or "",
        },
        "openclaw": {
            "installed": openclaw_installed,
            "running": openclaw_running,
            "pairing_required": pairing_required,
            "gateway_auth": gateway_auth,
            "device_pairing": device_pairing,
            "status_snippet": status_output[:240],
        },
        "telegram": {
            "configured": _telegram_configured(config),
        },
        "company_agent": {
            "configured": bool(agent),
            "id": str(agent.get("id", "")),
            "name": str(agent.get("name", "")),
            "workspace": str(agent.get("workspace", "")),
        },
    }


def build_purchase_status(
    store_root: Path,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_registry = registry if isinstance(registry, dict) else sync_fleet_registry(store_root)
    projects = current_registry.get("projects", []) if isinstance(current_registry.get("projects"), list) else []
    active_count = len([
        item for item in projects
        if isinstance(item, dict) and str(item.get("status", "active")).strip().lower() != "archived"
    ])
    free_remaining = max(0, FREE_PROJECT_SLOTS - active_count)
    next_node_badge = "+" if free_remaining > 0 else "+$"
    return {
        "purchase_command": "maestro-purchase",
        "free_project_slots_total": FREE_PROJECT_SLOTS,
        "free_project_slots_remaining": free_remaining,
        "active_project_count": active_count,
        "next_node_badge": next_node_badge,
        "requires_paid_license": free_remaining <= 0,
    }


def build_awareness_state(
    store_root: Path,
    command_center_state: dict[str, Any] | None = None,
    web_port: int = DEFAULT_WEB_PORT,
    command_runner: CommandRunner | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a machine-specific, runtime-specific awareness state contract."""
    root = Path(store_root).resolve()
    registry = sync_fleet_registry(root)
    services = _service_status(command_runner=command_runner, home_dir=home_dir)
    network = resolve_network_urls(web_port=web_port, command_runner=command_runner)
    purchase = build_purchase_status(root, registry=registry)

    fleet_projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    project_count = len([p for p in fleet_projects if isinstance(p, dict) and p.get("status") != "archived"])

    stale_projects: list[dict[str, Any]] = []
    for item in fleet_projects:
        if not isinstance(item, dict):
            continue
        dt = _parse_iso(item.get("last_updated")) or _parse_iso(item.get("last_ingest_at"))
        if not dt:
            continue
        age_hours = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours > 72:
            stale_projects.append({
                "project_slug": item.get("project_slug", ""),
                "project_name": item.get("project_name", ""),
                "last_updated": item.get("last_updated", ""),
                "age_hours": round(age_hours, 1),
            })

    degraded_reasons: list[str] = []
    if not services["tailscale"]["connected"]:
        degraded_reasons.append("Tailscale not connected")
    if not services["openclaw"]["running"]:
        degraded_reasons.append("OpenClaw gateway not running")
    gateway_auth = services["openclaw"].get("gateway_auth", {}) if isinstance(services["openclaw"], dict) else {}
    if not bool(gateway_auth.get("tokens_aligned")):
        degraded_reasons.append("Gateway auth token mismatch or missing")
    device_pairing = services["openclaw"].get("device_pairing", {}) if isinstance(services["openclaw"], dict) else {}
    if bool(device_pairing.get("required")):
        degraded_reasons.append("CLI device pairing approval required")
    if not services["telegram"]["configured"]:
        degraded_reasons.append("Telegram not configured")
    if not services["company_agent"]["configured"]:
        degraded_reasons.append("Company Maestro agent not configured")
    if not root.exists():
        degraded_reasons.append("Knowledge store root missing")
    if project_count == 0:
        degraded_reasons.append("No project nodes discovered")

    posture = "healthy" if not degraded_reasons else "degraded"
    current_action = ""
    if isinstance(command_center_state, dict):
        orchestrator = command_center_state.get("orchestrator")
        if isinstance(orchestrator, dict):
            current_action = str(orchestrator.get("currentAction", "")).strip()

    return {
        "generated_at": _now_iso(),
        "posture": posture,
        "degraded_reasons": degraded_reasons,
        "network": network,
        "paths": {
            "store_root": str(root),
            "registry_path": str(fleet_registry_path(root)),
            "workspace_root": str(services["company_agent"].get("workspace", "")).strip(),
        },
        "services": services,
        "fleet": {
            "project_count": project_count,
            "stale_projects": stale_projects,
            "registry": registry,
            "current_action": current_action,
        },
        "commands": {
            "update": "maestro update",
            "doctor": "maestro doctor --fix",
            "serve": f"maestro serve --port {web_port} --store {_quote_path(root)}",
            "start": f"maestro start --port {web_port} --store {_quote_path(root)}",
            "purchase": "maestro-purchase",
        },
        "purchase": purchase,
        "available_actions": [
            "sync_registry",
            "create_project_node",
            "onboard_project_store",
            "ingest_command",
            "preflight_ingest",
            "index_command",
            "move_project_store",
            "register_project_agent",
            "doctor_fix",
        ],
    }
