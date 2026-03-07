"""Tests for maestro.update."""

from __future__ import annotations

import json
from pathlib import Path

from maestro.profile import PROFILE_FLEET
from maestro.update import _ensure_frontend_artifacts, perform_update
from maestro.workspace_templates import render_workspace_awareness_md


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_template_dir(base: Path) -> Path:
    tmpl = base / "templates"
    tmpl.mkdir(parents=True, exist_ok=True)
    for filename in ("SOUL.md", "AGENTS.md", "IDENTITY.md", "USER.md"):
        (tmpl / filename).write_text(f"# {filename}\n", encoding="utf-8")

    skill_dir = tmpl / "skills" / "maestro"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Maestro Skill\n", encoding="utf-8")
    return tmpl


def _default_telegram() -> dict:
    return {
        "enabled": True,
        "accounts": {
            "maestro-company": {
                "botToken": "123456:ABC_DEF",
                "dmPolicy": "pairing",
                "groupPolicy": "allowlist",
                "streamMode": "partial",
            }
        },
    }


def _default_bindings() -> list[dict]:
    return [
        {
            "agentId": "maestro-company",
            "match": {"channel": "telegram", "accountId": "maestro-company"},
        }
    ]


def test_update_no_changes_when_already_current(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    sessions = openclaw_dir / "agents" / "maestro-company" / "sessions"

    template_dir = _make_template_dir(tmp_path)

    config = {
        "gateway": {"mode": "local"},
        "env": {"GEMINI_API_KEY": "test-key"},
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "The Commander",
                    "default": True,
                    "model": "google/gemini-3-pro-preview",
                    "workspace": str(workspace),
                }
            ]
        },
        "channels": {"telegram": _default_telegram()},
        "bindings": _default_bindings(),
    }
    config_path = openclaw_dir / "openclaw.json"
    _write_json(config_path, config)

    workspace.mkdir(parents=True, exist_ok=True)
    for filename in ("SOUL.md", "AGENTS.md", "IDENTITY.md", "USER.md"):
        (workspace / filename).write_text("existing\n", encoding="utf-8")
    (workspace / "TOOLS.md").write_text("existing\n", encoding="utf-8")
    (workspace / ".env").write_text(
        "MAESTRO_AGENT_ROLE=company\nMAESTRO_STORE=knowledge_store/\n",
        encoding="utf-8",
    )
    (workspace / "knowledge_store").mkdir(exist_ok=True)
    (workspace / "AWARENESS.md").write_text(
        render_workspace_awareness_md(
            model="google/gemini-3-pro-preview",
            preferred_url="http://localhost:3000/command-center",
            local_url="http://localhost:3000/command-center",
            tailnet_url="",
            store_root=workspace / "knowledge_store",
            surface_label="Command Center",
            generated_by="maestro update",
        ),
        encoding="utf-8",
    )
    (workspace / "skills" / "maestro").mkdir(parents=True, exist_ok=True)
    sessions.mkdir(parents=True, exist_ok=True)

    before = config_path.read_text(encoding="utf-8")

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert not summary.changed
    assert not summary.config_changed
    assert not summary.workspace_changed
    assert summary.backup_dir is None
    assert config_path.read_text(encoding="utf-8") == before


def test_update_migrates_legacy_agent_and_preserves_telegram(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "maestro": {"install_id": "legacy-install"},
        "agents": {
            "list": [
                {
                    "id": "maestro",
                    "name": "Maestro",
                    "default": True,
                    "model": "openai/gpt-5.2",
                    "workspace": str(workspace),
                }
            ]
        },
        "channels": {
            "telegram": {
                "enabled": True,
                "botToken": "123456:ABC_DEF",
                "dmPolicy": "pairing",
                "groupPolicy": "allowlist",
                "streamMode": "partial",
            }
        },
    }
    config_path = openclaw_dir / "openclaw.json"
    _write_json(config_path, config)

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert summary.changed
    assert summary.config_changed
    assert summary.telegram_configured
    assert summary.backup_dir is not None
    assert (summary.backup_dir / "openclaw.json").exists()

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    agents = updated.get("agents", {}).get("list", [])
    assert any(a.get("id") == "maestro-company" for a in agents if isinstance(a, dict))
    assert any(a.get("id") == "maestro-company" and a.get("name") == "The Commander" for a in agents if isinstance(a, dict))
    assert updated.get("maestro") is None

    telegram = updated.get("channels", {}).get("telegram", {})
    accounts = telegram.get("accounts", {})
    assert accounts.get("maestro-company", {}).get("botToken") == "123456:ABC_DEF"
    assert "botToken" not in telegram
    assert "default" not in accounts
    bindings = updated.get("bindings", [])
    assert {
        "agentId": "maestro-company",
        "match": {"channel": "telegram", "accountId": "maestro-company"},
    } in bindings
    awareness = (workspace / "AWARENESS.md").read_text(encoding="utf-8")
    assert "Recommended Command Center URL: `http://localhost:3000/command-center`" in awareness


