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
