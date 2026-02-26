from __future__ import annotations

from pathlib import Path

from maestro_solo.install_flow import (
    install_auto_approve_enabled,
    is_truthy,
    resolve_install_runtime,
    resolve_journey_selection,
)


def test_resolve_journey_selection_install_pro_auto_channel():
    selection = resolve_journey_selection(
        raw_flow="install",
        raw_intent="pro",
        raw_channel="auto",
    )
    assert selection.flow == "install"
    assert selection.intent == "pro"
    assert selection.channel == "pro"


def test_resolve_journey_selection_invalid_values_fallback():
    selection = resolve_journey_selection(
        raw_flow="weird",
        raw_intent="core",
        raw_channel="broken",
    )
    assert selection.flow == "free"
    assert selection.intent == "free"
    assert selection.channel == "core"


def test_resolve_install_runtime_uses_env_paths(monkeypatch, tmp_path):
    home = tmp_path / "home"
    solo = tmp_path / "solo-home"
    home.mkdir(parents=True, exist_ok=True)
    solo.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(solo))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-solo")

    runtime = resolve_install_runtime(workspace_dir="workspace-maestro-solo")

    assert runtime.solo_home == solo.resolve()
    assert runtime.openclaw_profile == "maestro-solo"
    assert runtime.openclaw_root == (home / ".openclaw-maestro-solo").resolve()
    assert runtime.workspace_root == (runtime.openclaw_root / "workspace-maestro-solo").resolve()
    assert runtime.store_root == (runtime.workspace_root / "knowledge_store").resolve()


def test_install_auto_approve_enabled_truthy(monkeypatch):
    monkeypatch.setenv("MAESTRO_INSTALL_AUTO", "yes")
    assert is_truthy("on") is True
    assert install_auto_approve_enabled() is True
