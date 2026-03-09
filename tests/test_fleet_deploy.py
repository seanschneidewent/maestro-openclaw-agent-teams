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
        model="openai/gpt-5.4",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        allow_openclaw_override=False,
    )
    assert result["config_path"] == str(config_path)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    account = saved["channels"]["telegram"]["accounts"]["maestro-company"]
    assert set(account.keys()) == {"botToken", "dmPolicy", "groupPolicy", "streamMode"}
    assert "botToken" not in saved["channels"]["telegram"]


def test_configure_company_openclaw_removes_duplicate_default_telegram_account(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {},
        "agents": {"list": []},
        "channels": {
            "telegram": {
                "enabled": True,
                "botToken": "123456:OLD",
                "accounts": {
                    "default": {
                        "botToken": "123456:ABCDEF",
                        "dmPolicy": "pairing",
                        "groupPolicy": "allowlist",
                        "streamMode": "partial",
                    }
                },
            }
        },
    }
    _write_json(config_path, config)

    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda: (config, config_path))

    fleet_deploy._configure_company_openclaw(
        model="openai/gpt-5.4",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        allow_openclaw_override=False,
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    accounts = saved["channels"]["telegram"]["accounts"]
    assert "default" not in accounts
    assert accounts["maestro-company"]["botToken"] == "123456:ABCDEF"
    assert "botToken" not in saved["channels"]["telegram"]


def test_configure_company_openclaw_blocks_unmanaged_default_agent(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "agents": {
            "list": [
                {"id": "external-agent", "default": True, "model": "openai/gpt-5.4"},
            ]
        }
    }
    _write_json(config_path, config)
    monkeypatch.setattr(fleet_deploy, "_load_openclaw_config", lambda: (config, config_path))

    with pytest.raises(RuntimeError, match="does not look Maestro-managed"):
        fleet_deploy._configure_company_openclaw(
            model="openai/gpt-5.4",
            api_key="sk-test-openai-key",
            telegram_token="123456:ABCDEF",
            allow_openclaw_override=False,
        )


def test_resolve_deploy_port_prefers_requested_when_free(monkeypatch):
    monkeypatch.setattr(fleet_deploy, "_port_listening", lambda port, host="127.0.0.1": False)
    port, shifted = fleet_deploy._resolve_deploy_port(3000)
    assert port == 3000
    assert shifted is False


def test_gateway_service_running_accepts_rpc_ok_when_service_reports_stopped():
    assert fleet_deploy._gateway_service_running({
        "service": {"runtime": {"status": "stopped"}},
        "rpc": {"ok": True},
        "port": {"status": "busy", "listeners": [{"pid": 1234}]},
    }) is True


def test_repair_gateway_token_mismatch_evicts_current_listener_after_restart_changes_pid(monkeypatch):
    statuses = iter(
        [
            (
                True,
                {
                    "rpc": {"ok": False, "error": "token mismatch"},
                    "port": {"status": "busy", "listeners": [{"pid": 1001}]},
                },
                '{"rpc":{"error":"token mismatch"}}',
            ),
            (
                True,
                {
                    "rpc": {"ok": False, "error": "token mismatch"},
                    "port": {"status": "busy", "listeners": [{"pid": 2002}]},
                },
                '{"rpc":{"error":"token mismatch"}}',
            ),
            (
                True,
                {
                    "rpc": {"ok": False, "error": "token mismatch"},
                    "port": {"status": "busy", "listeners": [{"pid": 3003}]},
                },
                '{"rpc":{"error":"token mismatch"}}',
            ),
            (
                True,
                {
                    "rpc": {"ok": True},
                    "port": {"status": "busy", "listeners": [{"pid": 4004}]},
                },
                '{"rpc":{"ok":true}}',
            ),
        ]
    )
    evict_calls: list[set[int] | None] = []

    monkeypatch.setattr(fleet_deploy, "_gateway_status_snapshot", lambda timeout=12: next(statuses))
    monkeypatch.setattr(fleet_deploy, "_run_cmd", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(fleet_deploy, "_fleet_gateway_port", lambda: 18789)

    def _fake_evict(gateway_status, *, only_pids=None):
        evict_calls.append(set(only_pids) if only_pids is not None else None)
        return [pid for pid in sorted(only_pids or [])]

    monkeypatch.setattr(fleet_deploy, "_evict_gateway_listener_pids", _fake_evict)

    result = fleet_deploy._repair_gateway_device_token_mismatch()

    assert result["repaired"] is True
    assert evict_calls == [{1001, 3003}]


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
                {"id": "maestro-company", "default": True, "model": "openai/gpt-5.4"},
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
    monkeypatch.setattr(fleet_deploy, "_run_doctor_for_deploy", lambda **kwargs: {"code": 0, "timed_out": False, "output": ""})
    monkeypatch.setattr(
        fleet_deploy,
        "_resolve_deploy_port",
        lambda preferred_port, max_attempts=20, **kwargs: (3011, True),
    )
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
    monkeypatch.setattr(
        fleet_deploy,
        "_ensure_gateway_running_for_pairing",
        lambda: {"ok": True, "already_running": True, "detail": "", "actions": []},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_repair_gateway_device_token_mismatch",
        lambda: {"mismatch_detected": False, "repaired": False},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_complete_commander_pairing",
        lambda **kwargs: {"approved": False, "skipped": True, "reason": "test"},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_commissioning_report",
        lambda **kwargs: {"ok": True, "checks": [], "critical_failures": []},
    )

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="openai/gpt-5.4",
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
                {"id": "maestro-company", "default": True, "model": "openai/gpt-5.4"},
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
    monkeypatch.setattr(fleet_deploy, "_run_doctor_for_deploy", lambda **kwargs: {"code": 0, "timed_out": False, "output": ""})
    monkeypatch.setattr(
        fleet_deploy,
        "_resolve_deploy_port",
        lambda preferred_port, max_attempts=20, **kwargs: (3011, True),
    )
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
    monkeypatch.setattr(
        fleet_deploy,
        "_ensure_gateway_running_for_pairing",
        lambda: {"ok": True, "already_running": True, "detail": "", "actions": []},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_repair_gateway_device_token_mismatch",
        lambda: {"mismatch_detected": False, "repaired": False},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_complete_commander_pairing",
        lambda **kwargs: {"approved": False, "skipped": True, "reason": "test"},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_commissioning_report",
        lambda **kwargs: {"ok": True, "checks": [], "critical_failures": []},
    )

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="openai/gpt-5.4",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        port=3000,
        non_interactive=True,
        skip_remote_validation=True,
        start_services=True,
    )
    assert code == 0
    assert checked_port["port"] == 3010


def test_run_deploy_doctor_output_with_brackets_does_not_trigger_rich_markup(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {},
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True, "model": "openai/gpt-5.4"},
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

    store_root = tmp_path / "store"

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
    monkeypatch.setattr(
        fleet_deploy,
        "_run_doctor_for_deploy",
        lambda **kwargs: {
            "code": 0,
            "timed_out": False,
            "output": "gateway connect failed: [/Users/fleetlab/.maestro/toolchain/node-v24.12.0-darwin-x64/bin/node]",
        },
    )
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
        model="openai/gpt-5.4",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        skip_remote_validation=True,
        start_services=False,
    )
    assert code == 0


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
    monkeypatch.setattr(fleet_deploy, "_run_doctor_for_deploy", lambda **kwargs: {"code": 0, "timed_out": False, "output": ""})
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
    monkeypatch.setattr(fleet_deploy, "_run_doctor_for_deploy", lambda **kwargs: {"code": 0, "timed_out": False, "output": ""})
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


