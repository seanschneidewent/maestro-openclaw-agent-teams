"""Tests for maestro.doctor."""

from __future__ import annotations

import json
from pathlib import Path

import maestro.doctor as doctor
from maestro.fleet.doctor import checks as doctor_checks
from maestro.doctor import run_doctor
from maestro.install_state import save_install_state


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_doctor_fix_creates_tools_md_for_openai(tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    store = tmp_path / "knowledge_store"
    store.mkdir(parents=True, exist_ok=True)

    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "env": {"OPENAI_API_KEY": "sk-test-1234567890"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "Maestro (TestCo)",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace),
                    }
                ]
            },
        },
    )
    (workspace / ".env").parent.mkdir(parents=True, exist_ok=True)
    (workspace / ".env").write_text(f"MAESTRO_STORE={store}\n", encoding="utf-8")

    code = run_doctor(
        fix=True,
        store_override=str(store),
        restart_gateway=False,
        json_output=False,
        home_dir=home,
    )

    assert code == 0
    tools_md = workspace / "TOOLS.md"
    assert tools_md.exists()
    content = tools_md.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" in content
    assert "http://<tailscale-ip>:3000/command-center" in content


def test_doctor_fails_on_placeholder_provider_key(tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    workspace.mkdir(parents=True, exist_ok=True)

    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "env": {"OPENAI_API_KEY": "<PASTE_OPENAI_API_KEY_HERE>"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "Maestro (TestCo)",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace),
                    }
                ]
            },
        },
    )

    code = run_doctor(
        fix=False,
        restart_gateway=False,
        json_output=False,
        home_dir=home,
    )

    assert code == 1


def test_doctor_fix_syncs_gateway_tokens(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    store = tmp_path / "knowledge_store"
    store.mkdir(parents=True, exist_ok=True)

    config_path = home / ".openclaw" / "openclaw.json"
    _write_json(
        config_path,
        {
            "env": {"OPENAI_API_KEY": "sk-test-1234567890"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "Maestro (TestCo)",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace),
                    }
                ]
            },
            "gateway": {"mode": "local"},
        },
    )

    commands: list[list[str]] = []

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        commands.append(args)
        if args[:3] == ["openclaw", "gateway", "install"]:
            return True, "installed"
        if args[:2] == ["openclaw", "status"]:
            return True, "ok"
        if args[:3] == ["openclaw", "devices", "list"]:
            return True, '{"pending":[],"paired":[]}'
        if args[:3] == ["openclaw", "devices", "approve"]:
            return True, '{"ok":true}'
        return True, ""

    monkeypatch.setattr(doctor, "_run_cmd", _fake_run_cmd)

    code = run_doctor(
        fix=True,
        store_override=str(store),
        restart_gateway=False,
        json_output=False,
        home_dir=home,
    )
    assert code == 0

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    gateway = saved.get("gateway", {})
    auth = gateway.get("auth", {})
    remote = gateway.get("remote", {})
    assert isinstance(auth.get("token"), str) and auth["token"]
    assert remote.get("token") == auth.get("token")
    assert ["openclaw", "gateway", "install", "--force", "--port", "18789"] in commands


def test_doctor_runtime_checks_can_be_skipped(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / ".openclaw-maestro-fleet" / "workspace-maestro"
    store = tmp_path / "knowledge_store"
    store.mkdir(parents=True, exist_ok=True)

    _write_json(
        home / ".openclaw-maestro-fleet" / "openclaw.json",
        {
            "env": {"OPENAI_API_KEY": "sk-test-1234567890"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "Maestro (TestCo)",
                        "default": True,
                        "model": "openai/gpt-5.4",
                        "workspace": str(workspace),
                    }
                ]
            },
            "gateway": {"mode": "local"},
        },
    )
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".env").write_text(
        f"MAESTRO_STORE={store}\nMAESTRO_AGENT_ROLE=company\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")

    calls: list[list[str]] = []

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        calls.append(list(args))
        if args[:4] == ["openclaw", "gateway", "status", "--json"]:
            return True, '{"service":{"runtime":{"status":"running"}},"rpc":{"ok":true},"port":{"status":"busy","listeners":[{"pid":1234}]}}'
        if args[:3] == ["openclaw", "devices", "list"]:
            return True, '{"pending":[],"paired":[]}'
        return True, ""

    monkeypatch.setattr(doctor, "_run_cmd", _fake_run_cmd)

    report = doctor.build_doctor_report(
        fix=True,
        store_override=str(store),
        restart_gateway=True,
        runtime_checks=False,
        home_dir=home,
    )

    checks = report.get("checks", [])
    names = {item.get("name") for item in checks if isinstance(item, dict)}
    assert "gateway_auth_tokens" in names
    assert "launchagent_env_sync" not in names
    assert "gateway_launchagent_sync" not in names
    assert "gateway_restart" not in names
    assert "cli_device_pairing" not in names
    assert "gateway_running" not in names
    assert calls == []


