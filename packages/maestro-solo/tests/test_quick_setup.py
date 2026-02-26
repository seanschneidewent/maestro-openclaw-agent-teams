from __future__ import annotations

from pathlib import Path

import maestro_solo.quick_setup as quick_setup
from maestro_solo.install_state import load_install_state, save_install_state


def _configure_env(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    solo_home = tmp_path / "solo-home"
    home.mkdir(parents=True, exist_ok=True)
    solo_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(solo_home))


def test_company_name_checkpoint_persists_after_prompt(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setattr(quick_setup.Prompt, "ask", lambda *args, **kwargs: "Trace Construction")

    runner = quick_setup.QuickSetup(company_name="", replay=False)
    assert runner._company_name_step() is True

    state = load_install_state()
    assert state.get("company_name") == "Trace Construction"
    assert state.get("setup_mode") == "quick"
    assert state.get("setup_completed") is False


def test_company_name_reuses_saved_value_without_prompt(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    save_install_state({"company_name": "Saved Co", "setup_mode": "quick", "setup_completed": False})

    def _should_not_prompt(*args, **kwargs):
        raise AssertionError("Prompt.ask should not be called when a saved company name exists")

    monkeypatch.setattr(quick_setup.Prompt, "ask", _should_not_prompt)

    runner = quick_setup.QuickSetup(company_name="", replay=False)
    assert runner._company_name_step() is True
    assert runner.company_name == "Saved Co"


def test_openai_oauth_step_does_not_fallback_to_onboard(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    monkeypatch.setattr(quick_setup, "_openclaw_oauth_profile_exists", lambda _provider: False)

    def _fake_run(args: list[str], *, timeout: int = 0) -> int:
        calls.append(list(args))
        return 1

    monkeypatch.setattr(quick_setup, "_run_interactive_command", _fake_run)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    assert runner._openai_oauth_step() is False
    assert calls == [["openclaw", "models", "auth", "login", "--provider", "openai-codex"]]

