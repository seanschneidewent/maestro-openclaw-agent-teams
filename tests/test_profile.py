"""Tests for runtime profile helpers."""

from __future__ import annotations

import json
from pathlib import Path

from maestro.install_state import load_install_state, save_install_state
from maestro.profile import (
    fleet_enabled,
    infer_profile_from_openclaw_config,
    resolve_profile,
    set_profile,
)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_infer_profile_from_config_solo_personal():
    config = {
        "agents": {"list": [{"id": "maestro-personal", "default": True}]},
    }
    assert infer_profile_from_openclaw_config(config) == "solo"


def test_infer_profile_from_config_fleet_company():
    config = {
        "agents": {
            "list": [
                {"id": "maestro-company", "default": True},
                {"id": "maestro-project-alpha"},
            ]
        },
    }
    assert infer_profile_from_openclaw_config(config) == "fleet"


def test_resolve_profile_prefers_install_state(tmp_path: Path):
    home = tmp_path / "home"
    save_install_state({"profile": "solo", "fleet_enabled": False}, home_dir=home)
    _write_json(
        home / ".openclaw" / "openclaw.json",
        {"agents": {"list": [{"id": "maestro-company", "default": True}]}},
    )
    assert resolve_profile(home_dir=home) == "solo"


def test_set_profile_updates_install_state(tmp_path: Path):
    home = tmp_path / "home"
    state = set_profile("fleet", home_dir=home, fleet=True)
    assert state["profile"] == "fleet"
    assert state["fleet_enabled"] is True

    persisted = load_install_state(home_dir=home)
    assert persisted.get("profile") == "fleet"
    assert persisted.get("fleet_enabled") is True


def test_fleet_enabled_respects_explicit_flag(tmp_path: Path):
    home = tmp_path / "home"
    save_install_state({"profile": "solo", "fleet_enabled": False}, home_dir=home)
    assert fleet_enabled(home_dir=home) is False

    save_install_state({"profile": "solo", "fleet_enabled": True}, home_dir=home)
    assert fleet_enabled(home_dir=home) is True