def test_update_removes_duplicate_default_telegram_account_for_fleet(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "The Commander",
                    "default": True,
                    "model": "openai/gpt-5.4",
                    "workspace": str(workspace),
                }
            ]
        },
        "channels": {
            "telegram": {
                "enabled": True,
                "botToken": "123456:ABC_DEF",
                "accounts": {
                    "maestro-company": {
                        "botToken": "123456:ABC_DEF",
                        "dmPolicy": "pairing",
                        "groupPolicy": "allowlist",
                        "streamMode": "partial",
                    },
                    "default": {
                        "botToken": "123456:ABC_DEF",
                        "dmPolicy": "pairing",
                        "groupPolicy": "allowlist",
                        "streamMode": "partial",
                    },
                },
            }
        },
        "bindings": _default_bindings(),
    }
    config_path = openclaw_dir / "openclaw.json"
    _write_json(config_path, config)

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert summary.changed

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    telegram = updated.get("channels", {}).get("telegram", {})
    accounts = telegram.get("accounts", {})
    assert "botToken" not in telegram
    assert "default" not in accounts
    assert accounts.get("maestro-company", {}).get("botToken") == "123456:ABC_DEF"


def test_update_backfills_project_workspace_awareness_and_agents(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    project_workspace = workspace / "projects" / "alpha-project"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "The Commander",
                    "default": True,
                    "model": "openai/gpt-5.4",
                    "workspace": str(workspace),
                },
                {
                    "id": "maestro-project-alpha-project",
                    "name": "Maestro (Alpha Project)",
                    "default": False,
                    "model": "openai/gpt-5.4",
                    "workspace": str(project_workspace),
                },
            ]
        },
        "channels": {"telegram": _default_telegram()},
        "bindings": _default_bindings(),
    }
    _write_json(openclaw_dir / "openclaw.json", config)

    project_workspace.mkdir(parents=True, exist_ok=True)
    (project_workspace / ".env").write_text(
        "MAESTRO_AGENT_ROLE=project\nMAESTRO_STORE=/tmp/alpha-store\n",
        encoding="utf-8",
    )
    (project_workspace / "AGENTS.md").write_text("# AGENTS.md - Your Workspace\nIf `BOOTSTRAP.md` exists, that's your birth certificate.\n", encoding="utf-8")
    (project_workspace / "TOOLS.md").write_text("# TOOLS.md - Local Notes\nCamera names and locations\n", encoding="utf-8")
    (project_workspace / "BOOTSTRAP.md").write_text("# BOOTSTRAP.md - Hello, World\nYou just woke up.\n", encoding="utf-8")

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert summary.changed
    awareness = (project_workspace / "AWARENESS.md").read_text(encoding="utf-8")
    assert "Local Workspace URL: `http://localhost:3000/alpha-project/`" in awareness
    assert f"Store Root: `{Path('/tmp/alpha-store').resolve()}`" in awareness
    agents_md = (project_workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "Read `AWARENESS.md` for current model + workspace URLs" in agents_md
    tools_md = (project_workspace / "TOOLS.md").read_text(encoding="utf-8")
    assert "Read `AWARENESS.md` and use the recommended workspace URL." in tools_md
    assert not (project_workspace / "BOOTSTRAP.md").exists()


def test_update_passes_command_runner_to_project_workspace_url_sync(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    project_workspace = workspace / "projects" / "alpha-project"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "The Commander",
                    "default": True,
                    "model": "openai/gpt-5.4",
                    "workspace": str(workspace),
                },
                {
                    "id": "maestro-project-alpha-project",
                    "name": "Maestro (Alpha Project)",
                    "default": False,
                    "model": "openai/gpt-5.4",
                    "workspace": str(project_workspace),
                },
            ]
        },
        "channels": {"telegram": _default_telegram()},
        "bindings": _default_bindings(),
    }
    _write_json(openclaw_dir / "openclaw.json", config)

    project_workspace.mkdir(parents=True, exist_ok=True)
    (project_workspace / ".env").write_text(
        "MAESTRO_AGENT_ROLE=project\nMAESTRO_STORE=/tmp/alpha-store\n",
        encoding="utf-8",
    )

    def sentinel_runner(command: str):
        _ = command
        return False, ""

    observed: list[tuple[str, object | None]] = []

    def fake_resolve_network_urls(*, route_path: str = "/command-center", command_runner=None, **_: object):
        observed.append((route_path, command_runner))
        return {
            "recommended_url": f"http://localhost:3000{route_path}",
            "localhost_url": f"http://localhost:3000{route_path}",
            "tailnet_url": "",
        }

    monkeypatch.setattr("maestro.update.resolve_network_urls", fake_resolve_network_urls)

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=sentinel_runner,
    )

    assert code == 0
    assert summary.changed
    assert ("/alpha-project/", sentinel_runner) in observed


