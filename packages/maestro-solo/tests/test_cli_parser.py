from __future__ import annotations

from maestro_solo.cli import build_parser


def test_parser_has_migrate_legacy_command():
    parser = build_parser()
    args = parser.parse_args(["migrate-legacy", "--dry-run"])
    assert args.command == "migrate-legacy"
    assert args.dry_run is True


def test_parser_ingest_command():
    parser = build_parser()
    args = parser.parse_args(["ingest", "/tmp/pdfs", "--project-name", "Project B"])
    assert args.command == "ingest"
    assert args.folder == "/tmp/pdfs"
    assert args.project_name == "Project B"


def test_parser_setup_quick_command():
    parser = build_parser()
    args = parser.parse_args(["setup", "--quick", "--company-name", "ACME"])
    assert args.command == "setup"
    assert args.quick is True
    assert args.company_name == "ACME"
    assert args.replay is False


def test_parser_setup_quick_replay_command():
    parser = build_parser()
    args = parser.parse_args(["setup", "--quick", "--replay"])
    assert args.command == "setup"
    assert args.quick is True
    assert args.replay is True


def test_parser_entitlements_activate_command():
    parser = build_parser()
    args = parser.parse_args(["entitlements", "activate", "--token", "abc.def.ghi"])
    assert args.command == "entitlements"
    assert args.entitlement_action == "activate"
    assert args.token == "abc.def.ghi"


def test_parser_up_require_pro_flag():
    parser = build_parser()
    args = parser.parse_args(["up", "--require-pro"])
    assert args.command == "up"
    assert args.require_pro is True


def test_parser_unsubscribe_command():
    parser = build_parser()
    args = parser.parse_args(["unsubscribe", "--email", "owner@example.com"])
    assert args.command == "unsubscribe"
    assert args.email == "owner@example.com"
