from __future__ import annotations

import os
from pathlib import Path

import pytest

from maestro_fleet import cli
from maestro_fleet import provisioning


def test_parser_has_fleet_surface():
    parser = cli.build_parser()
    args = parser.parse_args(["project", "create", "--project-name", "ACME Tower", "--dry-run"])
    assert args.command == "project"
    assert args.project_command == "create"
    assert args.project_name == "ACME Tower"
    assert args.dry_run is True


def test_forward_project_create_args():
    parser = cli.build_parser()
    args = parser.parse_args(["project", "create", "--project-name", "ACME Tower", "--dry-run"])
    forwarded = cli._to_legacy_argv(args)
    assert forwarded[:3] == ["fleet", "project", "create"]
    assert "--project-name" in forwarded
    assert "--dry-run" in forwarded


def test_forward_project_set_model_args():
    parser = cli.build_parser()
    args = parser.parse_args([
        "project",
        "set-model",
        "--project",
        "tower-a",
        "--model",
        "anthropic/claude-opus-4-6",
        "--skip-remote-validation",
    ])
    forwarded = cli._to_legacy_argv(args)
    assert forwarded[:3] == ["fleet", "project", "set-model"]
    assert "--project" in forwarded
    assert "--model" in forwarded
    assert "--skip-remote-validation" in forwarded


def test_forward_project_set_telegram_args():
    parser = cli.build_parser()
    args = parser.parse_args([
        "project",
        "set-telegram",
        "--project",
        "tower-a",
        "--telegram-token",
        "123:abc",
        "--pairing-code",
        "PAIR123",
        "--skip-remote-validation",
    ])
    forwarded = cli._to_legacy_argv(args)
    assert forwarded[:3] == ["fleet", "project", "set-telegram"]
    assert "--project" in forwarded
    assert "--telegram-token" in forwarded
    assert "--pairing-code" in forwarded
    assert "--skip-remote-validation" in forwarded


def test_forward_commander_set_model_args():
    parser = cli.build_parser()
    args = parser.parse_args([
        "commander",
        "set-model",
        "--model",
        "openai/gpt-5.4",
        "--api-key",
        "sk-test",
    ])
    forwarded = cli._to_legacy_argv(args)
    assert forwarded[:3] == ["fleet", "commander", "set-model"]
    assert "--model" in forwarded
    assert "--api-key" in forwarded


def test_forward_license_generate_args():
    parser = cli.build_parser()
    args = parser.parse_args(["license", "generate", "--project-name", "ACME Tower", "--expiry-days", "365"])
    forwarded = cli._to_legacy_argv(args)
    assert forwarded[:3] == ["fleet", "license", "generate"]
    assert "--project-name" in forwarded
    assert "--expiry-days" in forwarded


def test_forward_deploy_args():
    parser = cli.build_parser()
    args = parser.parse_args([
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
        "sk-openai",
        "--anthropic-api-key",
        "sk-ant",
        "--project-name",
        "Tower A",
        "--assignee",
        "Sean",
        "--project-telegram-token",
        "123:abc",
        "--provision-initial-project",
        "--local",
        "--non-interactive",
    ])
    forwarded = cli._to_legacy_argv(args)
    assert forwarded[:2] == ["fleet", "deploy"]
    assert "--company-name" in forwarded
    assert "--commander-model" in forwarded
    assert "--project-model" in forwarded
    assert "--project-name" in forwarded
    assert "--provision-initial-project" in forwarded
    assert "--local" in forwarded


