from __future__ import annotations

import json
from pathlib import Path

from maestro_solo import openclaw_runtime


def _configure_env(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    solo_home = tmp_path / "solo-home"
    home.mkdir(parents=True, exist_ok=True)
    solo_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(solo_home))
    return home, solo_home


def test_defaults_to_isolated_profile(monkeypatch, tmp_path):
    home, _ = _configure_env(monkeypatch, tmp_path)
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)
    monkeypatch.delenv("MAESTRO_ALLOW_SHARED_OPENCLAW", raising=False)

    assert openclaw_runtime.resolve_openclaw_profile() == "maestro-solo"
    assert openclaw_runtime.openclaw_state_root() == home / ".openclaw-maestro-solo"
    assert openclaw_runtime.prepend_openclaw_profile_args(["openclaw", "status"]) == [
        "openclaw",
        "--profile",
        "maestro-solo",
        "status",
    ]


def test_shared_profile_override_is_blocked_by_default(monkeypatch, tmp_path):
    home, _ = _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "shared")
    monkeypatch.delenv("MAESTRO_ALLOW_SHARED_OPENCLAW", raising=False)

    assert openclaw_runtime.resolve_openclaw_profile() == "maestro-solo"
    assert openclaw_runtime.openclaw_state_root() == home / ".openclaw-maestro-solo"


def test_shared_profile_override_requires_unsafe_flag(monkeypatch, tmp_path):
    home, _ = _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "shared")
    monkeypatch.setenv("MAESTRO_ALLOW_SHARED_OPENCLAW", "1")

    assert openclaw_runtime.resolve_openclaw_profile() == ""
    assert openclaw_runtime.openclaw_state_root() == home / ".openclaw"
    assert openclaw_runtime.prepend_openclaw_profile_args(["openclaw", "status"]) == ["openclaw", "status"]


def test_shared_write_guard_requires_explicit_write_override(monkeypatch, tmp_path):
    home, _ = _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MAESTRO_ALLOW_SHARED_OPENCLAW", "1")
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "shared")
    monkeypatch.delenv("MAESTRO_ALLOW_SHARED_OPENCLAW_WRITE", raising=False)

    ok, message = openclaw_runtime.ensure_safe_openclaw_write_target(home / ".openclaw")
    assert ok is False
    assert "MAESTRO_ALLOW_SHARED_OPENCLAW_WRITE=1" in message

    monkeypatch.setenv("MAESTRO_ALLOW_SHARED_OPENCLAW_WRITE", "1")
    ok_after, _ = openclaw_runtime.ensure_safe_openclaw_write_target(home / ".openclaw")
    assert ok_after is True


def test_install_state_profile_is_used(monkeypatch, tmp_path):
    _, solo_home = _configure_env(monkeypatch, tmp_path)
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)
    monkeypatch.delenv("MAESTRO_ALLOW_SHARED_OPENCLAW", raising=False)

    install_path = solo_home / "install.json"
    install_path.write_text(json.dumps({"openclaw_profile": "custom-profile"}), encoding="utf-8")

    assert openclaw_runtime.resolve_openclaw_profile() == "custom-profile"
