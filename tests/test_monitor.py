"""Tests for Solo/Fleet monitor rendering and agent resolution."""

from __future__ import annotations

import json
from pathlib import Path

from maestro import monitor
from maestro.profile import PROFILE_FLEET, PROFILE_SOLO


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_resolve_primary_agent_prefers_solo_personal_agent(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "default": True,
                        "workspace": "/tmp/company",
                    },
                    {
                        "id": "maestro-personal",
                        "default": False,
                        "workspace": "/tmp/personal",
                    },
                ]
            }
        },
    )

    agent_id, workspace = monitor._resolve_primary_agent(PROFILE_SOLO)
    assert agent_id == "maestro-personal"
    assert workspace == "/tmp/personal"


def test_render_tokens_solo_shows_connected_workspace():
    state = monitor.MonitorState(
        store_path=Path("/tmp/store"),
        web_port=3000,
        profile=PROFILE_SOLO,
        primary_url="http://localhost:3000/workspace",
        local_url="http://localhost:3000/workspace",
        tailnet_url="http://100.100.100.100:3000/workspace",
        agent_id="maestro-personal",
        workspace_path="/Users/test/.openclaw/workspace-maestro",
    )

    panel = monitor._render_tokens(state)
    body = str(panel.renderable)
    assert "Connected Workspace" in body
    assert "Access URL" in body
    assert "http://100.100.100.100:3000/workspace" in body
    assert "Local Fallback" in body
    assert "Command Center" not in body


def test_render_tokens_fleet_shows_command_center():
    state = monitor.MonitorState(
        store_path=Path("/tmp/store"),
        web_port=3000,
        profile=PROFILE_FLEET,
        primary_url="http://localhost:3000/command-center",
        local_url="http://localhost:3000/command-center",
        tailnet_url=None,
        agent_id="maestro-company",
        workspace_path="",
    )

    panel = monitor._render_tokens(state)
    body = str(panel.renderable)
    assert "Command Center" in body
    assert "Connected Workspace" not in body
