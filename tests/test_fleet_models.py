"""Tests for fleet model-switch operations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from maestro.fleet_constants import canonicalize_model, format_model_display
import maestro.fleet_models as fleet_models


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_set_commander_model_updates_agent_and_env(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "home" / ".openclaw" / "openclaw.json"
    config = {
        "env": {"GEMINI_API_KEY": "AIzaGeminiTest000000000000000000000000"},
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "default": True,
                    "model": "openai/gpt-5.4",
                    "workspace": str(tmp_path / "workspace-company"),
                }
            ]
        },
    }
    _write_json(config_path, config)
    monkeypatch.setattr(fleet_models, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))
    monkeypatch.setattr(fleet_models, "_restart_openclaw_gateway", lambda: (True, "ok"))
    monkeypatch.setattr(fleet_models, "resolve_fleet_store_root", lambda _store: tmp_path / "store")

    code = fleet_models.run_set_commander_model(
        model="anthropic/claude-opus-4-6",
        api_key="sk-ant-test",
        skip_remote_validation=True,
    )
    assert code == 0

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    commander = next(item for item in saved["agents"]["list"] if item.get("id") == "maestro-company")
    assert commander["model"] == "anthropic/claude-opus-4-6"
    assert saved["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test"


def test_set_project_model_updates_target_agent(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "home" / ".openclaw" / "openclaw.json"
    config = {
        "env": {"GEMINI_API_KEY": "AIzaGeminiTest000000000000000000000000"},
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "default": True,
                    "model": "anthropic/claude-opus-4-6",
                    "workspace": str(tmp_path / "workspace-company"),
                },
                {
                    "id": "maestro-project-tower-a",
                    "default": False,
                    "model": "openai/gpt-5.4",
                    "workspace": str(tmp_path / "workspace-project"),
                },
            ]
        },
    }
    _write_json(config_path, config)
    _write_json(
        tmp_path / "store" / "tower-a" / "project.json",
        {
            "name": "Tower A",
            "slug": "tower-a",
        },
    )
    monkeypatch.setattr(fleet_models, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))
    monkeypatch.setattr(fleet_models, "_restart_openclaw_gateway", lambda: (True, "ok"))
    monkeypatch.setattr(fleet_models, "resolve_fleet_store_root", lambda _store: tmp_path / "store")

    code = fleet_models.run_set_project_model(
        project="tower-a",
        model="openai/gpt-5.4",
        api_key="sk-test-openai",
        skip_remote_validation=True,
    )
    assert code == 0

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    project_agent = next(item for item in saved["agents"]["list"] if item.get("id") == "maestro-project-tower-a")
    assert project_agent["model"] == "openai/gpt-5.4"
    assert saved["env"]["OPENAI_API_KEY"] == "sk-test-openai"
    project_payload = json.loads((tmp_path / "store" / "tower-a" / "project.json").read_text(encoding="utf-8"))
    assert project_payload["maestro"]["model"] == "openai/gpt-5.4"
    env_text = (tmp_path / "workspace-project" / ".env").read_text(encoding="utf-8")
    assert "MAESTRO_PROJECT_SLUG=tower-a" in env_text


def test_set_project_telegram_updates_account_without_invalid_metadata_keys(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "home" / ".openclaw" / "openclaw.json"
    config = {
        "channels": {
            "telegram": {
                "enabled": True,
                "accounts": {},
            }
        },
        "bindings": [],
    }
    _write_json(config_path, config)
    _write_json(
        tmp_path / "store" / "tower-a" / "project.json",
        {
            "name": "Tower A",
            "slug": "tower-a",
        },
    )

    monkeypatch.setattr(fleet_models, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))
    monkeypatch.setattr(fleet_models, "resolve_fleet_store_root", lambda _store: tmp_path / "store")
    monkeypatch.setattr(
        fleet_models,
        "_validate_telegram_token",
        lambda _token: (True, "project_level_fleet_bot", "Fleet Project Bot", "ok"),
    )
    monkeypatch.setattr(
        fleet_models,
        "ensure_openclaw_override_allowed",
        lambda _config, allow_override=False: (True, ""),
    )
    monkeypatch.setattr(fleet_models, "_restart_openclaw_gateway", lambda: (True, "ok"))

    code = fleet_models.run_set_project_telegram(
        project="tower-a",
        telegram_token="123456:ABCDEF",
        skip_remote_validation=False,
    )

    assert code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    account = saved["channels"]["telegram"]["accounts"]["maestro-project-tower-a"]
    assert set(account.keys()) == {"botToken", "dmPolicy", "groupPolicy", "streamMode"}
    assert account["botToken"] == "123456:ABCDEF"
    project_payload = json.loads((tmp_path / "store" / "tower-a" / "project.json").read_text(encoding="utf-8"))
    assert project_payload["maestro"]["telegram_bot_username"] == "project_level_fleet_bot"
    assert project_payload["maestro"]["telegram_bot_display_name"] == "Fleet Project Bot"


def test_fleet_model_catalog_normalizes_legacy_defaults():
    assert canonicalize_model("openai/gpt-5.2") == "openai/gpt-5.4"
    assert canonicalize_model("google/gemini-3-pro-preview") == "google/gemini-3.1-pro-preview"
    assert format_model_display("google/gemini-3-pro-preview") == (
        "Google Gemini 3.1 Pro (google/gemini-3.1-pro-preview)"
    )


def test_fleet_model_gateway_restart_installs_when_start_reports_service_not_loaded(monkeypatch):
    calls: list[list[str]] = []
    status_payloads = iter([
        {"service": {"loaded": False, "runtime": {"status": "unknown"}}, "rpc": {"ok": False}, "port": {"status": "free", "listeners": []}},
        {"service": {"loaded": False, "runtime": {"status": "unknown"}}, "rpc": {"ok": False}, "port": {"status": "free", "listeners": []}},
        {"service": {"loaded": False, "runtime": {"status": "unknown"}}, "rpc": {"ok": False}, "port": {"status": "free", "listeners": []}},
        {"service": {"loaded": True, "runtime": {"status": "running"}}, "rpc": {"ok": True}, "port": {"status": "busy", "listeners": [{"pid": 123}]}},
    ])

    monkeypatch.setattr(fleet_models, "prepend_openclaw_profile_args", lambda args, default_profile="": args)

    def _fake_run(args, **kwargs):
        command = list(args)
        calls.append(command)
        if command[-3:] == ["gateway", "status", "--json"]:
            payload = next(status_payloads)
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        if command[-2:] == ["gateway", "restart"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="restart failed")
        if command[-2:] == ["gateway", "start"]:
            if sum(1 for item in calls if item[-2:] == ["gateway", "start"]) == 1:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="Gateway service not loaded.\nStart with: openclaw --profile maestro-fleet gateway install",
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="Gateway started", stderr="")
        if "install" in command:
            return subprocess.CompletedProcess(command, 0, stdout="Gateway installed", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(fleet_models.subprocess, "run", _fake_run)

    ok, detail = fleet_models._restart_openclaw_gateway()

    assert ok is True
    assert "Gateway installed" in detail


def test_fleet_model_gateway_restart_defaults_to_fleet_profile(monkeypatch):
    observed_profiles: list[str] = []

    monkeypatch.setattr(
        fleet_models,
        "prepend_openclaw_profile_args",
        lambda args, default_profile="": observed_profiles.append(default_profile) or args,
    )

    running_status = {
        "service": {"loaded": True, "runtime": {"status": "running"}},
        "rpc": {"ok": True},
        "port": {"status": "busy", "listeners": [{"pid": 123}]},
    }

    monkeypatch.setattr(
        fleet_models.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=json.dumps(running_status), stderr=""),
    )

    ok, _detail = fleet_models._restart_openclaw_gateway()

    assert ok is True
    assert observed_profiles
    assert all(profile == fleet_models.FLEET_PROFILE for profile in observed_profiles)
