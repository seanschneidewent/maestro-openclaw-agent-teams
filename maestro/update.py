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
from typing import Callable

from .control_plane import (
    ensure_telegram_account_bindings,
    resolve_node_identity,
    save_fleet_registry,
    sync_fleet_registry,
)
from .workspace_templates import (
    provider_env_key_for_model,
    render_company_agents_md,
    render_tools_md,
    render_workspace_env,
)
from .install_state import save_install_state


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
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    except Exception as exc:
        return False, str(exc)

    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


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
        if isinstance(agent, dict) and agent.get("id") == "maestro-company" and agent.get("workspace"):
            return Path(str(agent["workspace"])).expanduser().resolve(), False

    for agent in agent_list:
        if isinstance(agent, dict) and agent.get("id") == "maestro" and agent.get("workspace"):
            return Path(str(agent["workspace"])).expanduser().resolve(), False

    return (home_dir / ".openclaw" / "workspace-maestro").resolve(), False


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


def _company_name_from_agent(agent: dict) -> str:
    raw_name = str(agent.get("name", "")).strip()
    if raw_name == COMMANDER_DISPLAY_NAME:
        return "Company"
    if raw_name.startswith("Maestro (") and raw_name.endswith(")"):
        return raw_name[len("Maestro ("):-1].strip() or "Company"
    return raw_name or "Company"


def _apply_config_migrations(config: dict, workspace: Path, workspace_forced: bool) -> tuple[dict, list[str]]:
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
    legacy_agent = next((a for a in agents if isinstance(a, dict) and a.get("id") == "maestro"), None)

    default_exists = any(isinstance(a, dict) and a.get("default") for a in agents)

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
            default_model = "google/gemini-3-pro-preview"
            for agent in agents:
                if isinstance(agent, dict) and agent.get("default") and agent.get("model"):
                    default_model = str(agent.get("model"))
                    break
            if default_model == "google/gemini-3-pro-preview":
                for agent in agents:
                    if isinstance(agent, dict) and agent.get("model"):
                        default_model = str(agent.get("model"))
                        break

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
        if telegram.get("enabled") and bot_token and "maestro-company" not in accounts:
            accounts["maestro-company"] = {
                "botToken": bot_token,
                "dmPolicy": telegram.get("dmPolicy", "pairing"),
                "groupPolicy": telegram.get("groupPolicy", "allowlist"),
                "streamMode": telegram.get("streamMode", "partial"),
            }
            changes.append("Added telegram account mapping for maestro-company")

    binding_changes = ensure_telegram_account_bindings(migrated)
    changes.extend(binding_changes)

    return migrated, changes