def test_doctor_fix_auto_approves_single_device_pairing_request(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    store = tmp_path / "knowledge_store"
    store.mkdir(parents=True, exist_ok=True)

    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "env": {"OPENAI_API_KEY": "sk-test-1234567890"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "Maestro (TestCo)",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace),
                    }
                ]
            },
            "gateway": {
                "mode": "local",
                "auth": {"token": "abc123"},
                "remote": {"token": "abc123"},
            },
        },
    )

    commands: list[list[str]] = []

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        commands.append(args)
        if args[:2] == ["openclaw", "status"]:
            return True, "gateway connect failed: Error: pairing required"
        if args[:3] == ["openclaw", "devices", "list"]:
            return True, '{"pending":[{"requestId":"req-1"}],"paired":[]}'
        if args[:3] == ["openclaw", "devices", "approve"]:
            return True, '{"ok":true}'
        return True, ""

    monkeypatch.setattr(doctor, "_run_cmd", _fake_run_cmd)

    code = run_doctor(
        fix=True,
        store_override=str(store),
        restart_gateway=False,
        json_output=False,
        home_dir=home,
    )
    assert code == 0
    assert ["openclaw", "devices", "approve", "--latest", "--json"] in commands


def test_doctor_fix_adds_missing_telegram_bindings(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    store = tmp_path / "knowledge_store"
    store.mkdir(parents=True, exist_ok=True)

    config_path = home / ".openclaw" / "openclaw.json"
    _write_json(
        config_path,
        {
            "env": {"OPENAI_API_KEY": "sk-test-1234567890"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "Maestro (TestCo)",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace),
                    },
                    {
                        "id": "maestro-project-alpha",
                        "name": "Maestro (Alpha)",
                        "default": False,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace / "projects" / "alpha"),
                    },
                ]
            },
            "channels": {
                "telegram": {
                    "enabled": True,
                    "accounts": {
                        "maestro-company": {"botToken": "123456:AAA"},
                        "maestro-project-alpha": {"botToken": "123456:BBB"},
                    },
                }
            },
            "gateway": {
                "mode": "local",
                "auth": {"token": "abc123"},
                "remote": {"token": "abc123"},
            },
        },
    )

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        if args[:2] == ["openclaw", "status"]:
            return True, "gateway service running"
        if args[:3] == ["openclaw", "devices", "list"]:
            return True, '{"pending":[],"paired":[]}'
        return True, ""

    monkeypatch.setattr(doctor, "_run_cmd", _fake_run_cmd)

    code = run_doctor(
        fix=True,
        store_override=str(store),
        restart_gateway=False,
        json_output=False,
        home_dir=home,
    )
    assert code == 0

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    bindings = saved.get("bindings", [])
    assert {
        "agentId": "maestro-company",
        "match": {"channel": "telegram", "accountId": "maestro-company"},
    } in bindings
    assert {
        "agentId": "maestro-project-alpha",
        "match": {"channel": "telegram", "accountId": "maestro-project-alpha"},
    } in bindings


def test_doctor_solo_field_access_required_fails_without_tailscale(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    store = tmp_path / "knowledge_store"
    workspace.mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)

    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "env": {"OPENAI_API_KEY": "sk-test-1234567890"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-personal",
                        "name": "Maestro Personal",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace),
                    }
                ]
            },
        },
    )
    (workspace / ".env").write_text(f"MAESTRO_STORE={store}\nMAESTRO_AGENT_ROLE=project\n", encoding="utf-8")

    monkeypatch.setattr(
        doctor,
        "resolve_network_urls",
        lambda web_port=3000, route_path="/workspace": {
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": None,
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "tailscale_ip": None,
        },
    )

    code = run_doctor(
        fix=False,
        store_override=str(store),
        restart_gateway=False,
        field_access_required=True,
        json_output=False,
        home_dir=home,
    )
    assert code == 1