def test_update_dry_run_does_not_write_files(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "agents": {
            "list": [
                {
                    "id": "maestro",
                    "name": "Maestro",
                    "default": True,
                    "model": "anthropic/claude-opus-4-6",
                    "workspace": str(workspace),
                }
            ]
        }
    }
    config_path = openclaw_dir / "openclaw.json"
    _write_json(config_path, config)
    before = config_path.read_text(encoding="utf-8")

    summary, code = perform_update(
        restart_gateway=False,
        dry_run=True,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert summary.changed
    assert summary.config_changed
    assert summary.backup_dir is None
    assert config_path.read_text(encoding="utf-8") == before
    assert any("dry-run" in c for c in summary.changes)


def test_update_replaces_generic_identity_assets_for_fleet(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "The Commander",
                    "default": True,
                    "model": "openai/gpt-5.2",
                    "workspace": str(workspace),
                }
            ]
        },
        "channels": {"telegram": _default_telegram()},
        "bindings": _default_bindings(),
    }
    _write_json(openclaw_dir / "openclaw.json", config)

    workspace.mkdir(parents=True, exist_ok=True)
    for filename in ("SOUL.md", "IDENTITY.md", "USER.md"):
        (workspace / filename).write_text((template_dir / filename).read_text(encoding="utf-8"), encoding="utf-8")

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert summary.workspace_changed
    assert "Updated generic SOUL.md for Commander role" in summary.changes
    assert "Updated generic IDENTITY.md for Commander role" in summary.changes
    assert "Updated generic USER.md for Commander role" in summary.changes
    assert "The Commander" in (workspace / "SOUL.md").read_text(encoding="utf-8")
    assert "company-level Maestro orchestrator" in (workspace / "IDENTITY.md").read_text(encoding="utf-8")
    assert "Company Leadership" in (workspace / "USER.md").read_text(encoding="utf-8")


def test_update_replaces_stale_commander_agents_and_tools(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "The Commander",
                    "default": True,
                    "model": "openai/gpt-5.2",
                    "workspace": str(workspace),
                }
            ]
        },
        "channels": {"telegram": _default_telegram()},
        "bindings": _default_bindings(),
    }
    _write_json(openclaw_dir / "openclaw.json", config)

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "AGENTS.md").write_text(
        "# AGENTS.md\n- For license lifecycle, use local expiring keys and track annual renewal.\n",
        encoding="utf-8",
    )
    (workspace / "TOOLS.md").write_text(
        "# TOOLS.md\n- Handle license lifecycle and annual key refresh planning\n"
        "- `maestro-fleet license generate --project-name \"...\"` — issue local expiring project key\n",
        encoding="utf-8",
    )

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert summary.workspace_changed
    assert "Updated stale AGENTS.md for Commander role" in summary.changes
    assert "Updated stale TOOLS.md for Commander role" in summary.changes
    assert "license lifecycle" not in (workspace / "AGENTS.md").read_text(encoding="utf-8").lower()
    assert "maestro-fleet license generate" not in (workspace / "TOOLS.md").read_text(encoding="utf-8").lower()


def test_update_replaces_stale_commander_soul(tmp_path: Path):
    home = tmp_path / "home"
    openclaw_dir = home / ".openclaw"
    workspace = openclaw_dir / "workspace-maestro"
    template_dir = _make_template_dir(tmp_path)

    config = {
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "The Commander",
                    "default": True,
                    "model": "openai/gpt-5.2",
                    "workspace": str(workspace),
                }
            ]
        },
        "channels": {"telegram": _default_telegram()},
        "bindings": _default_bindings(),
    }
    _write_json(openclaw_dir / "openclaw.json", config)

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "SOUL.md").write_text(
        "# SOUL.md\n- Protect system boundaries, license boundaries, and cross-project isolation\n"
        "- Do not bypass license policy, routing policy, or project isolation policy\n",
        encoding="utf-8",
    )

    summary, code = perform_update(
        restart_gateway=False,
        home_dir=home,
        template_dir=template_dir,
        command_runner=lambda cmd: (False, ""),
    )

    assert code == 0
    assert summary.workspace_changed
    assert "Updated stale SOUL.md for Commander role" in summary.changes
    soul = (workspace / "SOUL.md").read_text(encoding="utf-8").lower()
    assert "license boundaries" not in soul
    assert "do not bypass license policy" not in soul


def test_ensure_frontend_artifacts_dry_run(monkeypatch):
    monkeypatch.setattr("maestro.update._frontend_dist_available", lambda *_args, **_kwargs: False)
    changes, warnings = _ensure_frontend_artifacts("solo", dry_run=True)
    assert "Would build missing Workspace frontend dist" in changes[0]
    assert warnings == []


def test_ensure_frontend_artifacts_fleet_build_failure(monkeypatch):
    monkeypatch.setattr("maestro.update._frontend_dist_available", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "maestro.update._build_frontend_dist",
        lambda *_args, **_kwargs: (False, "build failed"),
    )
    changes, warnings = _ensure_frontend_artifacts(PROFILE_FLEET, dry_run=False)
    assert changes == []
    assert len(warnings) == 2
    assert all("Could not build" in warning for warning in warnings)
