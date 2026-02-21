"""Maestro updater.

Provides a safe, idempotent `maestro update` path for existing installs.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


CommandRunner = Callable[[str], tuple[bool, str]]


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
            new_company.setdefault("name", "Maestro (Company)")
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
                "name": "Maestro (Company)",
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

        if not company_agent.get("name"):
            company_agent["name"] = "Maestro (Company)"
            changes.append("Set maestro-company name")

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

    return migrated, changes


def _sync_workspace_assets(workspace: Path, template_root: Path | None, dry_run: bool) -> tuple[list[str], list[str]]:
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

    tools_md = workspace / "TOOLS.md"
    if not tools_md.exists():
        content = (
            "# TOOLS.md — Company Maestro\n\n"
            "## Role\n"
            "- Company-level orchestration agent\n"
            "- Command Center owner\n\n"
            "## Key Paths\n"
            "- Knowledge store: `knowledge_store/`\n"
            "- Command Center: `http://localhost:3000/command-center`\n"
        )
        if not dry_run:
            tools_md.write_text(content, encoding="utf-8")
        changes.append("Added missing TOOLS.md")

    env_file = workspace / ".env"
    if not env_file.exists():
        if not dry_run:
            env_file.write_text("MAESTRO_STORE=knowledge_store/\n", encoding="utf-8")
        changes.append("Added missing workspace .env")

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

    template_root = _resolve_agent_template_dir(template_dir)
    workspace_changes, workspace_warnings = _sync_workspace_assets(workspace, template_root, dry_run=dry_run)
    summary.workspace_changed = bool(workspace_changes)
    summary.changes.extend(workspace_changes)
    summary.warnings.extend(workspace_warnings)

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
