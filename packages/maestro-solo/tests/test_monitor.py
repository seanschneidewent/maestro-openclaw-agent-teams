from __future__ import annotations

from pathlib import Path

from maestro_solo import monitor


def test_render_tokens_shows_connected_workspace():
    state = monitor.MonitorState(
        store_path=Path("/tmp/store"),
        web_port=3000,
        primary_url="http://localhost:3000/workspace",
        local_url="http://localhost:3000/workspace",
        tailnet_url="http://100.100.100.100:3000/workspace",
        agent_id="maestro-solo-personal",
        workspace_path="/Users/test/.openclaw/workspace-maestro-solo",
    )

    panel = monitor._render_tokens(state)
    body = str(panel.renderable)
    assert "Connected Workspace" in body
    assert "Access URL" in body
    assert "http://100.100.100.100:3000/workspace" in body
    assert "Command Center" not in body
