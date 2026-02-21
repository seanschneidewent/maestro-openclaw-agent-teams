"""Tests for install-state resolution helpers."""

from __future__ import annotations

import json
from pathlib import Path

from maestro.install_state import resolve_fleet_store_root, save_install_state


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_resolve_fleet_store_root_prefers_install_state(tmp_path: Path):
    home = tmp_path / "home"
    target = tmp_path / "fleet-store"
    save_install_state({"fleet_store_root": str(target)}, home_dir=home)
    assert resolve_fleet_store_root(home_dir=home) == target.resolve()


def test_resolve_fleet_store_root_from_workspace_env(tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".env").write_text("MAESTRO_STORE=knowledge_store_data\n", encoding="utf-8")

    _write_json(
        home / ".openclaw" / "openclaw.json",
        {
            "agents": {
                "list": [
                    {
                        "id": "maestro-company",
                        "default": True,
                        "workspace": str(workspace),
                    }
                ]
            }
        },
    )

    expected = (workspace / "knowledge_store_data").resolve()
    assert resolve_fleet_store_root(home_dir=home) == expected