def test_main_routes_up_tui_to_fleet_native_monitor(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_up_tui(args):
        observed["command"] = args.command
        observed["tui"] = args.tui
        return 0

    def _fail_legacy_import():
        raise AssertionError("legacy main should not be imported for `maestro-fleet up --tui`")

    monkeypatch.setattr(cli, "_run_fleet_up_tui", _fake_run_up_tui)
    monkeypatch.setattr(cli, "_import_legacy_main", _fail_legacy_import)

    code = cli.main(["up", "--tui", "--skip-doctor"])
    assert code == 0
    assert observed.get("command") == "up"
    assert observed.get("tui") is True


def test_main_non_tui_up_uses_package_native_runtime(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_up(args):
        observed["command"] = args.command
        observed["skip_doctor"] = args.skip_doctor
        return 0

    monkeypatch.setattr(cli, "_run_fleet_up", _fake_run_up)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet up`")),
    )

    code = cli.main(["up", "--skip-doctor"])
    assert code == 0
    assert observed.get("command") == "up"
    assert observed.get("skip_doctor") is True


def test_main_routes_serve_to_package_native_server(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_serve(args):
        observed["command"] = args.command
        return 0

    monkeypatch.setattr(cli, "_run_fleet_serve", _fake_run_serve)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet serve`")),
    )

    code = cli.main(["serve", "--port", "3300"])
    assert code == 0
    assert observed.get("command") == "serve"


def test_main_routes_doctor_to_package_native_doctor(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_doctor(args):
        observed["command"] = args.command
        return 0

    monkeypatch.setattr(cli, "_run_fleet_doctor", _fake_run_doctor)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet doctor`")),
    )

    code = cli.main(["doctor", "--fix"])
    assert code == 0
    assert observed.get("command") == "doctor"


def test_main_routes_project_create_to_package_native_provisioning(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_project_create(args):
        observed["project_name"] = args.project_name
        return 0

    monkeypatch.setattr(cli, "_run_fleet_project_create", _fake_run_project_create)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet project create`")),
    )

    code = cli.main(["project", "create", "--project-name", "ACME Tower", "--assignee", "Sean", "--dry-run"])
    assert code == 0
    assert observed.get("project_name") == "ACME Tower"


def test_run_purchase_warns_as_deprecated_alias(monkeypatch):
    monkeypatch.setattr(provisioning, "run_project_create", lambda *args, **kwargs: 9)
    monkeypatch.setattr(provisioning, "_RUN_PURCHASE_DEPRECATED_WARNED", False)

    with pytest.deprecated_call(match=r"run_purchase\(\) is deprecated"):
        code = provisioning.run_purchase(project_name="ACME Tower")

    assert code == 9


def test_main_routes_update_to_package_native_update(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_update(args):
        observed["dry_run"] = args.dry_run
        return 0

    monkeypatch.setattr(cli, "_run_fleet_update", _fake_run_update)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet update`")),
    )

    code = cli.main(["update", "--dry-run"])
    assert code == 0
    assert observed.get("dry_run") is True


def test_main_routes_enable_to_package_native_handler(monkeypatch):
    observed: dict[str, object] = {}
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)

    def _fake_run_enable(args):
        observed["dry_run"] = args.dry_run
        return 0

    monkeypatch.setattr(cli, "_run_fleet_enable", _fake_run_enable)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet enable`")),
    )

    code = cli.main(["enable", "--dry-run"])
    assert code == 0
    assert observed.get("dry_run") is True
    assert os.environ.get("MAESTRO_OPENCLAW_PROFILE") == "maestro-fleet"


def test_main_routes_status_to_package_native_handler(monkeypatch):
    observed: dict[str, object] = {}
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)

    def _fake_run_status(args):
        observed["command"] = args.command
        return 0

    monkeypatch.setattr(cli, "_run_fleet_status", _fake_run_status)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet status`")),
    )

    code = cli.main(["status"])
    assert code == 0
    assert observed.get("command") == "status"
    assert os.environ.get("MAESTRO_OPENCLAW_PROFILE") == "maestro-fleet"


def test_main_routes_command_center_to_package_native_handler(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_command_center(args):
        observed["open"] = args.open
        return 0

    monkeypatch.setattr(cli, "_run_fleet_command_center", _fake_run_command_center)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet command-center`")),
    )

    code = cli.main(["command-center", "--open"])
    assert code == 0
    assert observed.get("open") is True


