"""Tests for system directive persistence and feed behavior."""

from __future__ import annotations

import json
from pathlib import Path

from maestro.system_directives import (
    archive_system_directive,
    list_active_directive_feed,
    list_system_directives,
    upsert_system_directive,
)


def _write_json(path: Path, data: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_upsert_and_archive_directive(tmp_path: Path):
    created = upsert_system_directive(
        tmp_path,
        {
            "title": "Safety SOP",
            "body": "Enforce PPE checks before start of shift.",
            "scope": "global",
            "status": "active",
            "priority": 90,
        },
        updated_by="tester",
    )
    assert created["ok"] is True
    directive_id = created["directive"]["id"]

    directives = list_system_directives(tmp_path)
    assert len(directives) == 1
    assert directives[0]["id"] == directive_id
    assert directives[0]["status"] == "active"

    archived = archive_system_directive(tmp_path, directive_id, updated_by="tester")
    assert archived["ok"] is True
    assert archived["directive"]["status"] == "archived"

    active_only = list_system_directives(tmp_path)
    assert active_only == []

    with_archived = list_system_directives(tmp_path, include_archived=True)
    assert len(with_archived) == 1
    assert with_archived[0]["status"] == "archived"


def test_active_feed_filters_to_active(tmp_path: Path):
    upsert_system_directive(
        tmp_path,
        {"id": "DIR-A", "title": "A", "body": "Active", "status": "active", "priority": 80},
    )
    upsert_system_directive(
        tmp_path,
        {"id": "DIR-D", "title": "D", "body": "Draft", "status": "draft", "priority": 100},
    )
    feed = list_active_directive_feed(tmp_path)
    assert len(feed) == 1
    assert feed[0]["id"] == "DIR-A"
    assert feed[0]["command"] == "Active"


def test_legacy_directives_fallback(tmp_path: Path):
    _write_json(
        tmp_path / ".command_center" / "directives.json",
        {
            "directives": [
                {
                    "id": "DIR-LEG",
                    "title": "Legacy",
                    "command": "Legacy command",
                    "status": "active",
                    "priority": 70,
                }
            ]
        },
    )
    feed = list_active_directive_feed(tmp_path)
    assert len(feed) == 1
    assert feed[0]["id"] == "DIR-LEG"