def test_run_deploy_stays_commander_only_by_default(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {},
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True, "model": "openai/gpt-5.4"},
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

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
    monkeypatch.setattr(fleet_deploy, "resolve_fleet_store_root", lambda _store: (tmp_path / "store"))
    monkeypatch.setattr(fleet_deploy, "save_install_state", lambda payload: None)
    monkeypatch.setattr(fleet_deploy, "_run_doctor_for_deploy", lambda **kwargs: {"code": 0, "timed_out": False, "output": ""})
    monkeypatch.setattr(
        fleet_deploy,
        "_repair_gateway_device_token_mismatch",
        lambda: {"mismatch_detected": False, "repaired": False},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_ensure_gateway_running_for_pairing",
        lambda: {"ok": True, "already_running": True, "actions": []},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_complete_commander_pairing",
        lambda **kwargs: {"approved": False, "skipped": True, "reason": "user_skipped"},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_commissioning_report",
        lambda **kwargs: {"ok": True, "checks": [], "critical_failures": []},
    )
    monkeypatch.setattr(fleet_deploy, "_print_commissioning_report", lambda report: None)
    monkeypatch.setattr(
        fleet_deploy,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": "",
        },
    )

    def _fail_run_project_create(**kwargs):
        _ = kwargs
        raise AssertionError("run_project_create should not be called")

    monkeypatch.setattr(fleet_deploy, "run_project_create", _fail_run_project_create)

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="openai/gpt-5.4",
        project_model="openai/gpt-5.4",
        gemini_api_key="AIzaTestGeminiKey0000000000000000000000",
        openai_api_key="sk-test-openai-key",
        anthropic_api_key="sk-ant-test-key",
        telegram_token="123456:ABCDEF",
        non_interactive=False,
        skip_remote_validation=True,
        start_services=False,
    )
    assert code == 0


