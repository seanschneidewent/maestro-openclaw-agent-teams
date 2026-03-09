"""Maestro updater.

Provides a safe, idempotent `maestro update` path for existing installs.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .control_plane import (
    ensure_telegram_account_bindings,
    resolve_network_urls,
)
from .command_center import discover_project_dirs
from .fleet_constants import (
    DEFAULT_COMMANDER_MODEL,
    canonicalize_model,
    default_model_from_agents as default_fleet_model_from_agents,
)
from .profile import PROFILE_FLEET, PROFILE_SOLO, infer_profile_from_openclaw_config
from .openclaw_guard import ensure_openclaw_override_allowed
from .openclaw_profile import (
    openclaw_config_path,
    openclaw_state_root,
    openclaw_workspace_root,
    prepend_openclaw_profile_shell,
)
from .workspace_templates import (
    provider_env_key_for_model,
    render_company_agents_md,
    render_company_identity_md,
    render_company_soul_md,
    render_company_user_md,
    render_personal_agents_md,
    render_personal_tools_md,
    render_tools_md,
    render_workspace_env,
    sync_company_workspace_skill_bundles,
    sync_project_workspace_runtime_files,
    sync_project_workspace_skill_bundles,
    sync_workspace_awareness_file,
)
from .install_state import load_install_state, save_install_state


CommandRunner = Callable[[str], tuple[bool, str]]
COMMANDER_DISPLAY_NAME = "The Commander"


@dataclass
class UpdateSummary:
    changed: bool = False
    config_changed: bool = False
    workspace_changed: bool = False
    session_dir_created: bool = False
    backup_dir: Path | None = None
    workspace: Path | None = None
    telegram_configured: bool = False
    command_center_url: str = "http://localhost:3000/command-center"
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _default_command_runner(cmd: str) -> tuple[bool, str]:
    profiled_cmd = prepend_openclaw_profile_shell(cmd)
    try:
        result = subprocess.run(profiled_cmd, shell=True, capture_output=True, text=True)
    except Exception as exc:
        return False, str(exc)

    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _frontend_dist_candidates(frontend_dir_name: str) -> list[Path]:
    package_dir = Path(__file__).resolve().parent
    candidates: list[Path] = [package_dir / frontend_dir_name]
    for parent in package_dir.parents:
        candidates.append(parent / frontend_dir_name / "dist")
    return candidates


def _frontend_dist_available(frontend_dir_name: str) -> bool:
    for candidate in _frontend_dist_candidates(frontend_dir_name):
        if (candidate / "index.html").exists():
            return True
    return False


def _find_frontend_source_dir(frontend_dir_name: str) -> Path | None:
    package_dir = Path(__file__).resolve().parent
    for parent in package_dir.parents:
        candidate = parent / frontend_dir_name
        if (candidate / "package.json").exists():
            return candidate
    return None


def _build_frontend_dist(frontend_dir_name: str, *, label: str) -> tuple[bool, str]:
    source_dir = _find_frontend_source_dir(frontend_dir_name)
    if source_dir is None:
        return False, f"{label} source directory not found"
    if shutil.which("npm") is None:
        return False, "npm is not available on PATH"

    install = subprocess.run(
        ["npm", "install", "--prefix", str(source_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        output = (install.stderr or install.stdout or "").strip()
        return False, output or f"npm install failed for {label}"

    build = subprocess.run(
        ["npm", "run", "build", "--prefix", str(source_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        output = (build.stderr or build.stdout or "").strip()
        return False, output or f"npm run build failed for {label}"

    if not _frontend_dist_available(frontend_dir_name):
        return False, f"{label} build completed but dist/index.html was not found"

    return True, ""


def _ensure_frontend_artifacts(profile: str, *, dry_run: bool) -> tuple[list[str], list[str]]:
    changes: list[str] = []
    warnings: list[str] = []
    targets: list[tuple[str, str]] = [("Workspace frontend", "workspace_frontend")]
    if profile == PROFILE_FLEET:
        targets.append(("Command Center frontend", "command_center_frontend"))

    for label, frontend_dir_name in targets:
        if _frontend_dist_available(frontend_dir_name):
            continue

        if dry_run:
            changes.append(f"(dry-run) Would build missing {label} dist")
            continue

        ok, detail = _build_frontend_dist(frontend_dir_name, label=label)
        if ok:
            changes.append(f"Built missing {label} dist")
        else:
            warnings.append(f"Could not build {label}: {detail}")

    return changes, warnings


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _resolve_agent_template_dir(template_dir: Path | None = None) -> Path | None:
    if template_dir is not None:
        return template_dir

    package_dir = Path(__file__).resolve().parent
    candidates = [
        package_dir / "agent",
        package_dir.parent / "agent",
        package_dir,
    ]
    for candidate in candidates:
        if (candidate / "AGENTS.md").exists():
            return candidate
    return None


def _resolve_workspace(config: dict, home_dir: Path, override: str | None) -> tuple[Path, bool]:
    if override:
        return Path(override).expanduser().resolve(), True

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []

    for agent in agent_list:
        if isinstance(agent, dict) and agent.get("id") == "maestro-personal" and agent.get("workspace"):
            return Path(str(agent["workspace"])).expanduser().resolve(), False

    for agent in agent_list:
        if isinstance(agent, dict) and agent.get("id") == "maestro-company" and agent.get("workspace"):
            return Path(str(agent["workspace"])).expanduser().resolve(), False

    for agent in agent_list:
        if isinstance(agent, dict) and agent.get("id") == "maestro" and agent.get("workspace"):
            return Path(str(agent["workspace"])).expanduser().resolve(), False

    return openclaw_workspace_root(home_dir=home_dir).resolve(), False


def _resolve_company_agent(config: dict) -> dict:
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
    return default_agent if isinstance(default_agent, dict) else {}


def _resolve_personal_agent(config: dict) -> dict:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    personal = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("id") == "maestro-personal"),
        None,
    )
    if isinstance(personal, dict):
        return personal
    default_agent = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("default")),
        None,
    )
    return default_agent if isinstance(default_agent, dict) else {}


def _company_name_from_agent(agent: dict) -> str:
    raw_name = str(agent.get("name", "")).strip()
    if raw_name == COMMANDER_DISPLAY_NAME:
        return "Company"
    if raw_name.startswith("Maestro (") and raw_name.endswith(")"):
        return raw_name[len("Maestro ("):-1].strip() or "Company"
    return raw_name or "Company"


def _resolve_target_profile(config: dict, install_state: dict) -> str:
    state_profile = str(install_state.get("profile", "")).strip().lower()
    if state_profile in (PROFILE_SOLO, PROFILE_FLEET):
        return state_profile
    return infer_profile_from_openclaw_config(config)


def _apply_config_migrations(
    config: dict,
    workspace: Path,
    workspace_forced: bool,
    *,
    target_profile: str,
) -> tuple[dict, list[str]]:
    migrated = copy.deepcopy(config)
    changes: list[str] = []

    if not isinstance(migrated.get("gateway"), dict):
        migrated["gateway"] = {}
        changes.append("Initialized gateway config")
    if migrated["gateway"].get("mode") != "local":
        migrated["gateway"]["mode"] = "local"
        changes.append("Set gateway.mode=local")

    if "maestro" in migrated:
        migrated.pop("maestro", None)
        changes.append("Removed stale top-level maestro key")

    if not isinstance(migrated.get("env"), dict):
        migrated["env"] = {}
        changes.append("Initialized env config")

    if not isinstance(migrated.get("agents"), dict):
        migrated["agents"] = {}
        changes.append("Initialized agents config")
    if not isinstance(migrated["agents"].get("list"), list):
        migrated["agents"]["list"] = []
        changes.append("Initialized agents.list")

    agents = migrated["agents"]["list"]
    company_agent = next((a for a in agents if isinstance(a, dict) and a.get("id") == "maestro-company"), None)
    personal_agent = next((a for a in agents if isinstance(a, dict) and a.get("id") == "maestro-personal"), None)
    legacy_agent = next((a for a in agents if isinstance(a, dict) and a.get("id") == "maestro"), None)

    default_exists = any(isinstance(a, dict) and a.get("default") for a in agents)
    if target_profile == PROFILE_SOLO:
        if personal_agent is None:
            if legacy_agent is not None:
                new_personal = copy.deepcopy(legacy_agent)
                new_personal["id"] = "maestro-personal"
                new_personal["name"] = "Maestro Personal"
                new_personal["workspace"] = str(workspace)
                if not default_exists:
                    new_personal["default"] = True
                agents.append(new_personal)
                changes.append("Added maestro-personal agent from legacy maestro config")
                personal_agent = new_personal
            elif company_agent is not None and not any(str(a.get("id", "")) == "maestro-project" for a in agents if isinstance(a, dict)):
                new_personal = copy.deepcopy(company_agent)
                new_personal["id"] = "maestro-personal"
                new_personal["name"] = "Maestro Personal"
                new_personal["workspace"] = str(workspace)
                if not default_exists:
                    new_personal["default"] = True
                agents.append(new_personal)
                changes.append("Added maestro-personal agent from existing default config")
                personal_agent = new_personal
            else:
                default_model = "google/gemini-3-pro-preview"
                for agent in agents:
                    if isinstance(agent, dict) and agent.get("default") and agent.get("model"):
                        default_model = str(agent.get("model"))
                        break
                personal_agent = {
                    "id": "maestro-personal",
                    "name": "Maestro Personal",
                    "default": True,
                    "model": default_model,
                    "workspace": str(workspace),
                }
                agents.append(personal_agent)
                changes.append("Added missing maestro-personal agent")
        else:
            if workspace_forced and personal_agent.get("workspace") != str(workspace):
                personal_agent["workspace"] = str(workspace)
                changes.append("Updated maestro-personal workspace from --workspace")
            elif not personal_agent.get("workspace"):
                personal_agent["workspace"] = str(workspace)
                changes.append("Set maestro-personal workspace")

            if personal_agent.get("name") != "Maestro Personal":
                personal_agent["name"] = "Maestro Personal"
                changes.append("Set maestro-personal display name")

        # Ensure only personal is default in Solo mode.
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("id", "")).strip()
            if agent_id == "maestro-personal":
                if not agent.get("default"):
                    agent["default"] = True
                    changes.append("Marked maestro-personal as default agent")
            elif agent.get("default") and agent_id != "maestro-personal":
                agent["default"] = False
                changes.append(f"Cleared default flag from {agent_id}")
    else:
        if company_agent is None:
            if legacy_agent is not None:
                new_company = copy.deepcopy(legacy_agent)
                new_company["id"] = "maestro-company"
                new_company["name"] = COMMANDER_DISPLAY_NAME
                new_company["workspace"] = str(workspace)
                if not default_exists:
                    new_company["default"] = True
                agents.append(new_company)
                changes.append("Added maestro-company agent from legacy maestro config")
                company_agent = new_company
            else:
                default_model = default_fleet_model_from_agents(agents, fallback=DEFAULT_COMMANDER_MODEL)

                company_agent = {
                    "id": "maestro-company",
                    "name": COMMANDER_DISPLAY_NAME,
                    "default": True if not default_exists else False,
                    "model": default_model,
                    "workspace": str(workspace),
                }
                agents.append(company_agent)
                changes.append("Added missing maestro-company agent")
        else:
            if workspace_forced and company_agent.get("workspace") != str(workspace):
                company_agent["workspace"] = str(workspace)
                changes.append("Updated maestro-company workspace from --workspace")
            elif not company_agent.get("workspace"):
                company_agent["workspace"] = str(workspace)
                changes.append("Set maestro-company workspace")

            if company_agent.get("name") != COMMANDER_DISPLAY_NAME:
                company_agent["name"] = COMMANDER_DISPLAY_NAME
                changes.append("Set maestro-company display name to The Commander")

            if not default_exists:
                company_agent["default"] = True
                changes.append("Marked maestro-company as default agent")

    if target_profile == PROFILE_FLEET:
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("id", "")).strip()
            if agent_id != "maestro-company" and not agent_id.startswith("maestro-project-"):
                continue
            normalized_model = canonicalize_model(agent.get("model"))
            if normalized_model and str(agent.get("model", "")).strip() != normalized_model:
                agent["model"] = normalized_model
                changes.append(f"Normalized Fleet model for {agent_id}")

    if not isinstance(migrated.get("channels"), dict):
        migrated["channels"] = {}
        changes.append("Initialized channels config")

    telegram = migrated["channels"].get("telegram")
    if isinstance(telegram, dict):
        accounts = telegram.get("accounts")
        if not isinstance(accounts, dict):
            telegram["accounts"] = {}
            accounts = telegram["accounts"]
            changes.append("Initialized telegram.accounts")

        bot_token = telegram.get("botToken")
        if telegram.get("enabled") and bot_token:
            default_account_id = "maestro-company" if target_profile == PROFILE_FLEET else "maestro-personal"
            if default_account_id not in accounts:
                accounts[default_account_id] = {
                    "botToken": bot_token,
                    "dmPolicy": telegram.get("dmPolicy", "pairing"),
                    "groupPolicy": telegram.get("groupPolicy", "allowlist"),
                    "streamMode": telegram.get("streamMode", "partial"),
                }
                changes.append(f"Added telegram account mapping for {default_account_id}")
            if target_profile == PROFILE_FLEET:
                default_account = accounts.get("default")
                if (
                    isinstance(default_account, dict)
                    and str(default_account.get("botToken", "")).strip() == str(bot_token).strip()
                ):
                    accounts.pop("default", None)
                    changes.append("Removed duplicate default telegram account for maestro-company")
                if "botToken" in telegram:
                    telegram.pop("botToken", None)
                    changes.append("Removed top-level telegram botToken in favor of account bindings")

    binding_changes = ensure_telegram_account_bindings(migrated)
    changes.extend(binding_changes)

    return migrated, changes


def _sync_workspace_assets(
    workspace: Path,
    template_root: Path | None,
    dry_run: bool,
    *,
    profile: str,
    company_name: str,
    model: str | None,
    active_provider_env_key: str | None,
    provider_key: str | None,
    gemini_key: str | None,
    command_runner: CommandRunner | None = None,
) -> tuple[list[str], list[str]]:
    changes: list[str] = []
    warnings: list[str] = []

    if not workspace.exists():
        if not dry_run:
            workspace.mkdir(parents=True, exist_ok=True)
        changes.append(f"Created workspace directory: {workspace}")

    if template_root is None:
        warnings.append("Agent template files not found; skipped template sync")
    else:
        for filename in ("SOUL.md", "AGENTS.md", "IDENTITY.md", "USER.md"):
            src = template_root / filename
            dst = workspace / filename
            if src.exists() and not dst.exists():
                if not dry_run:
                    shutil.copy2(src, dst)
                changes.append(f"Added missing workspace file: {filename}")

    if profile == PROFILE_FLEET:
        skill_sync = sync_company_workspace_skill_bundles(
            workspace=workspace,
            template_root=template_root,
            dry_run=dry_run,
        )
        if skill_sync["commander_skill_synced"]:
            changes.append("Synced Commander skill bundle in workspace")
        if skill_sync["maestro_skill_removed"]:
            changes.append("Removed Maestro project skill bundle from Commander workspace")
    else:
        skill_sync = sync_project_workspace_skill_bundles(
            workspace=workspace,
            template_root=template_root,
            dry_run=dry_run,
        )
        if skill_sync["maestro_skill_synced"]:
            changes.append("Synced Maestro project skill bundle in workspace")
        if skill_sync["commander_skill_removed"]:
            changes.append("Removed Commander skill bundle from project workspace")

    desired_agents = render_company_agents_md() if profile == PROFILE_FLEET else render_personal_agents_md()
    desired_role = "company" if profile == PROFILE_FLEET else "project"
    desired_tools = (
        render_tools_md(
            company_name=company_name,
            active_provider_env_key=active_provider_env_key,
        )
        if profile == PROFILE_FLEET
        else render_personal_tools_md(active_provider_env_key=active_provider_env_key)
    )
    desired_identity_files = (
        {
            "SOUL.md": render_company_soul_md(),
            "IDENTITY.md": render_company_identity_md(),
            "USER.md": render_company_user_md(),
        }
        if profile == PROFILE_FLEET
        else {}
    )
    stale_company_markers = {
        "SOUL.md": (
            "license boundaries",
            "do not bypass license policy",
        ),
        "IDENTITY.md": (),
        "USER.md": (),
        "AGENTS.md": (
            "for license lifecycle",
        ),
        "TOOLS.md": (
            "handle license lifecycle",
            "maestro-fleet license generate",
        ),
    }

    def _should_refresh_company_generated_file(filename: str, current_content: str) -> bool:
        if profile != PROFILE_FLEET or not current_content.strip():
            return False
        markers = stale_company_markers.get(filename, ())
        lowered = current_content.lower()
        return any(marker in lowered for marker in markers)

    for filename, desired_content in desired_identity_files.items():
        dst = workspace / filename
        current_content = dst.read_text(encoding="utf-8") if dst.exists() else ""
        template_content = ""
        if template_root is not None:
            src = template_root / filename
            if src.exists():
                template_content = src.read_text(encoding="utf-8")

        needs_write = False
        change_label = ""
        if not dst.exists():
            needs_write = True
            change_label = f"Added missing {filename}"
        elif template_content and current_content.strip() == template_content.strip():
            needs_write = True
            change_label = f"Updated generic {filename} for Commander role"
        elif _should_refresh_company_generated_file(filename, current_content):
            needs_write = True
            change_label = f"Updated stale {filename} for Commander role"

        if needs_write:
            if not dry_run:
                dst.write_text(desired_content, encoding="utf-8")
            changes.append(change_label)

    agents_md = workspace / "AGENTS.md"
    current_agents = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
    if not agents_md.exists():
        if not dry_run:
            agents_md.write_text(desired_agents, encoding="utf-8")
        changes.append("Added missing AGENTS.md")
    elif _should_refresh_company_generated_file("AGENTS.md", current_agents):
        if not dry_run:
            agents_md.write_text(desired_agents, encoding="utf-8")
        changes.append("Updated stale AGENTS.md for Commander role")

    tools_md = workspace / "TOOLS.md"
    current_tools = tools_md.read_text(encoding="utf-8") if tools_md.exists() else ""
    if not tools_md.exists():
        if not dry_run:
            tools_md.write_text(desired_tools, encoding="utf-8")
        changes.append("Added missing TOOLS.md")
    elif _should_refresh_company_generated_file("TOOLS.md", current_tools):
        if not dry_run:
            tools_md.write_text(desired_tools, encoding="utf-8")
        changes.append("Updated stale TOOLS.md for Commander role")

    env_file = workspace / ".env"
    if not env_file.exists():
        if not dry_run:
            env_file.write_text(
                render_workspace_env(
                    store_path="knowledge_store/",
                    provider_env_key=active_provider_env_key,
                    provider_key=provider_key,
                    gemini_key=gemini_key,
                    agent_role=desired_role,
                ),
                encoding="utf-8",
            )
        changes.append("Added missing workspace .env")
    else:
        current_env = env_file.read_text(encoding="utf-8")
        expected_line = f"MAESTRO_AGENT_ROLE={desired_role}"
        if expected_line not in current_env:
            if not dry_run:
                with env_file.open("a", encoding="utf-8") as handle:
                    handle.write(f"{expected_line}\n")
            changes.append(f"Set {expected_line} in workspace .env")

    knowledge_store = workspace / "knowledge_store"
    if not knowledge_store.exists():
        if not dry_run:
            knowledge_store.mkdir(parents=True, exist_ok=True)
        changes.append("Created workspace knowledge_store directory")

    route_path = "/command-center" if profile == PROFILE_FLEET else "/workspace"
    surface_label = "Command Center" if profile == PROFILE_FLEET else "Workspace"
    if sync_workspace_awareness_file(
        workspace=workspace,
        model=str(model or "").strip() or "unknown",
        store_root=knowledge_store.resolve(),
        route_path=route_path,
        resolve_network_urls_fn=resolve_network_urls,
        surface_label=surface_label,
        generated_by="maestro update",
        command_runner=command_runner,
        dry_run=dry_run,
    ):
        changes.append("Updated workspace AWARENESS.md")

    return changes, warnings


def _read_env_value(env_path: Path, key: str) -> str:
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key:
            return value.strip()
    return ""


def _load_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return _load_json(path)
    except Exception:
        return {}


def _project_model_from_store(store_root: str | Path | None) -> str:
    if not store_root:
        return ""
    project_json = Path(store_root).expanduser().resolve() / "project.json"
    payload = _load_json_or_empty(project_json)
    maestro_meta = payload.get("maestro") if isinstance(payload.get("maestro"), dict) else {}
    if not isinstance(maestro_meta, dict):
        return ""
    return canonicalize_model(maestro_meta.get("model"))


def _sync_fleet_project_workspace_assets(
    workspace: Path,
    config: dict[str, Any],
    *,
    dry_run: bool,
    command_runner: CommandRunner | None = None,
) -> list[str]:
    projects_root = workspace / "projects"
    if not projects_root.exists():
        return []

    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    changes: list[str] = []

    for project_workspace in sorted(projects_root.iterdir()):
        if not project_workspace.is_dir():
            continue
        slug = project_workspace.name
        agent_id = f"maestro-project-{slug}"
        store_root = _read_env_value(project_workspace / ".env", "MAESTRO_STORE")
        if not store_root:
            store_root = str((project_workspace / "knowledge_store").resolve())

        agent = next(
            (item for item in agent_list if isinstance(item, dict) and str(item.get("id", "")).strip() == agent_id),
            {},
        )
        model = canonicalize_model(agent.get("model"))
        if not model:
            model = _project_model_from_store(store_root)
        model = model or "unknown"

        sync_result = sync_project_workspace_runtime_files(
            project_workspace=project_workspace,
            project_slug=slug,
            model=model,
            store_root=store_root,
            generated_by="maestro update",
            resolve_network_urls_fn=resolve_network_urls,
            command_runner=command_runner,
            dry_run=dry_run,
        )
        if sync_result["awareness_updated"]:
            changes.append(f"Updated project workspace AWARENESS.md: {slug}")

        if sync_result["agents_updated"]:
            changes.append(f"Updated project workspace AGENTS.md: {slug}")

        if sync_result["tools_updated"]:
            changes.append(f"Updated project workspace TOOLS.md: {slug}")

        if sync_result["maestro_skill_synced"]:
            changes.append(f"Synced project workspace Maestro skill: {slug}")

        if sync_result["commander_skill_removed"]:
            changes.append(f"Removed Commander skill from project workspace: {slug}")

        if sync_result["bootstrap_removed"]:
            changes.append(f"Removed generic project BOOTSTRAP.md: {slug}")

    return changes


def _ensure_session_dir(home_dir: Path, dry_run: bool, *, profile: str) -> bool:
    agent_id = "maestro-company" if profile == PROFILE_FLEET else "maestro-personal"
    sessions = openclaw_state_root(home_dir=home_dir) / "agents" / agent_id / "sessions"
    if sessions.exists():
        return False
    if not dry_run:
        sessions.mkdir(parents=True, exist_ok=True)
    return True


def _backfill_registry_identity(workspace: Path, config: dict, *, dry_run: bool) -> list[str]:
    """Backfill project Telegram identity metadata from Telegram account bindings."""
    store_root = (workspace / "knowledge_store").resolve()
    if not store_root.exists():
        return []

    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram", {}) if isinstance(channels.get("telegram"), dict) else {}
    accounts = telegram.get("accounts", {}) if isinstance(telegram.get("accounts"), dict) else {}

    changed = False
    messages: list[str] = []
    for project_dir in discover_project_dirs(store_root):
        payload = _load_json_or_empty(project_dir / "project.json")
        slug = str(payload.get("slug", "")).strip() or project_dir.name
        if not slug:
            continue
        maestro_meta = payload.get("maestro") if isinstance(payload.get("maestro"), dict) else {}
        if not isinstance(maestro_meta, dict):
            maestro_meta = {}

        account = accounts.get(f"maestro-project-{slug}", {}) if isinstance(accounts.get(f"maestro-project-{slug}"), dict) else {}
        username = str(account.get("username") or account.get("telegram_bot_username") or "").strip()
        display_name = str(account.get("display_name") or account.get("telegram_bot_display_name") or "").strip()

        entry_changed = False
        if username and str(maestro_meta.get("telegram_bot_username", "")).strip() != username:
            maestro_meta["telegram_bot_username"] = username
            entry_changed = True
            changed = True
        if display_name and str(maestro_meta.get("telegram_bot_display_name", "")).strip() != display_name:
            maestro_meta["telegram_bot_display_name"] = display_name
            entry_changed = True
            changed = True

        if entry_changed and not dry_run:
            payload["maestro"] = maestro_meta
            _save_json(project_dir / "project.json", payload)

    if changed:
        messages.append("Backfilled project Telegram identity metadata")
    return messages


def _create_backup(config_path: Path, home_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = home_dir / ".maestro" / "backups" / f"update-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, backup_dir / "openclaw.json")
    return backup_dir


def _telegram_is_configured(config: dict) -> bool:
    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    tg = channels.get("telegram")
    if not isinstance(tg, dict):
        return False
    if tg.get("enabled") and tg.get("botToken"):
        return True
    accounts = tg.get("accounts")
    return isinstance(accounts, dict) and any(
        isinstance(data, dict) and data.get("botToken") for data in accounts.values()
    )


def _resolve_profile_url(command_runner: CommandRunner, *, profile: str) -> str:
    path = "/command-center" if profile == PROFILE_FLEET else "/workspace"
    ok, output = command_runner("tailscale ip -4")
    if ok and output:
        ip = output.splitlines()[0].strip()
        if ip:
            return f"http://{ip}:3000{path}"
    return f"http://localhost:3000{path}"


def _restart_gateway_if_available(
    restart_gateway: bool,
    dry_run: bool,
    command_runner: CommandRunner,
    warnings: list[str],
):
    if not restart_gateway:
        return

    if shutil.which("openclaw") is None:
        warnings.append("openclaw not found on PATH; skipped gateway restart")
        return

    if dry_run:
        return

    ok, status_output = command_runner("openclaw status")
    status_lower = status_output.lower() if status_output else ""

    if ok and "running" in status_lower:
        restart_ok, restart_output = command_runner("openclaw gateway restart")
        if not restart_ok:
            warnings.append(f"Gateway restart failed: {restart_output or 'unknown error'}")
    else:
        start_ok, start_output = command_runner("openclaw gateway start")
        if not start_ok:
            warnings.append(f"Gateway start failed: {start_output or 'unknown error'}")


def perform_update(
    workspace_override: str | None = None,
    restart_gateway: bool = True,
    dry_run: bool = False,
    home_dir: Path | None = None,
    template_dir: Path | None = None,
    command_runner: CommandRunner | None = None,
) -> tuple[UpdateSummary, int]:
    summary = UpdateSummary()
    home = (home_dir or Path.home()).resolve()

    config_path = openclaw_config_path(home_dir=home)
    if not config_path.exists():
        summary.warnings.append(f"OpenClaw config not found: {config_path}")
        summary.warnings.append("Run maestro-setup first.")
        return summary, 1

    try:
        config = _load_json(config_path)
    except Exception as exc:
        summary.warnings.append(f"Could not read {config_path}: {exc}")
        return summary, 1
    current_install_state = load_install_state(home_dir=home)
    target_profile = _resolve_target_profile(config, current_install_state)
    if target_profile == PROFILE_FLEET:
        safe_override, override_message = ensure_openclaw_override_allowed(config)
        if not safe_override:
            summary.warnings.append(override_message)
            return summary, 1

    workspace, workspace_forced = _resolve_workspace(config, home, workspace_override)
    summary.workspace = workspace

    migrated, config_changes = _apply_config_migrations(
        config,
        workspace,
        workspace_forced,
        target_profile=target_profile,
    )
    summary.config_changed = bool(config_changes)
    summary.changes.extend(config_changes)

    primary_agent = (
        _resolve_company_agent(migrated)
        if target_profile == PROFILE_FLEET
        else _resolve_personal_agent(migrated)
    )
    company_name = _company_name_from_agent(primary_agent)
    model = str(primary_agent.get("model", "")).strip()
    provider_env_key = provider_env_key_for_model(model)
    env = migrated.get("env", {}) if isinstance(migrated.get("env"), dict) else {}
    provider_key = env.get(provider_env_key) if provider_env_key else None
    provider_key_str = provider_key if isinstance(provider_key, str) else None
    gemini_key = env.get("GEMINI_API_KEY")
    gemini_key_str = gemini_key if isinstance(gemini_key, str) else None

    template_root = _resolve_agent_template_dir(template_dir)
    workspace_changes, workspace_warnings = _sync_workspace_assets(
        workspace,
        template_root,
        dry_run=dry_run,
        profile=target_profile,
        company_name=company_name,
        model=model,
        active_provider_env_key=provider_env_key,
        provider_key=provider_key_str,
        gemini_key=gemini_key_str,
        command_runner=command_runner,
    )
    summary.workspace_changed = bool(workspace_changes)
    summary.changes.extend(workspace_changes)
    summary.warnings.extend(workspace_warnings)
    if target_profile == PROFILE_FLEET:
        project_workspace_changes = _sync_fleet_project_workspace_assets(
            workspace,
            migrated,
            dry_run=dry_run,
            command_runner=command_runner,
        )
        if project_workspace_changes:
            summary.workspace_changed = True
            summary.changes.extend(project_workspace_changes)
        identity_changes = _backfill_registry_identity(workspace, migrated, dry_run=dry_run)
        if identity_changes:
            summary.workspace_changed = True
            summary.changes.extend(identity_changes)

    if _ensure_session_dir(home, dry_run=dry_run, profile=target_profile):
        summary.session_dir_created = True
        session_agent_id = "maestro-company" if target_profile == PROFILE_FLEET else "maestro-personal"
        summary.changes.append(f"Created {session_agent_id} session directory")

    if summary.config_changed and not dry_run:
        summary.backup_dir = _create_backup(config_path, home)
        _save_json(config_path, migrated)
    elif summary.config_changed and dry_run:
        summary.changes.append("(dry-run) Would update openclaw.json")

    summary.telegram_configured = _telegram_is_configured(migrated)

    runner = command_runner or _default_command_runner
    _restart_gateway_if_available(
        restart_gateway=restart_gateway,
        dry_run=dry_run,
        command_runner=runner,
        warnings=summary.warnings,
    )
    summary.command_center_url = _resolve_profile_url(runner, profile=target_profile)

    install_state = {
        "version": 2,
        "profile": target_profile,
        "fleet_enabled": target_profile == PROFILE_FLEET,
        "workspace_root": str(workspace.resolve()),
        "store_root": str((workspace / "knowledge_store").resolve()),
        "fleet_store_root": str((workspace / "knowledge_store").resolve()),
        "company_name": company_name,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not dry_run:
        save_install_state(install_state, home_dir=home)
    else:
        summary.changes.append("(dry-run) Would sync install state")

    summary.changed = bool(summary.changes)
    return summary, 0


def run_update(
    workspace_override: str | None = None,
    restart_gateway: bool = True,
    dry_run: bool = False,
) -> int:
    summary, exit_code = perform_update(
        workspace_override=workspace_override,
        restart_gateway=restart_gateway,
        dry_run=dry_run,
    )

    if exit_code != 0:
        for warning in summary.warnings:
            print(f"[WARN] {warning}")
        return exit_code

    install_state = load_install_state()
    profile = str(install_state.get("profile", "solo")).strip() or "solo"
    frontend_changes, frontend_warnings = _ensure_frontend_artifacts(profile, dry_run=dry_run)
    if frontend_changes:
        summary.changes.extend(frontend_changes)
        summary.changed = True
    if frontend_warnings:
        summary.warnings.extend(frontend_warnings)

    print("Maestro update summary")
    print(f"- Workspace: {summary.workspace}")
    print(f"- Profile: {profile}")

    if summary.changed:
        print("- Changes applied:" if not dry_run else "- Planned changes:")
        for change in summary.changes:
            print(f"  - {change}")
    else:
        print("- No changes needed (already up-to-date)")

    if summary.backup_dir:
        print(f"- Backup: {summary.backup_dir}")

    print(f"- Telegram configured: {'yes' if summary.telegram_configured else 'no'}")
    if profile == PROFILE_FLEET:
        print(f"- Command Center: {summary.command_center_url}")
    else:
        print(f"- Workspace: {summary.command_center_url}")

    for warning in summary.warnings:
        print(f"[WARN] {warning}")

    return 0