def _sync_workspace_assets(
    workspace: Path,
    template_root: Path | None,
    dry_run: bool,
    *,
    company_name: str,
    active_provider_env_key: str | None,
    provider_key: str | None,
    gemini_key: str | None,
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

        skill_src = template_root / "skills" / "maestro"
        skill_dst = workspace / "skills" / "maestro"
        if skill_src.exists() and not skill_dst.exists():
            if not dry_run:
                skill_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(skill_src, skill_dst)
            changes.append("Added missing Maestro skill in workspace")

    company_agents = render_company_agents_md()
    agents_md = workspace / "AGENTS.md"
    if not agents_md.exists():
        if not dry_run:
            agents_md.write_text(company_agents, encoding="utf-8")
        changes.append("Added missing Company AGENTS.md")
    else:
        current_agents = agents_md.read_text(encoding="utf-8")
        # Migrate legacy project-style AGENTS in company workspace.
        if "Check `knowledge_store/` — this is what you know" in current_agents:
            if not dry_run:
                agents_md.write_text(company_agents, encoding="utf-8")
            changes.append("Updated company AGENTS.md to control-plane policy")

    tools_md = workspace / "TOOLS.md"
    if not tools_md.exists():
        content = render_tools_md(
            company_name=company_name,
            active_provider_env_key=active_provider_env_key,
        )
        if not dry_run:
            tools_md.write_text(content, encoding="utf-8")
        changes.append("Added missing TOOLS.md")

    env_file = workspace / ".env"
    if not env_file.exists():
        if not dry_run:
            env_file.write_text(
                render_workspace_env(
                    store_path="knowledge_store/",
                    provider_env_key=active_provider_env_key,
                    provider_key=provider_key,
                    gemini_key=gemini_key,
                    agent_role="company",
                ),
                encoding="utf-8",
            )
        changes.append("Added missing workspace .env")
    else:
        current_env = env_file.read_text(encoding="utf-8")
        if "MAESTRO_AGENT_ROLE=" not in current_env:
            if not dry_run:
                with env_file.open("a", encoding="utf-8") as handle:
                    handle.write("MAESTRO_AGENT_ROLE=company\n")
            changes.append("Set MAESTRO_AGENT_ROLE=company in workspace .env")

    knowledge_store = workspace / "knowledge_store"
    if not knowledge_store.exists():
        if not dry_run:
            knowledge_store.mkdir(parents=True, exist_ok=True)
        changes.append("Created workspace knowledge_store directory")

    return changes, warnings


def _ensure_session_dir(home_dir: Path, dry_run: bool) -> bool:
    sessions = home_dir / ".openclaw" / "agents" / "maestro-company" / "sessions"
    if sessions.exists():
        return False
    if not dry_run:
        sessions.mkdir(parents=True, exist_ok=True)
    return True


def _backfill_registry_identity(workspace: Path, config: dict, *, dry_run: bool) -> list[str]:
    """Backfill fleet registry node identity from Telegram account metadata."""
    store_root = (workspace / "knowledge_store").resolve()
    if not store_root.exists():
        return []

    registry = sync_fleet_registry(store_root, dry_run=dry_run)
    projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram", {}) if isinstance(channels.get("telegram"), dict) else {}
    accounts = telegram.get("accounts", {}) if isinstance(telegram.get("accounts"), dict) else {}

    changed = False
    messages: list[str] = []
    for entry in projects:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("project_slug", "")).strip()
        if not slug:
            continue
        agent_id = str(entry.get("maestro_agent_id", "")).strip() or f"maestro-project-{slug}"
        account = accounts.get(agent_id, {}) if isinstance(accounts.get(agent_id), dict) else {}

        username = str(
            account.get("username")
            or account.get("telegram_bot_username")
            or ""
        ).strip()
        display_name = str(
            account.get("display_name")
            or account.get("telegram_bot_display_name")
            or ""
        ).strip()

        if username and str(entry.get("telegram_bot_username", "")).strip() != username:
            entry["telegram_bot_username"] = username
            changed = True
        if display_name and str(entry.get("telegram_bot_display_name", "")).strip() != display_name:
            entry["telegram_bot_display_name"] = display_name
            changed = True

        node_display_name, source, node_handle = resolve_node_identity(entry)
        if str(entry.get("node_display_name", "")).strip() != node_display_name:
            entry["node_display_name"] = node_display_name
            changed = True
        if str(entry.get("node_identity_source", "")).strip() != source:
            entry["node_identity_source"] = source
            changed = True
        if str(entry.get("node_handle", "")).strip() != node_handle:
            entry["node_handle"] = node_handle
            changed = True

    if changed:
        if not dry_run:
            save_fleet_registry(store_root, {
                "version": int(registry.get("version", 1)),
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "store_root": str(store_root),
                "projects": projects,
            })
        messages.append("Backfilled fleet registry node identity metadata")
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


def _resolve_command_center_url(command_runner: CommandRunner) -> str:
    ok, output = command_runner("tailscale ip -4")
    if ok and output:
        ip = output.splitlines()[0].strip()
        if ip:
            return f"http://{ip}:3000/command-center"
    return "http://localhost:3000/command-center"


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
    config_path = home / ".openclaw" / "openclaw.json"
    if not config_path.exists():
        summary.warnings.append(f"OpenClaw config not found: {config_path}")
        summary.warnings.append("Run maestro-setup first.")
        return summary, 1

    try:
        config = _load_json(config_path)
    except Exception as exc:
        summary.warnings.append(f"Could not read {config_path}: {exc}")
        return summary, 1

    workspace, workspace_forced = _resolve_workspace(config, home, workspace_override)
    summary.workspace = workspace

    migrated, config_changes = _apply_config_migrations(config, workspace, workspace_forced)
    summary.config_changed = bool(config_changes)
    summary.changes.extend(config_changes)

    company_agent = _resolve_company_agent(migrated)
    company_name = _company_name_from_agent(company_agent)
    model = str(company_agent.get("model", "")).strip()
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
        company_name=company_name,
        active_provider_env_key=provider_env_key,
        provider_key=provider_key_str,
        gemini_key=gemini_key_str,
    )
    summary.workspace_changed = bool(workspace_changes)
    summary.changes.extend(workspace_changes)
    summary.warnings.extend(workspace_warnings)
    identity_changes = _backfill_registry_identity(workspace, migrated, dry_run=dry_run)
    if identity_changes:
        summary.workspace_changed = True
        summary.changes.extend(identity_changes)

    if _ensure_session_dir(home, dry_run=dry_run):
        summary.session_dir_created = True
        summary.changes.append("Created maestro-company session directory")

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
    summary.command_center_url = _resolve_command_center_url(runner)

    install_state = {
        "workspace_root": str(workspace.resolve()),
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

    print("Maestro update summary")
    print(f"- Workspace: {summary.workspace}")

    if summary.changed:
        print("- Changes applied:" if not dry_run else "- Planned changes:")
        for change in summary.changes:
            print(f"  - {change}")
    else:
        print("- No changes needed (already up-to-date)")

    if summary.backup_dir:
        print(f"- Backup: {summary.backup_dir}")

    print(f"- Telegram configured: {'yes' if summary.telegram_configured else 'no'}")
    print(f"- Command Center: {summary.command_center_url}")

    for warning in summary.warnings:
        print(f"[WARN] {warning}")

    return 0
