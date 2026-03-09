"""Tests for Maestro CLI parser wiring."""

from __future__ import annotations

import argparse

import pytest

from maestro.cli import _handle_ingest, _run_fleet, build_parser
from maestro.profile import PROFILE_FLEET


def test_setup_parser_mode():
    parser = build_parser()
    args = parser.parse_args(["setup"])
    assert args.mode == "setup"


def test_ingest_parser_accepts_new_project_name():
    parser = build_parser()
    args = parser.parse_args(["ingest", "/tmp/pdfs", "--new-project-name", "Project B"])
    assert args.mode == "ingest"
    assert args.folder == "/tmp/pdfs"
    assert args.new_project_name == "Project B"


def test_fleet_enable_parser():
    parser = build_parser()
    args = parser.parse_args(["fleet", "enable", "--dry-run"])
    assert args.mode == "fleet"
    assert args.fleet_command == "enable"
    assert args.dry_run is True


def test_fleet_project_create_parser():
    parser = build_parser()
    args = parser.parse_args([
        "fleet",
        "project",
        "create",
        "--project-name",
        "Test Project",
        "--assignee",
        "Andy",
        "--non-interactive",
    ])
    assert args.mode == "fleet"
    assert args.fleet_command == "project"
    assert args.fleet_project_command == "create"
    assert args.project_name == "Test Project"
    assert args.assignee == "Andy"
    assert args.non_interactive is True


def test_fleet_project_set_model_parser():
    parser = build_parser()
    args = parser.parse_args([
        "fleet",
        "project",
        "set-model",
        "--project",
        "tower-a",
        "--model",
        "anthropic/claude-opus-4-6",
        "--skip-remote-validation",
    ])
    assert args.mode == "fleet"
    assert args.fleet_command == "project"
    assert args.fleet_project_command == "set-model"
    assert args.project == "tower-a"
    assert args.model == "anthropic/claude-opus-4-6"
    assert args.skip_remote_validation is True


def test_fleet_commander_set_model_parser():
    parser = build_parser()
    args = parser.parse_args([
        "fleet",
        "commander",
        "set-model",
        "--model",
        "openai/gpt-5.4",
    ])
    assert args.mode == "fleet"
    assert args.fleet_command == "commander"
    assert args.fleet_commander_command == "set-model"
    assert args.model == "openai/gpt-5.4"


def test_fleet_license_command_is_disabled(capsys):
    parser = build_parser()
    args = parser.parse_args(["fleet", "license"])
    with pytest.raises(SystemExit) as exc:
        _run_fleet(args)
    assert int(exc.value.code) == 1
    captured = capsys.readouterr()
    assert "no longer uses license generation" in captured.out


def test_fleet_purchase_command_is_disabled(capsys):
    import os

    os.environ.pop("MAESTRO_OPENCLAW_PROFILE", None)
    parser = build_parser()
    args = parser.parse_args(["fleet", "purchase"])
    with pytest.raises(SystemExit) as exc:
        _run_fleet(args)
    assert int(exc.value.code) == 1
    assert os.environ.get("MAESTRO_OPENCLAW_PROFILE") == "maestro-fleet"
    captured = capsys.readouterr()
    assert "disabled" in captured.out


def test_run_fleet_project_create_uses_package_owner(monkeypatch):
    parser = build_parser()
    args = parser.parse_args([
        "fleet",
        "project",
        "create",
        "--project-name",
        "ACME Tower",
        "--assignee",
        "Sean",
        "--dry-run",
    ])

    observed: dict[str, object] = {}

    monkeypatch.setattr("maestro_fleet.provisioning.run_project_create", lambda **kwargs: (observed.setdefault("kwargs", kwargs), 0)[1])
    monkeypatch.setattr("maestro.cli.fleet_enabled", lambda: True)

    _run_fleet(args)

    assert observed["kwargs"] == {
        "project_name": "ACME Tower",
        "assignee": "Sean",
        "superintendent": None,
        "model": None,
        "api_key": None,
        "telegram_token": None,
        "pairing_code": None,
        "store_override": None,
        "dry_run": True,
        "json_output": False,
        "non_interactive": False,
        "skip_remote_validation": False,
        "allow_openclaw_override": False,
    }


def test_run_fleet_enable_uses_package_update_and_doctor(monkeypatch, capsys):
    parser = build_parser()
    args = parser.parse_args(["fleet", "enable", "--no-restart"])

    observed: dict[str, object] = {}

    monkeypatch.setattr("maestro_fleet.update.run_update", lambda **kwargs: (observed.setdefault("update", kwargs), 0)[1])
    monkeypatch.setattr("maestro_fleet.doctor.run_doctor", lambda **kwargs: (observed.setdefault("doctor", kwargs), 0)[1])
    monkeypatch.setattr("maestro.cli.set_profile", lambda profile, fleet=False: {"profile": profile, "fleet_enabled": fleet})
    monkeypatch.setattr(
        "maestro.control_plane.resolve_network_urls",
        lambda web_port=3000: {"recommended_url": f"http://localhost:{web_port}/command-center"},
    )

    _run_fleet(args)

    assert observed["update"] == {"restart_gateway": False, "dry_run": False}
    assert observed["doctor"] == {"fix": True, "restart_gateway": False, "json_output": False}
    captured = capsys.readouterr()
    assert "Fleet profile enabled" in captured.out


