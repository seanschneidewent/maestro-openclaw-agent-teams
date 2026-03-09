from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import maestro.server as legacy_server
from maestro_fleet.actions import install_fleet_action_runner
from maestro_fleet.command_center import build_derived_registry, install_fleet_command_center_backend


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_project_store(project_dir: Path, *, name: str = "Alpha Project") -> None:
    _write_json(
        project_dir / "project.json",
        {
            "name": name,
            "total_pages": 5,
            "index_summary": {"pointer_count": 12},
            "ingested_at": "2026-03-07T00:00:00Z",
        },
    )
    _write_json(project_dir / "index.json", {"summary": {"page_count": 5, "pointer_count": 12}})


def _write_workspace_env(workspace: Path, *, store: Path, role: str, project_slug: str | None = None) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    lines = [
        f"MAESTRO_STORE={store}",
        f"MAESTRO_AGENT_ROLE={role}",
    ]
    if project_slug:
        lines.append(f"MAESTRO_PROJECT_SLUG={project_slug}")
    (workspace / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_openclaw_config(home: Path, *, store_root: Path, project_store: Path) -> None:
    state_root = home / ".openclaw-maestro-fleet"
    company_workspace = state_root / "workspace-maestro"
    project_workspace = company_workspace / "projects" / "alpha-project"

    _write_workspace_env(company_workspace, store=store_root, role="company")
    _write_workspace_env(project_workspace, store=project_store, role="project", project_slug="alpha-project")

    _write_json(
        state_root / "openclaw.json",
        {
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "The Commander",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(company_workspace),
                    },
                    {
                        "id": "maestro-project-alpha-project",
                        "name": "Alpha Project",
                        "model": "openai/gpt-5.2",
                        "workspace": str(project_workspace),
                    },
                ]
            }
        },
    )


@pytest.fixture
def isolated_legacy_server_state() -> None:
    original_backend = legacy_server.command_center_state_backend
    original_action_runner = legacy_server.command_center_action_runner
    original_fleet_runtime_hooks_installed = legacy_server.fleet_runtime_hooks_installed
    original_store_path = legacy_server.store_path
    original_server_port = legacy_server.server_port
    try:
        legacy_server.projects = {}
        legacy_server.project_dir_slug_index = {}
        legacy_server.command_center_state = {}
        legacy_server.command_center_ws_clients = set()
        legacy_server.fleet_registry = {}
        legacy_server.awareness_state = {}
        legacy_server.agent_project_slug_index = {}
        legacy_server.command_center_node_index = {}
        legacy_server.fleet_runtime_hooks_installed = False
        yield
    finally:
        legacy_server.set_command_center_state_backend(original_backend)
        legacy_server.set_command_center_action_runner(original_action_runner)
        legacy_server.fleet_runtime_hooks_installed = original_fleet_runtime_hooks_installed
        legacy_server.store_path = original_store_path
        legacy_server.server_port = original_server_port
        legacy_server.projects = {}
        legacy_server.project_dir_slug_index = {}
        legacy_server.command_center_state = {}
        legacy_server.command_center_ws_clients = set()
        legacy_server.fleet_registry = {}
        legacy_server.awareness_state = {}
        legacy_server.agent_project_slug_index = {}
        legacy_server.command_center_node_index = {}


def _disable_external_runtime_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("maestro_fleet.command_center.shutil.which", lambda name: None)
    monkeypatch.setattr("maestro_fleet.runtime.shutil.which", lambda name: None)


