"""Tests for fleet model-switch operations."""

from __future__ import annotations

import json
from pathlib import Path

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
                    "model": "openai/gpt-5.2",
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
                    "model": "openai/gpt-5.2",
                    "workspace": str(tmp_path / "workspace-project"),
                },
            ]
        },
    }
    _write_json(config_path, config)
    monkeypatch.setattr(fleet_models, "_load_openclaw_config", lambda *args, **kwargs: (config, config_path))
    monkeypatch.setattr(fleet_models, "_restart_openclaw_gateway", lambda: (True, "ok"))
    monkeypatch.setattr(fleet_models, "resolve_fleet_store_root", lambda _store: tmp_path / "store")
    monkeypatch.setattr(
        fleet_models,
        "sync_fleet_registry",
        lambda _store: {
            "projects": [
                {
                    "project_slug": "tower-a",
                    "project_name": "Tower A",
                    "project_store_path": str(tmp_path / "store" / "tower-a"),
                }
            ]
        },
    )

    code = fleet_models.run_set_project_model(
        project="tower-a",
        model="openai/gpt-5.2",
        api_key="sk-test-openai",
        skip_remote_validation=True,
    )
    assert code == 0

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    project_agent = next(item for item in saved["agents"]["list"] if item.get("id") == "maestro-project-tower-a")
    assert project_agent["model"] == "openai/gpt-5.2"
    assert saved["env"]["OPENAI_API_KEY"] == "sk-test-openai"
