from __future__ import annotations

from maestro_solo.install_state import load_install_state, save_install_state


def test_install_state_persists_quick_setup_metadata(tmp_path):
    home = tmp_path / "solo-home"

    save_install_state(
        {
            "workspace_root": "/tmp/workspace",
            "store_root": "/tmp/store",
            "setup_mode": "quick",
            "setup_completed": True,
            "pending_optional_setup": ["tailscale", "ingest_plans", ""],
        },
        home_dir=home,
    )

    loaded = load_install_state(home_dir=home)
    assert loaded["setup_mode"] == "quick"
    assert loaded["setup_completed"] is True
    assert loaded["pending_optional_setup"] == ["tailscale", "ingest_plans"]
