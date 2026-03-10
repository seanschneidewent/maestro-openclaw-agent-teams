"""Tests for Fleet project provisioning workflow."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import maestro.fleet.projects.provisioning as purchase


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _base_config(workspace: Path) -> dict:
    return {
        "env": {"OPENAI_API_KEY": "sk-test-openai-key"},
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
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }


@pytest.fixture(autouse=True)
def _clear_openclaw_profile_env(monkeypatch):
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)


def test_validate_api_key_accepts_vertex_api_key_on_gemini_403(monkeypatch):
    class _Response:
        def __init__(self, status_code: int):
            self.status_code = status_code

    monkeypatch.setattr(
        purchase.httpx,
        "get",
        lambda *args, **kwargs: _Response(403),
    )

    ok, detail = purchase._validate_api_key("GEMINI_API_KEY", "AIza" + ("A" * 35))
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

    monkeypatch.setattr(purchase.httpx, "get", _fake_get)

    ok, detail = purchase._validate_api_key("GEMINI_API_KEY", "ya29.test-vertex-token")
    assert ok is True
    assert "Vertex token status=200" in detail


def test_validate_api_key_accepts_vertex_api_key_via_aiplatform_probe(monkeypatch):
    class _Response:
        def __init__(self, status_code: int):
            self.status_code = status_code

    monkeypatch.setattr(
        purchase.httpx,
        "get",
        lambda *args, **kwargs: _Response(401),
    )
    monkeypatch.setattr(
        purchase.httpx,
        "post",
        lambda *args, **kwargs: _Response(200),
    )

    ok, detail = purchase._validate_api_key("GEMINI_API_KEY", "AQ.Afakeyvertexstyletoken")
    assert ok is True
    assert "Vertex status=200" in detail


def test_project_model_options_include_openai_gpt_5_4():
    assert ("2", "openai/gpt-5.4") in purchase.PROJECT_MODEL_OPTIONS


def test_run_purchase_non_interactive_dry_run(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    store_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        purchase,
        "_load_openclaw_config",
        lambda: (config, config_path),
    )
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)

    code = purchase.run_purchase(
        project_name="Alpha Build",
        assignee="Mike",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=True,
        skip_remote_validation=True,
    )

    assert code == 0
    assert not (store_root / "alpha-build").exists()


def test_run_purchase_warns_as_deprecated_alias(monkeypatch):
    monkeypatch.setattr(purchase, "run_project_create", lambda *args, **kwargs: 7)
    monkeypatch.setattr(purchase, "_RUN_PURCHASE_DEPRECATED_WARNED", False)

    with pytest.deprecated_call(match=r"run_purchase\(\) is deprecated"):
        code = purchase.run_purchase(project_name="Alpha Build")

    assert code == 7


def test_root_run_project_create_delegates_to_package_owner(monkeypatch):
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "maestro_fleet.provisioning.run_project_create",
        lambda **kwargs: (observed.setdefault("kwargs", kwargs), 0)[1],
    )

    code = purchase.run_project_create(
        project_name="Alpha Build",
        assignee="Andy",
        telegram_token="123456:ABCDEF",
        dry_run=True,
        non_interactive=True,
    )

    assert code == 0
    assert observed["kwargs"] == {
        "project_name": "Alpha Build",
        "assignee": "Andy",
        "superintendent": None,
        "model": None,
        "api_key": None,
        "telegram_token": "123456:ABCDEF",
        "pairing_code": None,
        "store_override": None,
        "dry_run": True,
        "json_output": False,
        "non_interactive": True,
        "skip_remote_validation": False,
        "allow_openclaw_override": False,
    }


def test_run_purchase_has_no_payment_gate_after_free_slot(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    existing = store_root / "existing-project"
    existing.mkdir(parents=True, exist_ok=True)
    _write_json(existing / "project.json", {"name": "Existing Project", "slug": "existing-project"})

    monkeypatch.setattr(
        purchase,
        "_load_openclaw_config",
        lambda: (config, config_path),
    )
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    code = purchase.run_purchase(
        project_name="Second Project",
        assignee="Sarah",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=True,
        skip_remote_validation=True,
    )
    assert code == 0


def test_run_purchase_allows_multiple_projects_without_license_activation(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    existing = store_root / "existing-project"
    existing.mkdir(parents=True, exist_ok=True)
    _write_json(existing / "project.json", {"name": "Existing Project", "slug": "existing-project"})

    monkeypatch.setattr(
        purchase,
        "_load_openclaw_config",
        lambda: (config, config_path),
    )
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    code = purchase.run_purchase(
        project_name="Second Project",
        assignee="Sarah",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=True,
        skip_remote_validation=True,
    )
    assert code == 0


def test_run_purchase_preserves_registered_project_agent(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    store_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(purchase.Path, "home", staticmethod(lambda: home))

    def _fake_create_project_node(**kwargs):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        agents = payload.setdefault("agents", {}).setdefault("list", [])
        agents.append({
            "id": "maestro-project-alpha-build",
            "name": "Maestro (Alpha Build)",
            "default": False,
            "model": "openai/gpt-5.2",
            "workspace": str(workspace / "projects" / "alpha-build"),
        })
        config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (store_root / "alpha-build").mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "project": {"project_store_path": str(store_root / "alpha-build")},
            "agent_registration": {"workspace": str(workspace / "projects" / "alpha-build")},
        }

    monkeypatch.setattr(purchase, "create_project_node", _fake_create_project_node)
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    monkeypatch.setattr(purchase, "project_control_payload", lambda *args, **kwargs: {"ingest": {"command": "maestro ingest"}})
    monkeypatch.setattr(purchase, "_restart_openclaw_gateway", lambda **kwargs: {"ok": True, "detail": "ok"})
    monkeypatch.setattr(purchase, "_validate_api_key", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(purchase, "_validate_telegram_token", lambda *args, **kwargs: (True, "alpha_bot", "ok"))

    code = purchase.run_purchase(
        project_name="Alpha Build",
        assignee="Andy",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=False,
        skip_remote_validation=True,
    )
    assert code == 0

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    agent_ids = [a.get("id") for a in saved.get("agents", {}).get("list", []) if isinstance(a, dict)]
    assert "maestro-company" in agent_ids
    assert "maestro-project-alpha-build" in agent_ids
    assert "maestro-project-alpha-build" in saved.get("channels", {}).get("telegram", {}).get("accounts", {})
    project_account = saved.get("channels", {}).get("telegram", {}).get("accounts", {}).get("maestro-project-alpha-build", {})
    assert set(project_account.keys()) == {"botToken", "dmPolicy", "groupPolicy", "streamMode"}
    bindings = saved.get("bindings", [])
    assert {
        "agentId": "maestro-project-alpha-build",
        "match": {"channel": "telegram", "accountId": "maestro-project-alpha-build"},
    } in bindings


def test_update_openclaw_for_project_writes_project_metadata_to_store(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "openclaw.json"
    project_workspace = tmp_path / "workspace" / "projects" / "alpha-build"
    project_store = tmp_path / "store" / "alpha-build"
    config = _base_config(tmp_path / "workspace")
    _write_json(project_store / "project.json", {"name": "Alpha Build", "slug": "alpha-build"})

    monkeypatch.setattr(
        purchase,
        "resolve_network_urls",
        lambda **kwargs: {
            "recommended_url": "http://localhost:3000/alpha-build/",
            "localhost_url": "http://localhost:3000/alpha-build/",
            "tailnet_url": "",
        },
    )
    monkeypatch.setattr(purchase, "_current_command_center_port", lambda default_port=3000: 3000)

    result = purchase._update_openclaw_for_project(
        config=config,
        config_path=config_path,
        project_slug="alpha-build",
        project_name="Alpha Build",
        model="openai/gpt-5.2",
        provider_env_key="OPENAI_API_KEY",
        provider_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        telegram_bot_username="alpha_bot",
        telegram_bot_display_name="Alpha Bot",
        assignee="Andy",
        project_workspace=project_workspace,
        project_store_path=project_store,
        dry_run=False,
    )

    assert result["workspace_env_written"] is True
    env_text = (project_workspace / ".env").read_text(encoding="utf-8")
    assert "MAESTRO_PROJECT_SLUG=alpha-build" in env_text
    assert not (project_workspace / "project_agent.json").exists()

    payload = json.loads((project_store / "project.json").read_text(encoding="utf-8"))
    maestro_meta = payload.get("maestro", {})
    assert maestro_meta["project_slug"] == "alpha-build"
    assert maestro_meta["project_name"] == "Alpha Build"
    assert maestro_meta["assignee"] == "Andy"
    assert maestro_meta["model"] == "openai/gpt-5.2"
    assert maestro_meta["telegram_bot_username"] == "alpha_bot"


def test_current_command_center_url_prefers_active_fleet_port(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    state_dir = home / ".maestro" / "fleet"
    _write_json(state_dir / "serve.pid.json", {"pid": 123, "port": 3401})
    monkeypatch.setattr(purchase.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(
        purchase,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {"recommended_url": f"http://localhost:{web_port}{route_path}"},
    )

    assert purchase._current_command_center_url() == "http://localhost:3401/command-center"


def test_run_purchase_json_reports_active_command_center_url(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)
    _write_json(home / ".maestro" / "fleet" / "serve.pid.json", {"pid": 123, "port": 3401})

    store_root = tmp_path / "store-root"
    store_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(purchase.Path, "home", staticmethod(lambda: home))
    def _fake_create_project_node(**kwargs):
        project_store = store_root / "alpha-build"
        project_store.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "project": {"project_store_path": str(project_store)},
            "agent_registration": {"workspace": str(workspace / "projects" / "alpha-build")},
        }

    monkeypatch.setattr(purchase, "create_project_node", _fake_create_project_node)
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    monkeypatch.setattr(
        purchase,
        "resolve_network_urls",
        lambda web_port, route_path="/command-center": {"recommended_url": f"http://localhost:{web_port}{route_path}"},
    )
    monkeypatch.setattr(purchase, "project_control_payload", lambda *args, **kwargs: {"ingest": {"command": "maestro ingest"}})
    monkeypatch.setattr(purchase, "_restart_openclaw_gateway", lambda **kwargs: {"ok": True, "detail": "ok"})
    monkeypatch.setattr(purchase, "_validate_api_key", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(purchase, "_validate_telegram_token", lambda *args, **kwargs: (True, "alpha_bot", "ok"))

    captured: dict[str, object] = {}

    def _capture_print_json(payload: str):
        captured["payload"] = json.loads(payload)

    monkeypatch.setattr(purchase.console, "print_json", _capture_print_json)

    code = purchase.run_purchase(
        project_name="Alpha Build",
        assignee="Andy",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=False,
        json_output=True,
        skip_remote_validation=True,
    )
    assert code == 0
    assert captured["payload"]["command_center_url"] == "http://localhost:3401/command-center"


def test_restart_openclaw_gateway_installs_when_start_reports_service_not_loaded(monkeypatch):
    calls: list[list[str]] = []
    status_payloads = iter([
        {"service": {"loaded": False, "runtime": {"status": "unknown"}}, "rpc": {"ok": False}, "port": {"status": "free", "listeners": []}},
        {"service": {"loaded": False, "runtime": {"status": "unknown"}}, "rpc": {"ok": False}, "port": {"status": "free", "listeners": []}},
        {"service": {"loaded": False, "runtime": {"status": "unknown"}}, "rpc": {"ok": False}, "port": {"status": "free", "listeners": []}},
        {"service": {"loaded": True, "runtime": {"status": "running"}}, "rpc": {"ok": True}, "port": {"status": "busy", "listeners": [{"pid": 123}]}},
    ])

    monkeypatch.setattr(purchase, "prepend_openclaw_profile_args", lambda args, default_profile="": args)

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

    monkeypatch.setattr(purchase.subprocess, "run", _fake_run)

    result = purchase._restart_openclaw_gateway(dry_run=False)

    assert result["ok"] is True
    assert any("install" in item for command in calls for item in command)


def test_restart_openclaw_gateway_defaults_to_fleet_profile(monkeypatch):
    observed_profiles: list[str] = []

    monkeypatch.setattr(
        purchase,
        "prepend_openclaw_profile_args",
        lambda args, default_profile="": observed_profiles.append(default_profile) or args,
    )

    running_status = {
        "service": {"loaded": True, "runtime": {"status": "running"}},
        "rpc": {"ok": True},
        "port": {"status": "busy", "listeners": [{"pid": 123}]},
    }

    monkeypatch.setattr(
        purchase.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=json.dumps(running_status), stderr=""),
    )

    result = purchase._restart_openclaw_gateway(dry_run=False)

    assert result["ok"] is True
    assert observed_profiles
    assert all(profile == purchase.FLEET_PROFILE for profile in observed_profiles)
