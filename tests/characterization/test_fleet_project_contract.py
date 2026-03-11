from __future__ import annotations

import json
from pathlib import Path

from maestro.command_center import build_project_snapshot, discover_project_dirs
from maestro import control_plane_core
from maestro.workspace_templates import render_workspace_env
from maestro_engine.server_project_store import load_all_projects
from maestro_engine.server_workspace_data import load_all_workspaces, load_project_notes
from maestro_fleet.command_center import build_derived_registry


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def test_project_workspace_and_store_contract(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    state_root = home / ".openclaw-maestro-fleet"
    workspace = state_root / "workspace-maestro"
    store_root = workspace / "knowledge_store"
    config_path = state_root / "openclaw.json"
    workspace.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    (workspace / ".env").write_text(
        render_workspace_env(store_path=str(store_root), agent_role="company"),
        encoding="utf-8",
    )
    _write_json(
        config_path,
        {
            "env": {},
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
            "channels": {"telegram": {"enabled": True, "accounts": {}}},
        },
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    monkeypatch.setattr(control_plane_core, "_now_iso", lambda: "2026-03-09T00:00:00Z")
    monkeypatch.setattr(
        control_plane_core,
        "resolve_network_urls",
        lambda **kwargs: {
            "recommended_url": f"http://localhost:3000{kwargs.get('route_path', '/command-center')}",
            "localhost_url": f"http://localhost:3000{kwargs.get('route_path', '/command-center')}",
            "tailnet_url": "",
        },
    )

    result = control_plane_core.create_project_node(
        store_root,
        "Alpha Build",
        assignee="Andy",
        superintendent="Sean",
        register_agent=True,
        home_dir=home,
        dry_run=False,
    )

    assert result["ok"] is True
    assert result["project_slug"] == "alpha-build"

    project_dir = store_root / "alpha-build"
    project_workspace = workspace / "projects" / "alpha-build"
    project_json = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    assert project_json["name"] == "Alpha Build"
    assert project_json["slug"] == "alpha-build"
    assert project_json["maestro"] == {
        "status": "setup",
        "superintendent": "Sean",
        "assignee": "Andy",
    }

    env = _read_env(project_workspace / ".env")
    assert env["MAESTRO_STORE"] == str(project_dir)
    assert env["MAESTRO_AGENT_ROLE"] == "project"
    assert env["MAESTRO_PROJECT_SLUG"] == "alpha-build"

    files = sorted(path.relative_to(project_workspace).as_posix() for path in project_workspace.rglob("*") if path.is_file())
    assert "AGENTS.md" in files
    assert "TOOLS.md" in files
    assert "AWARENESS.md" in files
    assert "skills/maestro/SKILL.md" in files
    assert ".openclaw/extensions/maestro-native-tools/openclaw.plugin.json" in files
    assert not any(path.startswith("skills/commander/") for path in files)

    registry = build_derived_registry(store_root, home_dir=home)
    assert [item["project_slug"] for item in registry["projects"]] == ["alpha-build"]
    assert registry["projects"][0]["maestro_agent_id"] == "maestro-project-alpha-build"
    assert registry["projects"][0]["project_store_path"] == str(project_dir.resolve())

    projects, slug_index = load_all_projects(
        store_root,
        discover_project_dirs_fn=discover_project_dirs,
        build_project_snapshot_fn=build_project_snapshot,
    )
    assert slug_index == {"alpha-build": "alpha-build"}
    proj = projects["alpha-build"]
    assert load_all_workspaces(proj) == []
    assert load_project_notes(proj)["notes"] == []


def test_native_tools_project_resolution_contract() -> None:
    source = Path("agent/extensions/maestro-native-tools/index.ts").read_text(encoding="utf-8")

    assert 'const workspaceEnvStore = readWorkspaceEnv(workspaceDir, "MAESTRO_STORE");' in source
    assert 'const processEnvStore = asString(process.env.MAESTRO_STORE);' in source
    assert 'const raw = workspaceEnvStore || configStore || processEnvStore || "knowledge_store";' in source
    assert '|| resolveWorkspaceProjectSlug(workspaceDir)' in source
    assert 'if (projects.length === 1) {' in source
    assert 'return projects[0];' in source
    assert 'Multiple ingested projects found under ${storeRoot}.' in source
