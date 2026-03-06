from __future__ import annotations

import os

from maestro_fleet import cli


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
        "openai/gpt-5.2",
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
        "openai/gpt-5.2",
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


def test_main_non_tui_up_still_delegates_to_legacy(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_legacy(argv):
        observed["argv"] = argv
        return None

    monkeypatch.setattr(cli, "_import_legacy_main", lambda: _fake_legacy)

    code = cli.main(["up", "--skip-doctor"])
    assert code == 0
    assert observed.get("argv") == ["up", "--port", "3000", "--host", "0.0.0.0", "--skip-doctor"]


def test_main_sets_default_fleet_profile_env(monkeypatch):
    observed: dict[str, object] = {}
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)

    def _fake_legacy(argv):
        observed["argv"] = argv
        return None

    monkeypatch.setattr(cli, "_import_legacy_main", lambda: _fake_legacy)

    code = cli.main(["status"])
    assert code == 0
    assert observed.get("argv") == ["fleet", "status"]
    assert os.environ.get("MAESTRO_OPENCLAW_PROFILE") == "maestro-fleet"
