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


def test_validate_api_key_accepts_vertex_api_key_via_aiplatform_probe(monkeypatch):
    class _Response:
        def __init__(self, status_code: int):
            self.status_code = status_code

    monkeypatch.setattr(
        fleet_deploy.httpx,
        "get",
        lambda *args, **kwargs: _Response(401),
    )
    monkeypatch.setattr(
        fleet_deploy.httpx,
        "post",
        lambda *args, **kwargs: _Response(200),
    )

    ok, detail = fleet_deploy._validate_api_key("GEMINI_API_KEY", "AQ.Afakeyvertexstyletoken")
    assert ok is True
    assert "Vertex status=200" in detail


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
    monkeypatch.setattr(
        fleet_deploy,
        "_check_shared_gateway_collision",
        lambda target_gateway_port: {"blocked": False},
    )
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
    monkeypatch.setattr(
        fleet_deploy,
        "_check_shared_gateway_collision",
        lambda target_gateway_port: {"blocked": False},
    )
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


def test_run_deploy_prompts_for_new_key_when_existing_config_key_declined(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {"GEMINI_API_KEY": "AIzaEXISTINGINVALID0000000000000000"},
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True, "model": "google/gemini-3-pro-preview"},
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

    store_root = tmp_path / "store"
    captured_api_key: dict[str, str] = {}

    monkeypatch.setattr(
        fleet_deploy,
        "_check_prereqs",
        lambda require_tailscale: fleet_deploy.PrereqResult(ok=True, failures=[], warnings=[]),
    )
    monkeypatch.setattr(fleet_deploy, "set_profile", lambda *args, **kwargs: {"profile": "fleet"})
    monkeypatch.setattr(fleet_deploy, "_ensure_openclaw_config_exists", lambda *args, **kwargs: config_path)
    monkeypatch.setattr(
        fleet_deploy,
        "_check_shared_gateway_collision",
        lambda target_gateway_port: {"blocked": False},
    )
    monkeypatch.setattr(fleet_deploy, "run_update", lambda **kwargs: 0)
    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))

    def _fake_configure_company_openclaw(**kwargs):
        captured_api_key["value"] = str(kwargs.get("api_key", ""))
        return {
            "config_path": str(config_path),
            "workspace_root": str(tmp_path / "workspace-maestro"),
            "provider_env_key": "GEMINI_API_KEY",
            "binding_changes": [],
        }

    monkeypatch.setattr(fleet_deploy, "_configure_company_openclaw", _fake_configure_company_openclaw)
    monkeypatch.setattr(fleet_deploy, "resolve_fleet_store_root", lambda _store: store_root)
    monkeypatch.setattr(fleet_deploy, "save_install_state", lambda payload: None)
    monkeypatch.setattr(fleet_deploy, "run_doctor", lambda **kwargs: 0)
    monkeypatch.setattr(
        fleet_deploy,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": "",
        },
    )

    # Decline existing key, then provide a fresh one at prompt.
    monkeypatch.setattr(fleet_deploy.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        fleet_deploy.Prompt,
        "ask",
        lambda *args, **kwargs: "AIzaNEWKEY00000000000000000000000000",
    )

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="google/gemini-3-pro-preview",
        telegram_token="123456:ABCDEF",
        non_interactive=False,
        skip_remote_validation=True,
        start_services=False,
    )
    assert code == 0
    assert captured_api_key["value"] == "AIzaNEWKEY00000000000000000000000000"


def test_run_deploy_existing_key_prompt_defaults_to_no(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {"GEMINI_API_KEY": "AIzaEXISTINGINVALID0000000000000000"},
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True, "model": "google/gemini-3-pro-preview"},
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

    observed: list[tuple[str, object]] = []

    monkeypatch.setattr(
        fleet_deploy,
        "_check_prereqs",
        lambda require_tailscale: fleet_deploy.PrereqResult(ok=True, failures=[], warnings=[]),
    )
    monkeypatch.setattr(fleet_deploy, "set_profile", lambda *args, **kwargs: {"profile": "fleet"})
    monkeypatch.setattr(fleet_deploy, "_ensure_openclaw_config_exists", lambda *args, **kwargs: config_path)
    monkeypatch.setattr(
        fleet_deploy,
        "_check_shared_gateway_collision",
        lambda target_gateway_port: {"blocked": False},
    )
    monkeypatch.setattr(fleet_deploy, "run_update", lambda **kwargs: 0)
    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))
    monkeypatch.setattr(
        fleet_deploy,
        "_configure_company_openclaw",
        lambda **kwargs: {
            "config_path": str(config_path),
            "workspace_root": str(tmp_path / "workspace-maestro"),
            "provider_env_key": "GEMINI_API_KEY",
            "binding_changes": [],
        },
    )
    monkeypatch.setattr(fleet_deploy, "resolve_fleet_store_root", lambda _store: (tmp_path / "store"))
    monkeypatch.setattr(fleet_deploy, "save_install_state", lambda payload: None)
    monkeypatch.setattr(fleet_deploy, "run_doctor", lambda **kwargs: 0)
    monkeypatch.setattr(
        fleet_deploy,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": "",
        },
    )

    def _fake_confirm_ask(*args, **kwargs):
        prompt = str(args[0]) if args else ""
        observed.append((prompt, kwargs.get("default")))
        return False

    monkeypatch.setattr(fleet_deploy.Confirm, "ask", _fake_confirm_ask)
    monkeypatch.setattr(
        fleet_deploy.Prompt,
        "ask",
        lambda *args, **kwargs: "AIzaNEWKEY00000000000000000000000000",
    )

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="google/gemini-3-pro-preview",
        telegram_token="123456:ABCDEF",
        non_interactive=False,
        skip_remote_validation=True,
        start_services=False,
    )
    assert code == 0
    existing_key_prompt = next(
        (
            default
            for prompt, default in observed
            if "Use existing GEMINI_API_KEY from OpenClaw config" in prompt
        ),
        None,
    )
    assert existing_key_prompt is False