def test_doctor_allows_openclaw_oauth_without_provider_key(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    store = tmp_path / "knowledge_store"
    workspace.mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)

    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "env": {},
            "agents": {
                "list": [
                    {
                        "id": "maestro-personal",
                        "name": "Maestro Personal",
                        "default": True,
                        "model": "openai-codex/gpt-5.2",
                        "workspace": str(workspace),
                    }
                ]
            },
            "gateway": {
                "mode": "local",
                "auth": {"token": "abc123"},
                "remote": {"token": "abc123"},
            },
        },
    )
    (workspace / ".env").write_text(
        f"MAESTRO_STORE={store}\nMAESTRO_AGENT_ROLE=project\nMAESTRO_MODEL_AUTH_METHOD=openclaw_oauth\n",
        encoding="utf-8",
    )

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        if args[:3] == ["openclaw", "gateway", "install"]:
            return True, "installed"
        if args[:2] == ["openclaw", "status"]:
            return True, "gateway service running"
        if args[:3] == ["openclaw", "devices", "list"]:
            return True, '{"pending":[],"paired":[]}'
        if args[:3] == ["openclaw", "devices", "approve"]:
            return True, '{"ok":true}'
        return True, ""

    monkeypatch.setattr(doctor, "_run_cmd", _fake_run_cmd)

    code = run_doctor(
        fix=True,
        store_override=str(store),
        restart_gateway=False,
        json_output=False,
        home_dir=home,
    )
    assert code == 0


def test_doctor_prefers_fleet_profiled_openclaw_config(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    store = tmp_path / "knowledge_store"
    store.mkdir(parents=True, exist_ok=True)

    fleet_workspace = home / ".openclaw-maestro-fleet" / "workspace-maestro"
    fleet_workspace.mkdir(parents=True, exist_ok=True)
    (fleet_workspace / ".env").write_text(f"MAESTRO_STORE={store}\n", encoding="utf-8")

    # Shared config exists but should not be selected when Fleet profile is active.
    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "env": {"OPENAI_API_KEY": "<PASTE_OPENAI_API_KEY_HERE>"},
            "agents": {"list": []},
        },
    )
    _write_json(
        home / ".openclaw-maestro-fleet" / "openclaw.json",
        {
            "env": {"OPENAI_API_KEY": "sk-test-1234567890"},
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "name": "Maestro (FleetCo)",
                        "default": True,
                        "model": "openai/gpt-5.2",
                        "workspace": str(fleet_workspace),
                    }
                ]
            },
        },
    )
    save_install_state(
        {
            "profile": "fleet",
            "fleet_enabled": True,
            "store_root": str(store),
        },
        home_dir=home,
    )

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        if args[:2] == ["openclaw", "status"]:
            return True, "gateway service running"
        if args[:3] == ["openclaw", "devices", "list"]:
            return True, '{"pending":[],"paired":[]}'
        if args[:3] == ["openclaw", "gateway", "status"]:
            return True, '{"service":{"runtime":{"status":"running"}}}'
        return True, ""

    monkeypatch.setattr(doctor, "_run_cmd", _fake_run_cmd)

    report = doctor.build_doctor_report(
        fix=False,
        store_override=str(store),
        restart_gateway=False,
        home_dir=home,
    )
    checks = report.get("checks", [])
    config_check = next((c for c in checks if isinstance(c, dict) and c.get("name") == "openclaw_config"), {})
    assert config_check.get("ok") is True
    assert ".openclaw-maestro-fleet/openclaw.json" in str(config_check.get("detail", ""))


def test_gateway_running_accepts_rpc_healthy_task_state():
    def _fake_run_cmd(args: list[str], timeout: int = 25):
        if args[:4] == ["openclaw", "gateway", "status", "--json"]:
            return True, json.dumps(
                {
                    "service": {"runtime": {"status": "stopped", "state": "Ready"}},
                    "rpc": {"ok": True, "url": "ws://127.0.0.1:18789"},
                    "port": {"status": "busy", "listeners": [{"pid": 1234}]},
                }
            )
        raise AssertionError(f"unexpected command: {args}")

    assert doctor_checks.gateway_running(run_cmd=_fake_run_cmd) is True


def test_gateway_running_accepts_busy_listener_when_rpc_probe_is_unavailable():
    def _fake_run_cmd(args: list[str], timeout: int = 25):
        if args[:4] == ["openclaw", "gateway", "status", "--json"]:
            return True, json.dumps(
                {
                    "service": {"runtime": {"status": "stopped", "state": "Ready"}},
                    "rpc": {"ok": False, "error": "probe skipped"},
                    "port": {"status": "busy", "listeners": [{"pid": 1234}]},
                }
            )
        raise AssertionError(f"unexpected command: {args}")

    assert doctor_checks.gateway_running(run_cmd=_fake_run_cmd) is True