def test_main_routes_deploy_to_package_native_handler(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_run_deploy(args):
        observed["company_name"] = args.company_name
        return 0

    monkeypatch.setattr(cli, "_run_fleet_deploy", _fake_run_deploy)
    monkeypatch.setattr(
        cli,
        "_import_legacy_main",
        lambda: (_ for _ in ()).throw(AssertionError("legacy main should not be imported for `maestro-fleet deploy`")),
    )

    code = cli.main(["deploy", "--company-name", "ACME"])
    assert code == 0
    assert observed.get("company_name") == "ACME"


def test_run_fleet_serve_calls_package_server_main(monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args(["serve", "--port", "3300", "--host", "127.0.0.1", "--store", "/tmp/fleet-store"])

    observed: dict[str, object] = {}

    import maestro_fleet.server as fleet_server

    def _fake_server_main(argv=None):
        observed["argv"] = argv
        return 0

    monkeypatch.setattr(fleet_server, "main", _fake_server_main)

    code = cli._run_fleet_serve(args)

    assert code == 0
    assert observed["argv"] == ["--port", "3300", "--host", "127.0.0.1", "--store", "/tmp/fleet-store"]


def test_run_fleet_project_create_calls_package_provisioning(monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args([
        "project",
        "create",
        "--project-name",
        "ACME Tower",
        "--assignee",
        "Sean",
        "--dry-run",
        "--json",
    ])

    observed: dict[str, object] = {}

    monkeypatch.setattr(
        cli.fleet_provisioning,
        "run_project_create",
        lambda **kwargs: (observed.setdefault("kwargs", kwargs), 0)[1],
    )

    code = cli._run_fleet_project_create(args)

    assert code == 0
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
        "json_output": True,
        "non_interactive": False,
        "skip_remote_validation": False,
        "allow_openclaw_override": False,
    }


def test_run_fleet_update_calls_package_update(monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args(["update", "--workspace", "/tmp/workspace", "--dry-run", "--no-restart"])

    observed: dict[str, object] = {}

    monkeypatch.setattr(
        cli.fleet_update,
        "run_update",
        lambda **kwargs: (observed.setdefault("kwargs", kwargs), 0)[1],
    )

    code = cli._run_fleet_update(args)

    assert code == 0
    assert observed["kwargs"] == {
        "workspace_override": "/tmp/workspace",
        "restart_gateway": False,
        "dry_run": True,
    }


def test_run_fleet_enable_calls_package_update_and_doctor(monkeypatch, capsys):
    parser = cli.build_parser()
    args = parser.parse_args(["enable", "--no-restart"])

    observed: dict[str, object] = {}

    def _fake_load_legacy_attr(module_name: str, attr: str):
        if (module_name, attr) == ("maestro.control_plane", "resolve_network_urls"):
            return lambda web_port=3000: {"recommended_url": f"http://localhost:{web_port}/command-center"}
        if (module_name, attr) == ("maestro.profile", "set_profile"):
            return lambda profile, fleet=False: {"profile": profile, "fleet_enabled": fleet}
        raise AssertionError(f"unexpected legacy attr load: {module_name}.{attr}")

    monkeypatch.setattr(cli, "_load_legacy_attr", _fake_load_legacy_attr)
    monkeypatch.setattr(
        cli.fleet_update,
        "run_update",
        lambda **kwargs: (observed.setdefault("update", kwargs), 0)[1],
    )
    monkeypatch.setattr(
        cli.fleet_doctor,
        "run_doctor",
        lambda **kwargs: (observed.setdefault("doctor", kwargs), 0)[1],
    )

    code = cli._run_fleet_enable(args)

    assert code == 0
    assert observed["update"] == {"restart_gateway": False, "dry_run": False}
    assert observed["doctor"] == {"fix": True, "restart_gateway": False, "json_output": False}
    captured = capsys.readouterr()
    assert "Fleet profile enabled" in captured.out


def test_run_fleet_up_tui_uses_package_native_store_resolution(monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args(["up", "--tui", "--host", "127.0.0.1"])

    observed: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "_ensure_runtime_modules_on_path",
        lambda: (_ for _ in ()).throw(AssertionError("legacy runtime path should not be required")),
    )
    monkeypatch.setattr(cli.fleet_state, "resolve_fleet_store_root", lambda store: Path("/tmp/fleet-store"))
    def _fake_run_doctor(**kwargs):
        observed["doctor"] = kwargs
        return 0

    monkeypatch.setattr(cli.fleet_doctor, "run_doctor", _fake_run_doctor)

    import maestro_fleet.monitor as fleet_monitor

    monkeypatch.setattr(
        fleet_monitor,
        "run_up_tui",
        lambda **kwargs: observed.setdefault("monitor", kwargs),
    )

    code = cli._run_fleet_up_tui(args)

    assert code == 0
    assert observed["doctor"] == {
        "fix": True,
        "store_override": "/tmp/fleet-store",
        "restart_gateway": True,
        "json_output": False,
        "field_access_required": False,
    }
    assert observed["monitor"] == {
        "port": 3000,
        "store": "/tmp/fleet-store",
        "host": "127.0.0.1",
    }
