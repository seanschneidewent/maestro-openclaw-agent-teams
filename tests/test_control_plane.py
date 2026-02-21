"""Tests for command-center control plane awareness and action contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.responses import JSONResponse

import maestro.server as server
from maestro.control_plane import (
    build_awareness_state,
    create_project_node,
    move_project_store,
    onboard_project_store,
    project_control_payload,
    sync_fleet_registry,
)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_project(project_dir: Path, name: str = "Alpha Project", slug: str = "alpha-project"):
    _write_json(
        project_dir / "project.json",
        {
            "name": name,
            "slug": slug,
            "total_pages": 5,
            "index_summary": {"pointer_count": 10},
            "ingested_at": "2026-02-20T00:00:00",
        },
    )
    _write_json(
        project_dir / "index.json",
        {
            "summary": {"page_count": 5, "pointer_count": 10},
            "generated": "2026-02-20T00:05:00",
        },
    )


def test_registry_sync_discovers_projects(tmp_path: Path):
    project_dir = tmp_path / "alpha"
    _make_project(project_dir)

    registry = sync_fleet_registry(tmp_path)
    assert len(registry["projects"]) == 1
    project = registry["projects"][0]
    assert project["project_slug"] == "alpha-project"
    assert project["project_name"] == "Alpha Project"
    assert project["project_store_path"] == str(project_dir.resolve())


def test_project_control_payload_needs_input_path(tmp_path: Path):
    project_dir = tmp_path / "alpha"
    _make_project(project_dir)

    payload = project_control_payload(tmp_path, "alpha-project")
    assert payload["ok"] is True
    assert payload["ingest"]["needs_input_path"] is True
    assert payload["preflight"]["ready"] is False


def test_create_project_node_and_move(tmp_path: Path):
    input_dir = tmp_path / "incoming" / "alpha"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "A101.pdf").write_bytes(b"%PDF-1.7 fake")

    created = create_project_node(
        store_root=tmp_path,
        project_name="Beta Build",
        ingest_input_root=str(input_dir),
        superintendent="Mike",
        dry_run=False,
    )
    assert created["ok"] is True
    assert created["project_slug"] == "beta-build"
    assert (tmp_path / "beta-build").exists()

    moved = move_project_store(
        store_root=tmp_path,
        project_slug="beta-build",
        new_dir_name="beta-build-renamed",
        dry_run=False,
    )
    assert moved["ok"] is True
    assert not (tmp_path / "beta-build").exists()
    assert (tmp_path / "beta-build-renamed").exists()


def test_onboard_project_store_moves_preingested_data(tmp_path: Path):
    store_root = tmp_path / "store"
    store_root.mkdir(parents=True, exist_ok=True)

    incoming = tmp_path / "incoming" / "alpha-store"
    _make_project(incoming, name="Alpha Project", slug="alpha-project")

    result = onboard_project_store(
        store_root=store_root,
        source_path=str(incoming),
        register_agent=False,
        dry_run=False,
    )

    assert result["ok"] is True
    assert result["final_registry_entry"]["project_slug"] == "alpha-project"
    assert (store_root / "alpha-project" / "project.json").exists()
    assert not incoming.exists()


def test_awareness_state_contract(tmp_path: Path):
    project_dir = tmp_path / "alpha"
    _make_project(project_dir)

    home = tmp_path / "home"
    awareness = build_awareness_state(
        store_root=tmp_path,
        web_port=3333,
        command_runner=lambda args, timeout=6: (False, ""),
        home_dir=home,
    )

    assert awareness["network"]["recommended_url"] == "http://localhost:3333/command-center"
    assert awareness["paths"]["store_root"] == str(tmp_path.resolve())
    assert "ingest_command" in awareness["available_actions"]
    assert "doctor_fix" in awareness["available_actions"]
    assert awareness["purchase"]["purchase_command"] == "maestro-purchase"
    assert "gateway_auth" in awareness["services"]["openclaw"]
    assert "device_pairing" in awareness["services"]["openclaw"]


def test_server_control_plane_endpoints(tmp_path: Path, monkeypatch):
    project_dir = tmp_path / "alpha"
    _make_project(project_dir)

    server.store_path = tmp_path
    server.server_port = 3000
    server.load_all_projects()
    server._refresh_command_center_state()
    server._refresh_control_plane_state()

    awareness = asyncio.run(server.api_system_awareness())
    assert "network" in awareness
    assert "fleet" in awareness

    control = asyncio.run(server.api_command_center_actions({
        "action": "ingest_command",
        "project_slug": "alpha-project",
    }))
    assert control["ok"] is True
    assert "command" in control["ingest"]

    beta_src = tmp_path / "incoming" / "beta-store"
    _make_project(beta_src, name="Beta Project", slug="beta-project")
    onboard = asyncio.run(server.api_command_center_actions({
        "action": "onboard_project_store",
        "source_path": str(beta_src),
        "register_agent": False,
    }))
    assert onboard["ok"] is True
    assert onboard["final_registry_entry"]["project_slug"] == "beta-project"

    monkeypatch.setattr(
        server,
        "build_doctor_report",
        lambda **kwargs: {
            "ok": True,
            "fix_mode": bool(kwargs.get("fix")),
            "store_root": str(server.store_path.resolve()),
            "recommended_url": "http://localhost:3000/command-center",
            "checks": [{"name": "gateway_auth_tokens", "ok": True, "detail": "aligned", "fixed": False, "warning": False}],
        },
    )
    doctor = asyncio.run(server.api_command_center_actions({
        "action": "doctor_fix",
        "fix": True,
        "restart_gateway": False,
    }))
    assert doctor["ok"] is True
    assert doctor["doctor"]["ok"] is True
    assert "awareness" in doctor

    missing = asyncio.run(server.api_command_center_actions({"action": "preflight_ingest"}))
    assert isinstance(missing, JSONResponse)
    assert missing.status_code == 400
