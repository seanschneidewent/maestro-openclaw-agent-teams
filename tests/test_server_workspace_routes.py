"""Server route tests for Solo canonical workspace paths."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

import maestro.server as server


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_single_project_store(root: Path, name: str = "Solo Project"):
    _write_json(root / "project.json", {"name": name})


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


def test_workspace_api_project_route_uses_active_project(tmp_path: Path):
    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        response = client.get("/workspace/api/project")
        assert response.status_code == 200
        payload = response.json()
        assert payload["name"] == "Solo Project"
        assert "slug" in payload


def test_workspace_websocket_initializes(tmp_path: Path):
    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        with client.websocket_connect("/workspace/ws") as websocket:
            event = websocket.receive_json()
            assert event["type"] == "init"
            assert "page_count" in event


def test_workspace_project_notes_route_returns_empty_payload(tmp_path: Path):
    _make_single_project_store(tmp_path, name="Solo Project")
    with _with_store(tmp_path):
        client = TestClient(server.app)
        response = client.get("/workspace/api/project-notes")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["project_slug"]
        assert payload["categories"]
        assert payload["note_count"] == 0


def test_command_center_disabled_in_solo_returns_actionable_404(monkeypatch):
    monkeypatch.setattr(server, "profile_fleet_enabled", lambda: False)
    client = TestClient(server.app)
    response = client.get("/command-center")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"] == "Fleet mode not enabled"
    assert payload["next_step"] == "Run maestro fleet enable"


def test_root_redirects_to_workspace_in_solo(monkeypatch):
    monkeypatch.setattr(server, "profile_fleet_enabled", lambda: False)
    client = TestClient(server.app)
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/workspace"
