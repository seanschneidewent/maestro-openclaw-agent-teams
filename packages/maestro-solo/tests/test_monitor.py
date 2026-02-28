from __future__ import annotations

import json
import plistlib
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from maestro_solo import monitor


def test_render_tokens_shows_connected_workspace():
    state = monitor.MonitorState(
        store_path=Path("/tmp/store"),
        web_port=3000,
        primary_url="http://localhost:3000/workspace",
        local_url="http://localhost:3000/workspace",
        tailnet_url="http://100.100.100.100:3000/workspace",
        gateway_port=18789,
        agent_id="maestro-solo-personal",
        workspace_path="/Users/test/.openclaw/workspace-maestro-solo",
    )

    panel = monitor._render_tokens(state)
    body = str(panel.renderable)
    assert "Connected Workspace" in body
    assert "Access URL" in body
    assert "http://100.100.100.100:3000/workspace" in body
    assert "Command Center" not in body


def test_gateway_event_filtering_prefers_runtime_signals():
    assert monitor._is_relevant_gateway_event("", "OpenClaw gateway started and running")
    assert monitor._is_relevant_gateway_event("warn", "connection retry in progress")
    assert monitor._is_relevant_gateway_event("", "Traceback: gateway exception detected")
    assert not monitor._is_relevant_gateway_event("", "debug periodic metrics sample")


def test_format_gateway_event_highlights_severity_and_redacts_token():
    formatted = monitor._format_gateway_event(
        'Gateway auth token="abc123" expired',
        level_hint="warning",
    )
    assert "WARN" in formatted
    assert "[redacted]" in formatted
    assert "abc123" not in formatted


def test_update_metrics_uses_gateway_port_probe_for_running_state():
    state = monitor.MonitorState(
        store_path=Path("/tmp/store"),
        web_port=3000,
        primary_url="http://localhost:3000/workspace",
        local_url="http://localhost:3000/workspace",
        tailnet_url=None,
        gateway_port=18789,
        agent_id="maestro-solo-personal",
        workspace_path="/Users/test/.openclaw/workspace-maestro-solo",
    )
    process = Mock()
    process.poll.return_value = None

    with (
        patch("maestro_solo.monitor._probe_gateway_port", return_value=True),
        patch("maestro_solo.monitor.resolve_network_urls", return_value={
            "recommended_url": "http://localhost:3000/workspace",
            "localhost_url": "http://localhost:3000/workspace",
            "tailnet_url": None,
        }),
        patch("maestro_solo.monitor.time.time", return_value=1000.0),
    ):
        monitor._update_metrics(state, process)

    assert state.gateway_running is True


def test_activity_events_parse_tool_calls_and_response():
    known: dict[str, str] = {}
    line = (
        '{"type":"message","timestamp":"2026-02-25T05:00:00Z","message":{"role":"assistant","content":['
        '{"type":"thinking","thinking":""},'
        '{"type":"toolCall","id":"call_123","name":"maestro_search","arguments":{"query":"door schedule"}},'
        '{"type":"text","text":"Done."}'
        ']}}'
    )
    events = monitor._activity_events_from_session_line(line, known_tool_calls=known)
    labels = [item.get("label") for item in events]
    messages = [item.get("message", "") for item in events]

    assert "THINK" in labels
    assert "TOOL" in labels
    assert "RESP" in labels
    assert any("Tool call: maestro_search" in message for message in messages)
    assert known.get("call_123") == "maestro_search"


def test_activity_events_parse_tool_result_error():
    known = {"call_abc": "maestro_get_workspace"}
    line = (
        '{"type":"message","timestamp":"2026-02-25T05:00:01Z","message":{"role":"toolResult",'
        '"toolCallId":"call_abc","toolName":"maestro_get_workspace","isError":true,'
        '"content":[{"type":"text","text":"failed"}]}}'
    )
    events = monitor._activity_events_from_session_line(line, known_tool_calls=known)
    assert len(events) == 1
    assert events[0]["label"] == "ERROR"
    assert "Tool failed: maestro_get_workspace" in events[0]["message"]


def test_update_runtime_state_logs_gateway_and_tailnet_transitions():
    state = monitor.MonitorState(
        store_path=Path("/tmp/store"),
        web_port=3000,
        primary_url="http://localhost:3000/workspace",
        local_url="http://localhost:3000/workspace",
        tailnet_url=None,
        gateway_port=18789,
        agent_id="maestro-solo-personal",
        workspace_path="/Users/test/.openclaw/workspace-maestro-solo",
    )
    process = Mock()
    logs = monitor.LogBuffer()

    def _fake_update_metrics(_state, _process):
        _state.gateway_running = True
        _state.tailnet_url = "http://100.100.100.100:3000/workspace"

    with patch("maestro_solo.monitor._update_metrics", side_effect=_fake_update_metrics):
        monitor._update_runtime_state(state, process, logs)

    lines = logs.recent(8)
    assert any("Gateway service is running." in line for line in lines)
    assert any("Tailnet workspace reachable at http://100.100.100.100:3000/workspace" in line for line in lines)


def test_start_gateway_log_stream_handles_missing_openclaw():
    logs = monitor.LogBuffer()
    stop_event = threading.Event()

    with patch("maestro_solo.monitor._start_text_process", side_effect=FileNotFoundError("openclaw not found")):
        process = monitor._start_gateway_log_stream(stop_event, logs)

    assert process is None
    assert any("OpenClaw event stream unavailable" in line for line in logs.recent(4))


def test_resolve_gateway_port_prefers_profile_config(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("OPENCLAW_GATEWAY_PORT", raising=False)
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)

    config_path = home / ".openclaw-maestro-solo" / "openclaw.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"gateway": {"port": 19124}}), encoding="utf-8")

    plist_path = home / "Library" / "LaunchAgents" / "ai.openclaw.gateway.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plistlib.dumps({
        "ProgramArguments": ["openclaw", "gateway", "--port", "18789"],
        "EnvironmentVariables": {"OPENCLAW_GATEWAY_PORT": "18789"},
    }))

    assert monitor._resolve_gateway_port() == 19124


def test_resolve_gateway_port_uses_profile_specific_launchagent(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("OPENCLAW_GATEWAY_PORT", raising=False)
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)

    profile_plist = home / "Library" / "LaunchAgents" / "ai.openclaw.maestro-solo.plist"
    profile_plist.parent.mkdir(parents=True, exist_ok=True)
    profile_plist.write_bytes(plistlib.dumps({
        "ProgramArguments": ["openclaw", "gateway", "--port", "19125"],
    }))

    generic_plist = home / "Library" / "LaunchAgents" / "ai.openclaw.gateway.plist"
    generic_plist.write_bytes(plistlib.dumps({
        "ProgramArguments": ["openclaw", "gateway", "--port", "18789"],
    }))

    assert monitor._resolve_gateway_port() == 19125
