from __future__ import annotations

import json

from maestro_fleet.openclaw_runtime import openclaw_state_root
from maestro_fleet.state import resolve_commander_agent


def test_openclaw_state_root_uses_profiled_dir_without_shared_fallback(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")

    shared = home / ".openclaw"
    profiled = home / ".openclaw-maestro-fleet"
    shared.mkdir()
    profiled.mkdir()

    assert openclaw_state_root(home_dir=home) == profiled


def test_resolve_commander_agent_prefers_profiled_openclaw_config(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")

    shared = home / ".openclaw"
    shared.mkdir()
    (shared / "openclaw.json").write_text(
        json.dumps(
            {
                "agents": {
                    "list": [
                        {
                            "id": "maestro-company",
                            "default": True,
                            "workspace": "/shared/workspace",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    profiled = home / ".openclaw-maestro-fleet"
    profiled.mkdir()
    (profiled / "openclaw.json").write_text(
        json.dumps(
            {
                "agents": {
                    "list": [
                        {
                            "id": "maestro-company",
                            "default": True,
                            "workspace": "/profiled/workspace",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert resolve_commander_agent(home_dir=home) == ("maestro-company", "/profiled/workspace")
