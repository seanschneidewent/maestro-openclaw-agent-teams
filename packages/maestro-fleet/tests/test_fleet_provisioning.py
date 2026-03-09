from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

import maestro_fleet.provisioning as provisioning


def _write_json(path: Path, data: dict) -> None:
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


def test_run_project_create_is_package_owned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    store_root.mkdir(parents=True, exist_ok=True)
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "maestro.fleet.projects.provisioning.run_project_create",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy run_project_create should not be called")),
    )
    monkeypatch.setattr(provisioning, "_load_openclaw_config", lambda: (config, config_path))
    monkeypatch.setattr(provisioning, "resolve_fleet_store_root", lambda *_args, **_kwargs: store_root)
    monkeypatch.setattr(provisioning, "_current_command_center_url", lambda *args, **kwargs: "http://localhost:3000/command-center")
    monkeypatch.setattr(provisioning, "_restart_openclaw_gateway", lambda **kwargs: {"ok": True, "detail": "ok"})
    monkeypatch.setattr(provisioning, "_complete_telegram_pairing", lambda **kwargs: {"approved": True})
    monkeypatch.setattr(provisioning, "project_control_payload", lambda *args, **kwargs: {"ingest": {"command": "maestro ingest"}})

    def _fake_create_project_node(**kwargs):
        observed["create_kwargs"] = kwargs
        project_store = store_root / "alpha-build"
        project_store.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "project": {"project_store_path": str(project_store)},
            "agent_registration": {"workspace": str(workspace / "projects" / "alpha-build")},
        }

    def _fake_update_openclaw_for_project(**kwargs):
        observed["update_kwargs"] = kwargs
        return {
            "agent_id": "maestro-project-alpha-build",
            "workspace_env_written": True,
            "metadata_written": True,
            "binding_changes": [],
        }

    monkeypatch.setattr(provisioning, "create_project_node", _fake_create_project_node)
    monkeypatch.setattr(provisioning, "_update_openclaw_for_project", _fake_update_openclaw_for_project)

    code = provisioning.run_project_create(
        project_name="Alpha Build",
        assignee="Andy",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=False,
        json_output=True,
        skip_remote_validation=True,
    )

    assert code == 0
    create_kwargs = observed["create_kwargs"]
    assert isinstance(create_kwargs, dict)
    assert create_kwargs["project_slug"] == "alpha-build"
    assert create_kwargs["register_agent"] is True
    update_kwargs = observed["update_kwargs"]
    assert isinstance(update_kwargs, dict)
    assert Path(str(update_kwargs["project_store_path"])).name == "alpha-build"
    assert Path(str(update_kwargs["project_workspace"])).name == "alpha-build"


def test_run_project_create_rejects_single_project_fleet_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    _write_json(store_root / "project.json", {"name": "Alpha Build", "slug": "alpha-build"})

    monkeypatch.setattr(provisioning, "_load_openclaw_config", lambda: (config, config_path))
    monkeypatch.setattr(provisioning, "resolve_fleet_store_root", lambda *_args, **_kwargs: store_root)
    monkeypatch.setattr(provisioning, "create_project_node", lambda **kwargs: (_ for _ in ()).throw(AssertionError("create_project_node should not be called")))

    console = Console(record=True)
    monkeypatch.setattr(
        provisioning,
        "_legacy_provisioning_module",
        lambda: type("LegacyProvisioning", (), {
            "console": console,
            "ensure_openclaw_override_allowed": staticmethod(lambda config, allow_override=False: (True, "")),
            "_resolve_company_agent": staticmethod(lambda config: config["agents"]["list"][0]),
            "slugify": staticmethod(lambda value: "alpha-build"),
            "provider_env_key_for_model": staticmethod(lambda model: "OPENAI_API_KEY"),
            "PROJECT_MODEL_OPTIONS": (("1", "inherit"), ("2", "openai/gpt-5.4")),
            "MODEL_LABELS": {},
            "Prompt": type("Prompt", (), {"ask": staticmethod(lambda *args, **kwargs: "")}),
            "Confirm": type("Confirm", (), {"ask": staticmethod(lambda *args, **kwargs: True)}),
            "Panel": object,
            "openclaw_workspace_root": staticmethod(lambda **kwargs: workspace),
        })(),
    )

    code = provisioning.run_project_create(
        project_name="Alpha Build",
        assignee="Andy",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=False,
        skip_remote_validation=True,
    )

    assert code == 1
    output = console.export_text()
    assert "Fleet store root cannot be a single-project store" in output
    assert "parent directory" in output
    assert "project folders" in output
