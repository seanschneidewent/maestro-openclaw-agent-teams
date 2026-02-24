from __future__ import annotations

from maestro_fleet import cli


def test_parser_has_fleet_surface():
    parser = cli.build_parser()
    args = parser.parse_args(["purchase", "--project-name", "ACME Tower", "--dry-run"])
    assert args.command == "purchase"
    assert args.project_name == "ACME Tower"
    assert args.dry_run is True


def test_forward_purchase_args():
    parser = cli.build_parser()
    args = parser.parse_args(["purchase", "--project-name", "ACME Tower", "--dry-run"])
    forwarded = cli._to_legacy_argv(args)
    assert forwarded[:2] == ["fleet", "purchase"]
    assert "--project-name" in forwarded
    assert "--dry-run" in forwarded
