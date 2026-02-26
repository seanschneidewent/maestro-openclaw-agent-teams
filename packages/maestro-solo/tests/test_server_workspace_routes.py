from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

import maestro_solo.server as server


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_single_project_store(root: Path, name: str = "Solo Project"):
    _write_json(root / "project.json", {"name": name})


def _enable_pro_workspace(monkeypatch):
    monkeypatch.setenv("MAESTRO_TIER", "pro")
    monkeypatch.delenv("MAESTRO_ALLOW_CORE_WORKSPACE", raising=False)


@contextmanager
def _with_store(path: Path):
    previous_store = server.store_path
    previous_projects = dict(server.projects)
    previous_ws_clients = dict(server.ws_clients)
    previous_project_dir_index = dict(server.project_dir_slug_index)
    try:
        server.store_path = path
        server.load_all_projects()
        yield
    finally:
        server.store_path = previous_store
        server.projects = previous_projects
        server.ws_clients = previous_ws_clients
        server.project_dir_slug_index = previous_project_dir_index


def test_workspace_api_project_route_uses_active_project(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(home / ".maestro-solo"))
    _enable_pro_workspace(monkeypatch)

    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        response = client.get("/workspace/api/project")
        assert response.status_code == 200
        payload = response.json()
        assert payload["name"] == "Solo Project"
        assert "slug" in payload


def test_command_center_not_served_in_solo(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(home / ".maestro-solo"))
    _enable_pro_workspace(monkeypatch)

    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        response = client.get("/command-center")
        assert response.status_code == 404


def test_root_redirects_to_workspace(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(home / ".maestro-solo"))
    _enable_pro_workspace(monkeypatch)

    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/workspace"


def test_workspace_project_notes_route_returns_notes(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(home / ".maestro-solo"))
    _enable_pro_workspace(monkeypatch)

    _make_single_project_store(tmp_path, name="Solo Project")
    _write_json(
        tmp_path / "notes" / "project_notes.json",
        {
            "version": 1,
            "updated_at": "2026-02-25T05:36:28.291Z",
            "categories": [{"id": "general", "name": "General", "color": "slate", "order": 0}],
            "notes": [
                {
                    "id": "inspection-note",
                    "text": "Spoke with Andy — planning a two-stage pour.",
                    "category_id": "general",
                    "source_pages": [{"page_name": "VC_05_Header_and_Venting_Pipe_Cross_Section_p001"}],
                    "status": "open",
                    "pinned": False,
                }
            ],
        },
    )

    with _with_store(tmp_path):
        client = TestClient(server.app)
        workspace_response = client.get("/workspace/api/project-notes")
        assert workspace_response.status_code == 200
        workspace_payload = workspace_response.json()
        assert workspace_payload["ok"] is True
        assert workspace_payload["note_count"] == 1
        assert workspace_payload["category_count"] >= 1
        assert workspace_payload["notes"][0]["text"] == "Spoke with Andy — planning a two-stage pour."

        project_payload = client.get("/workspace/api/project").json()
        project_slug = project_payload["slug"]
        slug_response = client.get(f"/{project_slug}/api/project-notes")
        assert slug_response.status_code == 200
        assert slug_response.json()["note_count"] == 1


def test_core_mode_blocks_workspace_routes(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(home / ".maestro-solo"))
    monkeypatch.setenv("MAESTRO_TIER", "core")
    monkeypatch.delenv("MAESTRO_ALLOW_CORE_WORKSPACE", raising=False)

    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        workspace_response = client.get("/workspace")
        assert workspace_response.status_code == 403
        assert workspace_response.json()["error"] == "Workspace UI is available on Maestro Pro only."

        api_response = client.get("/workspace/api/project")
        assert api_response.status_code == 403
        assert api_response.json()["next_step"].startswith("Run maestro-solo purchase")


def test_core_mode_root_returns_text_only_status(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(home / ".maestro-solo"))
    monkeypatch.setenv("MAESTRO_TIER", "core")
    monkeypatch.delenv("MAESTRO_ALLOW_CORE_WORKSPACE", raising=False)

    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        response = client.get("/")
        assert response.status_code == 200
        payload = response.json()
        assert payload["product"] == "maestro-solo-core"
        assert payload["mode"] == "text_only"
        assert any("maestro-solo purchase" in step for step in payload.get("next_steps", []))
