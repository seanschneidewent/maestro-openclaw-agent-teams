"""Tests for Maestro CLI parser wiring."""

from __future__ import annotations

from maestro.cli import build_parser


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


def test_fleet_purchase_parser():
    parser = build_parser()
    args = parser.parse_args([
        "fleet",
        "purchase",
        "--project-name",
        "Test Project",
        "--assignee",
        "Andy",
        "--non-interactive",
    ])
    assert args.mode == "fleet"
    assert args.fleet_command == "purchase"
    assert args.project_name == "Test Project"
    assert args.assignee == "Andy"
    assert args.non_interactive is True


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
