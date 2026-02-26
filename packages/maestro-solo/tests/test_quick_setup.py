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


def test_tailscale_step_defers_when_not_installed_without_prompt(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)

    def _should_not_prompt(*args, **kwargs):
        raise AssertionError("Confirm.ask should not be called during quick setup tailscale deferral")

    monkeypatch.setattr(quick_setup.Confirm, "ask", _should_not_prompt)
    monkeypatch.setattr(quick_setup.shutil, "which", lambda _cmd: None)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    assert runner._tailscale_optional_step() is True
    assert "tailscale" in runner.pending_optional_setup


def test_pairing_fails_fast_when_gateway_is_not_running(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    monkeypatch.setattr(quick_setup.time, "sleep", lambda _seconds: None)

    def _fake_interactive(args: list[str], *, timeout: int = 0) -> int:
        calls.append(list(args))
        return 1

    def _fake_command(args: list[str], *, timeout: int = 120, capture: bool = True):
        if args[:2] == ["openclaw", "status"]:
            return True, "gateway service stopped"
        return False, "not-running"

    def _should_not_ask(*args, **kwargs):
        raise AssertionError("Prompt.ask should not be called when gateway health checks fail")

    monkeypatch.setattr(quick_setup, "_run_interactive_command", _fake_interactive)
    monkeypatch.setattr(quick_setup, "_run_command", _fake_command)
    monkeypatch.setattr(quick_setup.Prompt, "ask", _should_not_ask)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    runner.bot_username = "trace_bot"
    assert runner._pair_telegram_required_step() is False
    assert calls[:2] == [["openclaw", "gateway", "start"], ["openclaw", "gateway", "restart"]]