def test_run_deploy_ignores_initial_project_args_without_explicit_opt_in(monkeypatch, tmp_path: Path, capsys):
    home = tmp_path / "home"
    config_path = home / ".openclaw" / "openclaw.json"
    config = {
        "env": {},
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True, "model": "openai/gpt-5.4"},
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }
    _write_json(config_path, config)

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
    monkeypatch.setattr(fleet_deploy, "resolve_fleet_store_root", lambda _store: (tmp_path / "store"))
    monkeypatch.setattr(fleet_deploy, "save_install_state", lambda payload: None)
    monkeypatch.setattr(fleet_deploy, "_run_doctor_for_deploy", lambda **kwargs: {"code": 0, "timed_out": False, "output": ""})
    monkeypatch.setattr(
        fleet_deploy,
        "_repair_gateway_device_token_mismatch",
        lambda: {"mismatch_detected": False, "repaired": False},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_ensure_gateway_running_for_pairing",
        lambda: {"ok": True, "already_running": True, "actions": []},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_complete_commander_pairing",
        lambda **kwargs: {"approved": False, "skipped": True, "reason": "user_skipped"},
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_commissioning_report",
        lambda **kwargs: {"ok": True, "checks": [], "critical_failures": []},
    )
    monkeypatch.setattr(fleet_deploy, "_print_commissioning_report", lambda report: None)
    monkeypatch.setattr(
        fleet_deploy,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": "",
        },
    )

    def _fail_run_project_create(**kwargs):
        _ = kwargs
        raise AssertionError("run_project_create should not be called without explicit opt-in")

    monkeypatch.setattr(fleet_deploy, "run_project_create", _fail_run_project_create)

    code = fleet_deploy.run_deploy(
        company_name="TestCo",
        model="openai/gpt-5.4",
        project_model="openai/gpt-5.4",
        gemini_api_key="AIzaTestGeminiKey0000000000000000000000",
        openai_api_key="sk-test-openai-key",
        anthropic_api_key="sk-ant-test-key",
        telegram_token="123456:ABCDEF",
        project_name="Tower A",
        assignee="Sean",
        project_telegram_token="123:abc",
        non_interactive=True,
        skip_remote_validation=True,
        start_services=False,
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "Initial project Maestro: not provisioned" in captured.out


def test_fleet_openclaw_profile_isolated_from_shared_config(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    shared_path = home / ".openclaw" / "openclaw.json"
    _write_json(
        shared_path,
        {
            "agents": {
                "list": [
                    {"id": "main", "default": True, "model": "openai/gpt-5.4"},
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
        lambda args, timeout=12: (True, '{"service":{"runtime":{"status":"running"}}}'),
    )
    result = fleet_deploy._ensure_gateway_running_for_pairing()
    assert result["ok"] is True
    assert result["already_running"] is True


def test_read_process_command_windows_uses_powershell(monkeypatch):
    observed: dict[str, object] = {}

    class _Result:
        stdout = 'C:\\Python313\\python.exe -m maestro.cli serve --port 3401 --store C:\\fleet'

    def _fake_run(args, **kwargs):
        observed["args"] = list(args)
        observed["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(fleet_deploy.os, "name", "nt", raising=False)
    monkeypatch.setattr(fleet_deploy.subprocess, "run", _fake_run)

    command = fleet_deploy._read_process_command(4242)
    assert command.endswith("--store C:\\fleet")
    assert observed["args"][:3] == ["powershell", "-NoProfile", "-Command"]
    assert 'ProcessId=4242' in str(observed["args"][3])


def test_listener_pids_windows_uses_powershell(monkeypatch):
    observed: dict[str, object] = {}

    class _Result:
        stdout = "1234\n5678\n1234\n"

    def _fake_run(args, **kwargs):
        observed["args"] = list(args)
        observed["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(fleet_deploy.os, "name", "nt", raising=False)
    monkeypatch.setattr(fleet_deploy.subprocess, "run", _fake_run)

    assert fleet_deploy._listener_pids(3401) == [1234, 5678]
    assert observed["args"][:3] == ["powershell", "-NoProfile", "-Command"]
    assert "Get-NetTCPConnection" in str(observed["args"][3])
    assert "-LocalPort 3401" in str(observed["args"][3])


def test_listener_pids_windows_falls_back_to_netstat(monkeypatch):
    calls: list[list[str]] = []

    class _PsResult:
        stdout = ""

    class _NetstatResult:
        stdout = (
            "  TCP    0.0.0.0:3401           0.0.0.0:0              LISTENING       8123\n"
            "  TCP    [::]:3401              [::]:0                 LISTENING       8124\n"
        )

    def _fake_run(args, **kwargs):
        calls.append(list(args))
        if args[0] == "powershell":
            return _PsResult()
        return _NetstatResult()

    monkeypatch.setattr(fleet_deploy.os, "name", "nt", raising=False)
    monkeypatch.setattr(fleet_deploy.subprocess, "run", _fake_run)

    assert fleet_deploy._listener_pids(3401) == [8123, 8124]
    assert calls[0][:3] == ["powershell", "-NoProfile", "-Command"]
    assert calls[1] == ["netstat", "-ano", "-p", "tcp"]


def test_start_detached_server_uses_windows_task_runner(monkeypatch, tmp_path: Path):
    state_dir = tmp_path / "state"
    store_root = tmp_path / "store"
    log_path = state_dir / "serve.log"
    calls: list[str] = []
    listener_checks = iter([[], [4242]])

    monkeypatch.setattr(fleet_deploy, "_is_windows", lambda: True)
    monkeypatch.setattr(fleet_deploy, "_fleet_state_dir", lambda: state_dir)
    monkeypatch.setattr(fleet_deploy, "_listener_pids", lambda port: [])
    monkeypatch.setattr(fleet_deploy, "_pid_running", lambda pid: False)
    monkeypatch.setattr(fleet_deploy, "_managed_listener_pids", lambda **kwargs: next(listener_checks))
    monkeypatch.setattr(
        fleet_deploy,
        "_ensure_windows_server_task",
        lambda **kwargs: calls.append("install") or (True, "task installed"),
    )
    monkeypatch.setattr(
        fleet_deploy,
        "_start_windows_server_task_runner",
        lambda **kwargs: calls.append("start") or (True, "task started"),
    )
    monkeypatch.setattr(fleet_deploy.time, "sleep", lambda _: None)

    result = fleet_deploy._start_detached_server(port=3300, store_root=store_root, host="127.0.0.1")

    assert result["ok"] is True
    assert result["pid"] == 4242
    assert result["task_installed"] is True
    assert calls == ["install", "start"]
    assert (state_dir / "run-fleet-server.ps1").exists()
    assert json.loads((state_dir / "serve.pid.json").read_text(encoding="utf-8"))["pid"] == 4242
    script = (state_dir / "run-fleet-server.ps1").read_text(encoding="utf-8")
    assert str(store_root) in script
    assert str(log_path) in script
    assert "maestro_fleet.server" in script


def test_start_detached_server_windows_task_failure_returns_detail(monkeypatch, tmp_path: Path):
    state_dir = tmp_path / "state"
    store_root = tmp_path / "store"

    monkeypatch.setattr(fleet_deploy, "_is_windows", lambda: True)
    monkeypatch.setattr(fleet_deploy, "_fleet_state_dir", lambda: state_dir)
    monkeypatch.setattr(fleet_deploy, "_listener_pids", lambda port: [])
    monkeypatch.setattr(fleet_deploy, "_pid_running", lambda pid: False)
    monkeypatch.setattr(fleet_deploy, "_managed_listener_pids", lambda **kwargs: [])
    monkeypatch.setattr(
        fleet_deploy,
        "_ensure_windows_server_task",
        lambda **kwargs: (False, "Access denied"),
    )

    result = fleet_deploy._start_detached_server(port=3300, store_root=store_root, host="127.0.0.1")

    assert result["ok"] is False
    assert "Access denied" in result["detail"]


def test_ensure_windows_server_task_uses_schtasks_with_script_path(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    def _fake_run_cmd(args, timeout=12):
        calls.append(list(args))
        return True, "ok"

    monkeypatch.setattr(fleet_deploy, "_run_cmd", _fake_run_cmd)

    ok, _ = fleet_deploy._ensure_windows_server_task(
        task_name="Maestro Fleet Server (maestro-fleet)",
        script_path=tmp_path / "run-fleet-server.ps1",
    )

    assert ok is True
    assert calls[0][:4] == ["schtasks", "/Create", "/TN", "Maestro Fleet Server (maestro-fleet)"]
    assert calls[0][4:8] == ["/TR", f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{tmp_path / "run-fleet-server.ps1"}"', "/SC", "ONCE"]
    assert calls[1] == ["schtasks", "/Query", "/TN", "Maestro Fleet Server (maestro-fleet)", "/FO", "LIST", "/V"]


def test_run_doctor_for_deploy_uses_package_native_fleet_cli(monkeypatch, tmp_path: Path):
    observed: dict[str, object] = {}

    class _Proc:
        pid = 4242
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def communicate(self, timeout=None):
            return ("doctor ok", "")

    def _fake_popen(cmd, **kwargs):
        observed["cmd"] = list(cmd)
        observed["env"] = dict(kwargs.get("env", {}))
        return _Proc()

    monkeypatch.setattr(fleet_deploy.subprocess, "Popen", _fake_popen)

    result = fleet_deploy._run_doctor_for_deploy(store_root=tmp_path / "store")

    assert result == {"code": 0, "timed_out": False, "output": "doctor ok"}
    assert observed["cmd"][:4] == [fleet_deploy.sys.executable, "-m", "maestro_fleet", "doctor"]
    assert "--fix" in observed["cmd"]
    assert observed["env"].get("MAESTRO_OPENCLAW_PROFILE") == "maestro-fleet"


def test_ensure_gateway_running_for_pairing_restarts_when_needed(monkeypatch):
    responses = iter([
        (True, '{"service":{"runtime":{"status":"stopped"}}}'),
        (True, "restart ok"),
        (True, '{"service":{"runtime":{"status":"running"}}}'),
    ])

    def _fake_run(args, timeout=12):
        return next(responses)

    monkeypatch.setattr(fleet_deploy, "_run_cmd", _fake_run)
    result = fleet_deploy._ensure_gateway_running_for_pairing()
    assert result["ok"] is True
    assert result["already_running"] is False
    assert result["restart_attempt_ok"] is True


def test_repair_gateway_device_token_mismatch_evicts_stale_listener(monkeypatch):
    snapshots = iter([
        (
            True,
            {
                "rpc": {"ok": False, "error": "unauthorized: gateway token mismatch"},
                "port": {"status": "busy", "listeners": [{"pid": 42}]},
            },
            "token mismatch",
        ),
        (
            True,
            {
                "rpc": {"ok": False, "error": "unauthorized: gateway token mismatch"},
                "port": {"status": "busy", "listeners": [{"pid": 42}]},
            },
            "still mismatched",
        ),
        (
            True,
            {
                "rpc": {"ok": False, "error": "unauthorized: gateway token mismatch"},
                "port": {"status": "busy", "listeners": [{"pid": 42}]},
            },
            "still mismatched",
        ),
        (
            True,
            {
                "rpc": {"ok": True},
                "service": {"runtime": {"status": "running"}},
                "port": {"status": "busy", "listeners": [{"pid": 99}]},
            },
            "healthy",
        ),
    ])
    commands: list[list[str]] = []

    monkeypatch.setattr(fleet_deploy, "_gateway_status_snapshot", lambda timeout=12: next(snapshots))
    def _fake_run(args, timeout=12):
        commands.append(list(args))
        return True, "ok"

    monkeypatch.setattr(fleet_deploy, "_run_cmd", _fake_run)
    monkeypatch.setattr(fleet_deploy, "_evict_gateway_listener_pids", lambda status, only_pids=None: [42])

    result = fleet_deploy._repair_gateway_device_token_mismatch()
    assert result["ok"] is True
    assert result["repaired"] is True
    assert ["openclaw", "gateway", "start"] in commands
    assert any("evicted stale gateway listener pid(s): 42" in item for item in result["actions"])


def test_ensure_gateway_running_for_pairing_evicts_stale_listener(monkeypatch):
    snapshots = iter([
        (True, {"service": {"runtime": {"status": "stopped"}}, "port": {"status": "free", "listeners": []}} , "stopped"),
        (True, {"service": {"runtime": {"status": "stopped"}}, "port": {"status": "free", "listeners": []}} , "still stopped"),
        (
            True,
            {
                "service": {"runtime": {"status": "stopped"}},
                "rpc": {"ok": False, "error": "unauthorized: gateway token mismatch"},
                "port": {"status": "busy", "listeners": [{"pid": 42}]},
            },
            "still stopped",
        ),
        (True, {"service": {"runtime": {"status": "running"}}, "rpc": {"ok": True}, "port": {"status": "busy", "listeners": [{"pid": 99}]}} , "running"),
    ])
    commands: list[list[str]] = []

    monkeypatch.setattr(fleet_deploy, "_gateway_status_snapshot", lambda timeout=12: next(snapshots))
    def _fake_run(args, timeout=12):
        commands.append(list(args))
        return True, "ok"

    monkeypatch.setattr(fleet_deploy, "_run_cmd", _fake_run)
    monkeypatch.setattr(fleet_deploy, "_evict_gateway_listener_pids", lambda status, only_pids=None: [42])

    result = fleet_deploy._ensure_gateway_running_for_pairing()
    assert result["ok"] is True
    assert result["already_running"] is False
    assert ["openclaw", "gateway", "start"] in commands
    assert any("evicted stale gateway listener pid(s): 42" in item for item in result["actions"])


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
