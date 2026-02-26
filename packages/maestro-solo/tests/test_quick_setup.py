from __future__ import annotations

import json
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
    monkeypatch.setattr(
        quick_setup.QuickSetup,
        "_ensure_openai_oauth_provider_plugin",
        lambda self: True,
    )

    def _fake_run(args: list[str], *, timeout: int = 0) -> int:
        calls.append(list(args))
        return 1

    monkeypatch.setattr(quick_setup, "_run_interactive_command", _fake_run)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    assert runner._openai_oauth_step() is False
    assert calls == [["openclaw", "models", "auth", "login", "--provider", "openai-codex"]]


def test_openai_oauth_plugin_bootstrap_stages_plugin_and_config(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    npm_calls: list[tuple[list[str], Path]] = []

    def _fake_run_in_dir(args: list[str], *, cwd: Path, timeout: int = 120, capture: bool = True):
        npm_calls.append((list(args), Path(cwd)))
        marker = Path(cwd) / "node_modules" / "@mariozechner" / "pi-ai"
        marker.mkdir(parents=True, exist_ok=True)
        (marker / "package.json").write_text("{}", encoding="utf-8")
        return True, ""

    monkeypatch.setattr(quick_setup.shutil, "which", lambda cmd: "/usr/local/bin/npm" if cmd == "npm" else None)
    monkeypatch.setattr(quick_setup, "_run_command_in_dir", _fake_run_in_dir)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    assert runner._ensure_openai_oauth_provider_plugin() is True

    config_path = Path(tmp_path / "home" / ".openclaw" / "openclaw.json")
    assert config_path.exists()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    plugins = config.get("plugins", {})
    entries = plugins.get("entries", {})
    assert entries.get("maestro-openai-codex-auth", {}).get("enabled") is True
    assert "maestro-openai-codex-auth" in plugins.get("allow", [])
    assert npm_calls and npm_calls[0][0][:2] == ["npm", "install"]

    npm_calls.clear()
    assert runner._ensure_openai_oauth_provider_plugin() is True
    assert npm_calls == []


def test_workspace_bootstrap_core_tier_does_not_reference_native_plugin(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    runner.gemini_key = "GEMINI_KEY_FOR_TEST"
    runner.telegram_token = "123456:abcDEF123_token"
    runner.bot_username = "trace_bot"

    monkeypatch.setattr(runner, "_refresh_entitlement", lambda: None)
    monkeypatch.setattr(quick_setup, "has_capability", lambda _entitlement, _capability: False)
    monkeypatch.setattr(runner, "_seed_workspace_files", lambda *, pro_enabled: None)
    monkeypatch.setattr(runner, "_seed_workspace_skill", lambda: None)
    monkeypatch.setattr(runner, "_seed_native_extension", lambda: None)
    monkeypatch.setattr(runner, "_maybe_build_workspace_frontend", lambda: None)

    assert runner._configure_openclaw_and_workspace_step() is True

    config_path = Path(tmp_path / "home" / ".openclaw" / "openclaw.json")
    assert config_path.exists()
    config = json.loads(config_path.read_text(encoding="utf-8"))

    plugins = config.get("plugins", {})
    entries = plugins.get("entries", {})
    assert "maestro-native-tools" not in entries

    telegram = config.get("channels", {}).get("telegram", {})
    assert telegram.get("streaming") == "partial"
    assert "streamMode" not in telegram
    account = telegram.get("accounts", {}).get("maestro-solo-personal", {})
    assert account.get("streaming") == "partial"
    assert "streamMode" not in account


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
