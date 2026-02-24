from __future__ import annotations

import json
from pathlib import Path

from maestro_solo import migration


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_migrate_legacy_imports_state(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(home / ".maestro-solo"))

    _write_json(
        home / ".maestro" / "install.json",
        {
            "workspace_root": str(home / ".openclaw" / "workspace-maestro"),
            "store_root": str(home / ".openclaw" / "workspace-maestro" / "knowledge_store"),
            "active_project_slug": "alpha",
            "active_project_name": "Alpha",
        },
    )

    report = migration.migrate_legacy(dry_run=False)

    assert report["changed"] is True
    assert report["state"]["active_project_slug"] == "alpha"
    assert report["state"]["active_project_name"] == "Alpha"
