"""Tests for Maestro CLI parser wiring."""

from __future__ import annotations

from maestro.cli import build_parser


def test_up_parser_accepts_tui_flag():
    parser = build_parser()
    args = parser.parse_args(["up", "--tui", "--store", "/tmp/ks"])
    assert args.mode == "up"
    assert args.tui is True
    assert args.store == "/tmp/ks"


def test_doctor_parser_fix_and_json_flags():
    parser = build_parser()
    args = parser.parse_args(["doctor", "--fix", "--json"])
    assert args.mode == "doctor"
    assert args.fix is True
    assert args.json is True
