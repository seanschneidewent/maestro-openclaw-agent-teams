from __future__ import annotations

import json
from pathlib import Path

import maestro.doctor as legacy_doctor
import maestro_fleet.doctor as fleet_doctor


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_fleet_doctor_report_uses_derived_registry(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    state_root = home / ".openclaw-maestro-fleet"
    workspace = state_root / "workspace-maestro"
    store_root = tmp_path / "store"
    project_store = store_root / "alpha-project"

    _write_json(
        state_root / "openclaw.json",
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
                        "id": "maestro-project-alpha-project",
                        "name": "Maestro (Alpha Project)",
                        "default": False,
                        "model": "openai/gpt-5.2",
                        "workspace": str(workspace / "projects" / "alpha-project"),
                    },
                ]
            },
        },
    )
    (workspace / ".env").parent.mkdir(parents=True, exist_ok=True)
    (workspace / ".env").write_text(f"MAESTRO_STORE={store_root}\nMAESTRO_AGENT_ROLE=company\n", encoding="utf-8")
    project_workspace = workspace / "projects" / "alpha-project"
    project_workspace.mkdir(parents=True, exist_ok=True)
    (project_workspace / ".env").write_text(
        f"MAESTRO_STORE={project_store}\nMAESTRO_AGENT_ROLE=project\nMAESTRO_PROJECT_SLUG=alpha-project\n",
        encoding="utf-8",
    )
    _write_json(project_store / "project.json", {"name": "Alpha Project", "slug": "alpha-project"})

    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        if args[:2] == ["openclaw", "status"]:
            return True, "gateway service running"
        if args[:3] == ["openclaw", "devices", "list"]:
            return True, '{"pending":[],"paired":[]}'
        if args[:4] == ["openclaw", "gateway", "status", "--json"]:
            return True, json.dumps(
                {
                    "service": {"runtime": {"status": "running"}},
                    "rpc": {"ok": True},
                    "port": {"status": "busy", "listeners": [{"pid": 1234}]},
                }
            )
        return True, ""

    monkeypatch.setattr(legacy_doctor, "_run_cmd", _fake_run_cmd)

    report = fleet_doctor.build_doctor_report(
        fix=False,
        store_override=str(store_root),
        restart_gateway=False,
        home_dir=home,
    )

    checks = report.get("checks", [])
    registry_projects = next(
        (item for item in checks if isinstance(item, dict) and item.get("name") == "registry_projects"),
        {},
    )
    assert registry_projects.get("ok") is True
    assert registry_projects.get("detail") == "1 active project maestro(s) registered"
    assert not (store_root / ".command_center" / "fleet_registry.json").exists()


def test_fleet_doctor_flags_single_project_company_store(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    state_root = home / ".openclaw-maestro-fleet"
    workspace = state_root / "workspace-maestro"
    store_root = tmp_path / "single-project-store"

    _write_json(
        state_root / "openclaw.json",
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
    (workspace / ".env").write_text(f"MAESTRO_STORE={store_root}\nMAESTRO_AGENT_ROLE=company\n", encoding="utf-8")
    _write_json(store_root / "project.json", {"name": "Alpha Project", "slug": "alpha-project"})

    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    monkeypatch.setattr(legacy_doctor, "_run_cmd", lambda *args, **kwargs: (True, ""))

    report = fleet_doctor.build_doctor_report(
        fix=False,
        store_override=str(store_root),
        restart_gateway=False,
        home_dir=home,
    )

    checks = report.get("checks", [])
    layout = next(
        (item for item in checks if isinstance(item, dict) and item.get("name") == "fleet_store_layout"),
        {},
    )
    assert layout.get("ok") is False
    assert "single-project store" in str(layout.get("detail", ""))


def test_fleet_doctor_can_skip_runtime_checks(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    state_root = home / ".openclaw-maestro-fleet"
    workspace = state_root / "workspace-maestro"
    store_root = tmp_path / "store"

    _write_json(
        state_root / "openclaw.json",
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
        f"MAESTRO_STORE={store_root}\nMAESTRO_AGENT_ROLE=company\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    monkeypatch.setattr(legacy_doctor, "_run_cmd", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runtime checks should be skipped")))

    report = fleet_doctor.build_doctor_report(
        fix=True,
        store_override=str(store_root),
        restart_gateway=True,
        runtime_checks=False,
        home_dir=home,
    )

    checks = report.get("checks", [])
    names = {item.get("name") for item in checks if isinstance(item, dict)}
    assert "gateway_auth_tokens" in names
    assert "launchagent_env_sync" not in names
    assert "gateway_restart" not in names
    assert "cli_device_pairing" not in names
    assert "gateway_running" not in names
