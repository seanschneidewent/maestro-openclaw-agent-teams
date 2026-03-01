"""Tests for fleet deployment helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maestro import fleet_deploy


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_validate_api_key_accepts_vertex_api_key_on_gemini_403(monkeypatch):
    class _Response:
        def __init__(self, status_code: int):
            self.status_code = status_code

    monkeypatch.setattr(
        fleet_deploy.httpx,
        "get",
        lambda *args, **kwargs: _Response(403),
    )

    ok, detail = fleet_deploy._validate_api_key("GEMINI_API_KEY", "AIza" + ("A" * 35))
    assert ok is True
    assert "Vertex API key accepted" in detail


def test_validate_api_key_accepts_vertex_access_token(monkeypatch):
    class _Response:
        def __init__(self, status_code: int):
            self.status_code = status_code

    def _fake_get(url: str, *args, **kwargs):
        if "oauth2.googleapis.com/tokeninfo" in url:
            return _Response(200)
        return _Response(401)

    monkeypatch.setattr(fleet_deploy.httpx, "get", _fake_get)

    ok, detail = fleet_deploy._validate_api_key("GEMINI_API_KEY", "ya29.test-vertex-token")
    assert ok is True
    assert "Vertex token status=200" in detail


def test_configure_company_openclaw_writes_schema_valid_telegram_account(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {},
        "agents": {"list": []},
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda: (config, config_path))

    result = fleet_deploy._configure_company_openclaw(
        model="openai/gpt-5.2",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        allow_openclaw_override=False,
    )
    assert result["config_path"] == str(config_path)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    account = saved["channels"]["telegram"]["accounts"]["maestro-company"]
    assert set(account.keys()) == {"botToken", "dmPolicy", "groupPolicy", "streamMode"}


def test_configure_company_openclaw_blocks_unmanaged_default_agent(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "agents": {
            "list": [
                {"id": "external-agent", "default": True, "model": "openai/gpt-5.2"},
            ]
        }
    }
    _write_json(config_path, config)
    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda: (config, config_path))

    with pytest.raises(RuntimeError, match="does not look Maestro-managed"):
        fleet_deploy._configure_company_openclaw(
            model="openai/gpt-5.2",
            api_key="sk-test-openai-key",
            telegram_token="123456:ABCDEF",
            allow_openclaw_override=False,
        )