def test_build_derived_registry_ignores_stale_registry_file(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    store_root = tmp_path / "store"
    project_store = store_root / "alpha-project"
    _make_project_store(project_store)
    _write_openclaw_config(home, store_root=store_root, project_store=project_store)
    _write_json(
        store_root / ".command_center" / "fleet_registry.json",
        {
            "version": 1,
            "updated_at": "2026-03-08T00:00:00Z",
            "store_root": str(store_root),
            "projects": [
                {
                    "project_slug": "ghost-project",
                    "project_name": "Ghost Project",
                    "project_dir_name": "ghost-project",
                    "project_store_path": str(store_root / "ghost-project"),
                    "maestro_agent_id": "maestro-project-ghost-project",
                    "status": "archived",
                }
            ],
        },
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    _disable_external_runtime_checks(monkeypatch)

    registry = build_derived_registry(store_root)

    assert [item["project_slug"] for item in registry["projects"]] == ["alpha-project"]
    assert registry["projects"][0]["maestro_agent_id"] == "maestro-project-alpha-project"
    assert registry["projects"][0]["project_store_path"] == str(project_store.resolve())


def test_fleet_server_backend_uses_openclaw_bindings_for_command_center(monkeypatch, tmp_path: Path, isolated_legacy_server_state: None) -> None:
    home = tmp_path / "home"
    store_root = tmp_path / "store"
    project_store = store_root / "alpha-project"
    _make_project_store(project_store)
    _write_openclaw_config(home, store_root=store_root, project_store=project_store)
    _write_json(
        store_root / ".command_center" / "fleet_registry.json",
        {
            "version": 1,
            "updated_at": "2026-03-08T00:00:00Z",
            "store_root": str(store_root),
            "projects": [
                {
                    "project_slug": "ghost-project",
                    "project_name": "Ghost Project",
                    "project_dir_name": "ghost-project",
                    "project_store_path": str(store_root / "ghost-project"),
                    "maestro_agent_id": "maestro-project-ghost-project",
                    "status": "archived",
                }
            ],
        },
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    _disable_external_runtime_checks(monkeypatch)

    install_fleet_command_center_backend(legacy_server)
    legacy_server.store_path = store_root
    legacy_server.server_port = 3300

    legacy_server.load_all_projects()
    legacy_server._refresh_command_center_state()
    legacy_server._refresh_control_plane_state()

    state_payload = asyncio.run(legacy_server.api_command_center_state())
    assert [item["slug"] for item in state_payload["projects"]] == ["alpha-project"]
    assert state_payload["projects"][0]["agent_id"] == "maestro-project-alpha-project"
    assert state_payload["projects"][0]["agent_workspace_url"].endswith("/agents/maestro-project-alpha-project/workspace/")

    awareness = asyncio.run(legacy_server.api_system_awareness())
    assert awareness["fleet"]["project_count"] == 1
    assert [item["project_slug"] for item in awareness["fleet"]["registry"]["projects"]] == ["alpha-project"]

    workspace_index = asyncio.run(legacy_server.api_agent_workspace_index())
    assert workspace_index["agents"][0]["agent_id"] == "maestro-project-alpha-project"

    project_payload = asyncio.run(legacy_server.api_agent_project("maestro-project-alpha-project"))
    assert project_payload["slug"] == "alpha-project"


def test_root_server_auto_installs_package_fleet_hooks(monkeypatch, tmp_path: Path, isolated_legacy_server_state: None) -> None:
    home = tmp_path / "home"
    store_root = tmp_path / "store"
    project_store = store_root / "alpha-project"
    _make_project_store(project_store)
    _write_openclaw_config(home, store_root=store_root, project_store=project_store)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    monkeypatch.setattr(legacy_server, "profile_fleet_enabled", lambda: True)
    _disable_external_runtime_checks(monkeypatch)

    legacy_server.set_command_center_state_backend(None)
    legacy_server.set_command_center_action_runner(None)
    legacy_server.store_path = store_root
    legacy_server.server_port = 3300

    legacy_server._refresh_all_state()

    assert legacy_server.command_center_state_backend is not None
    assert legacy_server.command_center_action_runner is not None
    assert legacy_server.fleet_runtime_hooks_installed is True

    state_payload = asyncio.run(legacy_server.api_command_center_state())
    assert [item["slug"] for item in state_payload["projects"]] == ["alpha-project"]
    assert state_payload["projects"][0]["agent_id"] == "maestro-project-alpha-project"


def test_fleet_server_actions_create_project_without_registry_write(monkeypatch, tmp_path: Path, isolated_legacy_server_state: None) -> None:
    home = tmp_path / "home"
    store_root = tmp_path / "store"
    state_root = home / ".openclaw-maestro-fleet"
    company_workspace = state_root / "workspace-maestro"
    _write_workspace_env(company_workspace, store=store_root, role="company")
    _write_json(
        state_root / "openclaw.json",
        {
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "The Commander",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(company_workspace),
                    }
                ]
            }
        },
    )
    incoming = tmp_path / "incoming-pdfs"
    incoming.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    _disable_external_runtime_checks(monkeypatch)

    install_fleet_command_center_backend(legacy_server)
    install_fleet_action_runner(legacy_server)
    legacy_server.store_path = store_root
    legacy_server.server_port = 3300
    store_root.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(legacy_server.api_command_center_actions({
        "action": "create_project_node",
        "project_name": "Alpha Project",
        "assignee": "andy",
        "superintendent": "sam",
        "ingest_input_root": str(incoming),
        "register_agent": True,
    }))

    assert result["ok"] is True
    project_dir = store_root / "alpha-project"
    project_json = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    assert project_json["maestro"]["assignee"] == "andy"
    assert project_json["maestro"]["superintendent"] == "sam"
    assert project_json["maestro"]["ingest_input_root"] == str(incoming.resolve())
    assert not (store_root / ".command_center" / "fleet_registry.json").exists()

    project_workspace = state_root / "workspace-maestro" / "projects" / "alpha-project"
    env_text = (project_workspace / ".env").read_text(encoding="utf-8")
    assert f"MAESTRO_STORE={project_dir.resolve()}" in env_text
    assert "MAESTRO_PROJECT_SLUG=alpha-project" in env_text

    state_payload = asyncio.run(legacy_server.api_command_center_state())
    assert [item["slug"] for item in state_payload["projects"]] == ["alpha-project"]
    assert state_payload["projects"][0]["assignee"] == "andy"
    assert state_payload["projects"][0]["superintendent"] == "sam"
    assert state_payload["projects"][0]["agent_id"] == "maestro-project-alpha-project"

    control = asyncio.run(legacy_server.api_command_center_actions({
        "action": "ingest_command",
        "project_slug": "alpha-project",
    }))
    assert control["ok"] is True
    assert control["project"]["ingest_input_root"] == str(incoming.resolve())
