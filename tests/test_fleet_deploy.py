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


def test_resolve_deploy_port_prefers_requested_when_free(monkeypatch):
    monkeypatch.setattr(fleet_deploy, "_port_listening", lambda port, host="127.0.0.1": False)
    port, shifted = fleet_deploy._resolve_deploy_port(3000)
    assert port == 3000
    assert shifted is False


def test_resolve_deploy_port_falls_forward_when_requested_in_use(monkeypatch):
    def _fake_port_listening(port: int, host: str = "127.0.0.1") -> bool:
        return port in {3000, 3001}

    monkeypatch.setattr(fleet_deploy, "_port_listening", _fake_port_listening)
    port, shifted = fleet_deploy._resolve_deploy_port(3000)
    assert port == 3002
    assert shifted is True


def test_run_deploy_uses_shifted_port_when_requested_port_busy(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {},
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True, "model": "openai/gpt-5.2"},
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

    store_root = tmp_path / "store"
    captured: dict[str, int] = {}

    monkeypatch.setattr(
        fleet_deploy,
        "_check_prereqs",
        lambda require_tailscale: fleet_deploy.PrereqResult(ok=True, failures=[], warnings=[]),
    )
    monkeypatch.setattr(fleet_deploy, "set_profile", lambda *args, **kwargs: {"profile": "fleet"})
    monkeypatch.setattr(fleet_deploy, "_ensure_openclaw_config_exists", lambda *args, **kwargs: config_path)
    monkeypatch.setattr(fleet_deploy, "run_update", lambda **kwargs: 0)
    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))
    monkeypatch.setattr(
        fleet_deploy,
        "_configure_company_openclaw",
        lambda **kwargs: {
            "config_path": str(config_path),
            "workspace_root": str(tmp_path / "workspace-maestro"),
            "provider_env_key": "OPENAI_API_KEY",
            "binding_changes": [],
        },
    )
    monkeypatch.setattr(fleet_deploy, "resolve_fleet_store_root", lambda _store: store_root)
    monkeypatch.setattr(fleet_deploy, "save_install_state", lambda payload: None)
    monkeypatch.setattr(fleet_deploy, "run_doctor", lambda **kwargs: 0)
    monkeypatch.setattr(fleet_deploy, "_resolve_deploy_port", lambda preferred_port, max_attempts=20: (3011, True))
    def _fake_start_detached_server(*, port: int, store_root: Path, host: str) -> dict:
        captured["port"] = int(port)
        return {
            "ok": True,
            "already_running": False,
            "pid": 12345,
            "pid_path": str(tmp_path / "serve.pid.json"),
            "log_path": str(tmp_path / "serve.log"),
        }

    monkeypatch.setattr(fleet_deploy, "_start_detached_server", _fake_start_detached_server)
    monkeypatch.setattr(fleet_deploy, "_verify_command_center_http", lambda port, timeout_seconds=25: True)
    monkeypatch.setattr(
        fleet_deploy,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": "",
        },
    )

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="openai/gpt-5.2",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        port=3000,
        non_interactive=True,
        skip_remote_validation=True,
        start_services=True,
    )
    assert code == 0
    assert captured["port"] == 3011


def test_run_deploy_reuses_existing_server_port_from_pid_state(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {},
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True, "model": "openai/gpt-5.2"},
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

    store_root = tmp_path / "store"
    checked_port: dict[str, int] = {}

    monkeypatch.setattr(
        fleet_deploy,
        "_check_prereqs",
        lambda require_tailscale: fleet_deploy.PrereqResult(ok=True, failures=[], warnings=[]),
    )
    monkeypatch.setattr(fleet_deploy, "set_profile", lambda *args, **kwargs: {"profile": "fleet"})
    monkeypatch.setattr(fleet_deploy, "_ensure_openclaw_config_exists", lambda *args, **kwargs: config_path)
    monkeypatch.setattr(fleet_deploy, "run_update", lambda **kwargs: 0)
    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))
    monkeypatch.setattr(
        fleet_deploy,
        "_configure_company_openclaw",
        lambda **kwargs: {
            "config_path": str(config_path),
            "workspace_root": str(tmp_path / "workspace-maestro"),
            "provider_env_key": "OPENAI_API_KEY",
            "binding_changes": [],
        },
    )
    monkeypatch.setattr(fleet_deploy, "resolve_fleet_store_root", lambda _store: store_root)
    monkeypatch.setattr(fleet_deploy, "save_install_state", lambda payload: None)
    monkeypatch.setattr(fleet_deploy, "run_doctor", lambda **kwargs: 0)
    monkeypatch.setattr(fleet_deploy, "_resolve_deploy_port", lambda preferred_port, max_attempts=20: (3011, True))
    monkeypatch.setattr(
        fleet_deploy,
        "_start_detached_server",
        lambda **kwargs: {
            "ok": True,
            "already_running": True,
            "pid": 77777,
            "port": 3010,
            "port_mismatch": True,
            "pid_path": str(tmp_path / "serve.pid.json"),
            "log_path": str(tmp_path / "serve.log"),
        },
    )
    def _fake_verify_command_center_http(port: int, timeout_seconds: int = 25) -> bool:
        checked_port["port"] = int(port)
        return True

    monkeypatch.setattr(fleet_deploy, "_verify_command_center_http", _fake_verify_command_center_http)
    monkeypatch.setattr(
        fleet_deploy,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": "",
        },
    )

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="openai/gpt-5.2",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        port=3000,
        non_interactive=True,
        skip_remote_validation=True,
        start_services=True,
    )
    assert code == 0
    assert checked_port["port"] == 3010
