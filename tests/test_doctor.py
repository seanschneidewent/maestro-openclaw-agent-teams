"""Tests for maestro.doctor."""

from __future__ import annotations

import json
from pathlib import Path

import maestro.doctor as doctor
from maestro.doctor import run_doctor


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
    assert ["openclaw", "gateway", "install", "--force"] in commands


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
