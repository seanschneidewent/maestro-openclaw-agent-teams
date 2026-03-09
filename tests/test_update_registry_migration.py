from __future__ import annotations

import json
from pathlib import Path

import maestro.update as update


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_backfill_registry_identity_writes_project_metadata_not_registry(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-maestro"
    store_root = workspace / "knowledge_store"
    project_dir = store_root / "alpha-project"
    _write_json(project_dir / "project.json", {"name": "Alpha Project", "slug": "alpha-project"})

    config = {
        "channels": {
            "telegram": {
                "accounts": {
                    "maestro-project-alpha-project": {
                        "username": "alpha_bot",
                        "display_name": "Alpha Bot",
                    }
                }
            }
        }
    }

    messages = update._backfill_registry_identity(workspace, config, dry_run=False)

    assert messages == ["Backfilled project Telegram identity metadata"]
    payload = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    assert payload["maestro"]["telegram_bot_username"] == "alpha_bot"
    assert payload["maestro"]["telegram_bot_display_name"] == "Alpha Bot"
    assert not (store_root / ".command_center" / "fleet_registry.json").exists()