def test_fleet_deploy_parser():
    parser = build_parser()
    args = parser.parse_args([
        "fleet",
        "deploy",
        "--company-name",
        "ACME",
        "--commander-model",
        "anthropic/claude-opus-4-6",
        "--project-model",
        "openai/gpt-5.4",
        "--gemini-api-key",
        "AIzaGeminiTestKey000000000000000000000",
        "--openai-api-key",
        "sk-test-openai",
        "--anthropic-api-key",
        "sk-ant-test",
        "--project-name",
        "Tower A",
        "--assignee",
        "Sean",
        "--commander-pairing-code",
        "PAIR-1234",
        "--project-telegram-token",
        "123:abc",
        "--non-interactive",
    ])
    assert args.mode == "fleet"
    assert args.fleet_command == "deploy"
    assert args.company_name == "ACME"
    assert args.commander_model == "anthropic/claude-opus-4-6"
    assert args.project_model == "openai/gpt-5.4"
    assert args.commander_pairing_code == "PAIR-1234"
    assert args.gemini_api_key.startswith("AIza")
    assert args.project_name == "Tower A"
    assert args.provision_initial_project is False
    assert args.non_interactive is True


def test_fleet_deploy_parser_accepts_initial_project_opt_in():
    parser = build_parser()
    args = parser.parse_args([
        "fleet",
        "deploy",
        "--company-name",
        "ACME",
        "--provision-initial-project",
        "--project-name",
        "Tower A",
        "--assignee",
        "Sean",
    ])
    assert args.mode == "fleet"
    assert args.fleet_command == "deploy"
    assert args.provision_initial_project is True
    assert args.project_name == "Tower A"


def test_up_parser_accepts_tui_flag():
    parser = build_parser()
    args = parser.parse_args(["up", "--tui", "--field-access-required", "--store", "/tmp/ks"])
    assert args.mode == "up"
    assert args.tui is True
    assert args.field_access_required is True
    assert args.store == "/tmp/ks"


def test_doctor_parser_fix_and_json_flags():
    parser = build_parser()
    args = parser.parse_args(["doctor", "--fix", "--json"])
    assert args.mode == "doctor"
    assert args.fix is True
    assert args.json is True


def test_doctor_parser_field_access_required_flag():
    parser = build_parser()
    args = parser.parse_args(["doctor", "--field-access-required"])
    assert args.mode == "doctor"
    assert args.field_access_required is True


def test_handle_ingest_uses_desktop_store_in_fleet_mode(monkeypatch, tmp_path):
    import maestro.cli as cli
    import maestro.ingest as ingest_module

    folder = tmp_path / "plans"
    folder.mkdir()
    desktop_store = tmp_path / "home" / "Desktop" / "knowledge_store"
    captured: dict[str, object] = {}
    updates: list[dict[str, str]] = []

    def fake_ingest(folder_path: str, project_name: str | None, dpi: int, store_path: str):
        captured["folder_path"] = folder_path
        captured["project_name"] = project_name
        captured["dpi"] = dpi
        captured["store_path"] = store_path

    monkeypatch.setattr(ingest_module, "ingest", fake_ingest)
    monkeypatch.setattr(cli, "resolve_profile", lambda: PROFILE_FLEET)
    monkeypatch.setattr(cli, "resolve_desktop_store_root", lambda: desktop_store)
    monkeypatch.setattr(cli, "update_install_state", lambda payload: updates.append(payload) or payload)

    _handle_ingest(
        argparse.Namespace(
            folder=str(folder),
            project_name=None,
            new_project_name=None,
            dpi=200,
            store=None,
        )
    )

    assert captured["folder_path"] == str(folder)
    assert captured["store_path"] == str(desktop_store)
    assert updates == [{"store_root": str(desktop_store), "fleet_store_root": str(desktop_store)}]


def test_tools_schedule_upsert_parser():
    parser = build_parser()
    args = parser.parse_args([
        "tools",
        "upsert_schedule_item",
        "milestone_podium_pour",
        "--title", "Podium pour",
        "--type", "milestone",
        "--status", "pending",
        "--due-date", "2026-03-01",
    ])
    assert args.mode == "tools"
    assert args.command == "upsert_schedule_item"
    assert args.item_id == "milestone_podium_pour"
    assert args.item_type == "milestone"
    assert args.status == "pending"
    assert args.due_date == "2026-03-01"


def test_tools_schedule_constraint_parser():
    parser = build_parser()
    args = parser.parse_args([
        "tools",
        "set_schedule_constraint",
        "constraint_rfi_012",
        "RFI-012 response needed",
        "--activity-id", "A1100",
        "--status", "blocked",
    ])
    assert args.mode == "tools"
    assert args.command == "set_schedule_constraint"
    assert args.constraint_id == "constraint_rfi_012"
    assert args.description == "RFI-012 response needed"
    assert args.activity_id == "A1100"
    assert args.status == "blocked"
