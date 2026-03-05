"""Tests for commander chat session parsing and send helpers."""

from __future__ import annotations

import json
from pathlib import Path

import maestro.commander_chat as chat


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row) for row in rows) + "\n"
    path.write_text(payload, encoding="utf-8")


def _seed_session(home: Path, agent_id: str = "maestro-project-alpha") -> tuple[str, Path]:
    sessions_dir = home / ".openclaw" / "agents" / agent_id / "sessions"
    session_id = "00000000-0000-4000-8000-000000000001"
    _write_json(
        sessions_dir / "sessions.json",
        {
            f"agent:{agent_id}:main": {
                "sessionId": session_id,
                "updatedAt": 123,
            }
        },
    )
    return session_id, sessions_dir / f"{session_id}.jsonl"


def test_read_agent_conversation_filters_events(tmp_path: Path):
    home = tmp_path / "home"
    session_id, jsonl = _seed_session(home)
    _write_jsonl(
        jsonl,
        [
            {"type": "thinking", "id": "t1", "timestamp": "2026-02-22T00:00:00Z"},
            {
                "type": "message",
                "id": "u1",
                "timestamp": "2026-02-22T00:00:01Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            },
            {
                "type": "message",
                "id": "tool1",
                "timestamp": "2026-02-22T00:00:02Z",
                "message": {"role": "toolResult", "content": [{"type": "text", "text": "ignore"}]},
            },
            {
                "type": "message",
                "id": "a1",
                "timestamp": "2026-02-22T00:00:03Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "copy that"}]},
            },
        ],
    )

    payload = chat.read_agent_conversation(
        "maestro-project-alpha",
        limit=100,
        project_slug="alpha",
        home_dir=home,
    )
    assert payload["session_id"] == session_id
    assert [item["id"] for item in payload["messages"]] == ["u1", "a1"]
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "assistant"


def test_resolve_agent_session_returns_none_when_missing(tmp_path: Path):
    home = tmp_path / "home"
    session = chat.resolve_agent_session("maestro-project-missing", home_dir=home)
    assert session is None


def test_send_agent_message_validation_errors():
    missing = chat.send_agent_message("", "hi")
    assert missing["ok"] is False
    assert missing["status_code"] == 400

    empty = chat.send_agent_message("maestro-project-alpha", "")
    assert empty["ok"] is False
    assert empty["status_code"] == 400


def test_read_agent_conversation_prefers_profiled_state_root_when_shared_missing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)
    home = tmp_path / "home"
    agent_id = "maestro-project-alpha"
    profiled_dir = home / ".openclaw-maestro-fleet" / "agents" / agent_id / "sessions"
    session_id = "00000000-0000-4000-8000-000000000002"
    _write_json(
        profiled_dir / "sessions.json",
        {
            f"agent:{agent_id}:main": {
                "sessionId": session_id,
                "updatedAt": 456,
            }
        },
    )
    _write_jsonl(
        profiled_dir / f"{session_id}.jsonl",
        [
            {
                "type": "message",
                "id": "u2",
                "timestamp": "2026-03-01T00:00:01Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "hello profiled"}]},
            }
        ],
    )

    payload = chat.read_agent_conversation(
        agent_id,
        limit=10,
        project_slug="alpha",
        home_dir=home,
    )
    assert payload["session_id"] == session_id
    assert [item["id"] for item in payload["messages"]] == ["u2"]


def test_send_agent_message_includes_fleet_profile(monkeypatch):
    recorded = {}

    class _Completed:
        returncode = 0
        stdout = "{\"ok\":true}"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return _Completed()

    monkeypatch.setattr(chat.subprocess, "run", _fake_run)
    payload = chat.send_agent_message("maestro-company", "hello")
    assert payload["ok"] is True
    assert recorded["cmd"][:3] == ["openclaw", "--profile", "maestro-fleet"]