def test_fleet_openclaw_profile_isolated_from_shared_config(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    shared_path = home / ".openclaw" / "openclaw.json"
    _write_json(
        shared_path,
        {
            "agents": {
                "list": [
                    {"id": "main", "default": True, "model": "openai/gpt-5.2"},
                ]
            }
        },
    )

    monkeypatch.setattr(fleet_deploy.Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")

    created = fleet_deploy._ensure_openclaw_config_exists()
    config, loaded_path = fleet_deploy._load_openclaw_config()

    assert created == home / ".openclaw-maestro-fleet" / "openclaw.json"
    assert loaded_path == created
    assert config == {}


def test_run_cmd_defaults_openclaw_profile_to_maestro_fleet(monkeypatch):
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)
    observed: dict[str, list[str]] = {}

    def _fake_run(args, **kwargs):
        observed["args"] = list(args)
        observed["env"] = dict(kwargs.get("env", {}) or {})

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Result()

    monkeypatch.setattr(fleet_deploy.subprocess, "run", _fake_run)

    ok, out = fleet_deploy._run_cmd(["openclaw", "status"])
    assert ok is True
    assert out == "ok"
    assert observed["args"][:3] == ["openclaw", "--profile", "maestro-fleet"]
    assert observed["args"][3:] == ["status"]


def test_run_cmd_does_not_add_profile_to_non_openclaw(monkeypatch):
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)
    observed: dict[str, list[str]] = {}

    def _fake_run(args, **kwargs):
        observed["args"] = list(args)
        observed["env"] = dict(kwargs.get("env", {}) or {})

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Result()

    monkeypatch.setattr(fleet_deploy.subprocess, "run", _fake_run)

    ok, out = fleet_deploy._run_cmd(["tailscale", "ip", "-4"])
    assert ok is True
    assert out == "ok"
    assert observed["args"] == ["tailscale", "ip", "-4"]
    assert "OPENCLAW_GATEWAY_PORT" not in observed.get("env", {})


def test_ensure_gateway_running_for_pairing_when_already_running(monkeypatch):
    monkeypatch.setattr(
        fleet_deploy,
        "_run_cmd",
        lambda args, timeout=12: (True, "Gateway service: running"),
    )
    result = fleet_deploy._ensure_gateway_running_for_pairing()
    assert result["ok"] is True
    assert result["already_running"] is True


def test_ensure_gateway_running_for_pairing_restarts_when_needed(monkeypatch):
    responses = iter([
        (False, "Gateway service: stopped"),
        (False, '{"service":{"runtime":{"status":"stopped"}}}'),
        (True, "restart ok"),
        (True, "Gateway service: running"),
        (True, '{"service":{"runtime":{"status":"running"}}}'),
    ])

    def _fake_run(args, timeout=12):
        return next(responses)

    monkeypatch.setattr(fleet_deploy, "_run_cmd", _fake_run)
    result = fleet_deploy._ensure_gateway_running_for_pairing()
    assert result["ok"] is True
    assert result["already_running"] is False
    assert result["restart_attempt_ok"] is True


def test_run_deploy_blocks_when_shared_gateway_would_collide(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    _write_json(config_path, {"env": {}, "agents": {"list": []}})

    monkeypatch.setattr(
        fleet_deploy,
        "_check_prereqs",
        lambda require_tailscale: fleet_deploy.PrereqResult(ok=True, failures=[], warnings=[]),
    )
    monkeypatch.setattr(fleet_deploy, "set_profile", lambda *args, **kwargs: {"profile": "fleet"})
    monkeypatch.setattr(fleet_deploy, "_ensure_openclaw_config_exists", lambda *args, **kwargs: config_path)
    monkeypatch.setattr(
        fleet_deploy,
        "_check_shared_gateway_collision",
        lambda target_gateway_port: {"blocked": True, "shared_port": 18789},
    )

    called = {"update": False}

    def _no_update(**kwargs):
        called["update"] = True
        return 0

    monkeypatch.setattr(fleet_deploy, "run_update", _no_update)

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        non_interactive=True,
        skip_remote_validation=True,
        start_services=False,
    )
    assert code == 1
    assert called["update"] is False
