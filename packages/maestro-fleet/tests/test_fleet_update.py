from __future__ import annotations

from pathlib import Path

import maestro.update as legacy_update
import maestro_fleet.update as fleet_update


def test_package_update_uses_profiled_openclaw_paths(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    profiled = home / ".openclaw-maestro-fleet" / "openclaw.json"
    shared = home / ".openclaw" / "openclaw.json"
    profiled.parent.mkdir(parents=True, exist_ok=True)
    shared.parent.mkdir(parents=True, exist_ok=True)
    profiled.write_text("{}", encoding="utf-8")
    shared.write_text("{}", encoding="utf-8")

    observed: dict[str, object] = {}

    def _fake_run_update(**kwargs):
        observed["config_path"] = legacy_update.openclaw_config_path(home_dir=home)
        observed["workspace_root"] = legacy_update.openclaw_workspace_root(home_dir=home)
        observed["runner"] = legacy_update.prepend_openclaw_profile_shell("openclaw gateway status")
        observed["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(legacy_update, "run_update", _fake_run_update)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")

    code = fleet_update.run_update(workspace_override=None, restart_gateway=False, dry_run=True)

    assert code == 0
    assert observed["config_path"] == profiled
    assert observed["workspace_root"] == home / ".openclaw-maestro-fleet" / "workspace-maestro"
    assert observed["runner"] == "openclaw --profile maestro-fleet gateway status"
    assert observed["kwargs"] == {
        "workspace_override": None,
        "restart_gateway": False,
        "dry_run": True,
    }
