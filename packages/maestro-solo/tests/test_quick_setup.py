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


def test_quick_setup_replay_stays_on_isolated_profile(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    save_install_state({"setup_completed": True})
    monkeypatch.delenv("MAESTRO_OPENCLAW_PROFILE", raising=False)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=True)
    assert runner.openclaw_profile == "maestro-solo"
    assert runner.openclaw_root == Path(tmp_path / "home" / ".openclaw-maestro-solo")


def test_openai_oauth_step_does_not_fallback_to_onboard(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    monkeypatch.setattr(quick_setup, "_openclaw_oauth_profile_exists", lambda _provider, **_kwargs: False)
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
    assert calls == [["openclaw", "--profile", "maestro-solo", "models", "auth", "login", "--provider", "openai-codex"]]


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

    config_path = Path(tmp_path / "home" / ".openclaw-maestro-solo" / "openclaw.json")
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


def test_openai_oauth_plugin_bootstrap_retries_npm_install(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    install_attempts = 0

    def _fake_run_in_dir(args: list[str], *, cwd: Path, timeout: int = 120, capture: bool = True):
        nonlocal install_attempts
        if args[:2] == ["npm", "install"]:
            install_attempts += 1
            if install_attempts < 3:
                return False, f"network error attempt {install_attempts}"
            marker = Path(cwd) / "node_modules" / "@mariozechner" / "pi-ai"
            marker.mkdir(parents=True, exist_ok=True)
            (marker / "package.json").write_text("{}", encoding="utf-8")
            return True, "installed"
        return True, ""

    monkeypatch.setattr(quick_setup.shutil, "which", lambda cmd: "/usr/local/bin/npm" if cmd == "npm" else None)
    monkeypatch.setattr(quick_setup, "_run_command_in_dir", _fake_run_in_dir)
    monkeypatch.setattr(quick_setup.time, "sleep", lambda _seconds: None)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    assert runner._ensure_openai_oauth_provider_plugin() is True
    assert install_attempts == 3


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

    config_path = Path(tmp_path / "home" / ".openclaw-maestro-solo" / "openclaw.json")
    assert config_path.exists()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    gateway = config.get("gateway", {})
    assert gateway.get("mode") == "local"
    assert gateway.get("port") == quick_setup.DEFAULT_MAESTRO_GATEWAY_PORT

    plugins = config.get("plugins", {})
    entries = plugins.get("entries", {})
    assert "maestro-native-tools" not in entries

    telegram = config.get("channels", {}).get("telegram", {})
    assert telegram.get("streamMode") == "partial"
    assert "streaming" not in telegram
    account = telegram.get("accounts", {}).get("maestro-solo-personal", {})
    assert account.get("streamMode") == "partial"
    assert "streaming" not in account


def test_workspace_bootstrap_does_not_write_shared_openclaw_config(monkeypatch, tmp_path):
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

    isolated_config = Path(tmp_path / "home" / ".openclaw-maestro-solo" / "openclaw.json")
    shared_config = Path(tmp_path / "home" / ".openclaw" / "openclaw.json")
    assert isolated_config.exists()
    assert not shared_config.exists()


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
        if args[:4] == ["openclaw", "--profile", "maestro-solo", "status"]:
            return True, "gateway service stopped"
        return False, "not-running"

    def _should_not_ask(*args, **kwargs):
        raise AssertionError("Prompt.ask should not be called when gateway health checks fail")

    monkeypatch.setattr(quick_setup, "_run_interactive_command", _fake_interactive)
    monkeypatch.setattr(quick_setup, "_run_command", _fake_command)
    monkeypatch.setattr(quick_setup.Prompt, "ask", _should_not_ask)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    runner.bot_username = "trace_bot"
    runner.gateway_port = 19133
    monkeypatch.setattr(runner, "_ensure_gateway_service_port_alignment", lambda: True)
    assert runner._pair_telegram_required_step() is False
    assert calls[:4] == [
        ["openclaw", "--profile", "maestro-solo", "gateway", "--port", "19133", "start"],
        ["openclaw", "--profile", "maestro-solo", "gateway", "--port", "19133", "install", "--force"],
        ["openclaw", "--profile", "maestro-solo", "gateway", "--port", "19133", "restart"],
        ["openclaw", "--profile", "maestro-solo", "gateway", "--port", "19133", "start"],
    ]


def test_gateway_running_requires_reachable_port(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    runner.gateway_port = 19124

    monkeypatch.setattr(
        runner,
        "_run_openclaw_command",
        lambda *args, **kwargs: (True, "Gateway service running; Gateway local · ws://127.0.0.1:19124"),
    )
    monkeypatch.setattr(quick_setup, "_port_is_reachable", lambda _port, timeout=0.5: False)

    ok, _ = runner._gateway_running()
    assert ok is False


def test_gateway_running_rejects_unreachable_status(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    runner.gateway_port = 19124

    monkeypatch.setattr(
        runner,
        "_run_openclaw_command",
        lambda *args, **kwargs: (
            True,
            "Gateway service running; Gateway local · ws://127.0.0.1:19124 · unreachable (connect ECONNREFUSED)",
        ),
    )
    monkeypatch.setattr(quick_setup, "_port_is_reachable", lambda _port, timeout=0.5: True)

    ok, _ = runner._gateway_running()
    assert ok is False


def test_gateway_alignment_reinstalls_service_when_port_mismatch(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    runner.gateway_port = 19124
    calls: list[list[str]] = []
    observed = {"count": 0}

    monkeypatch.setattr(quick_setup.platform, "system", lambda: "Darwin")

    def _fake_launchagent_port(_path):
        observed["count"] += 1
        if observed["count"] == 1:
            return 18789
        return 19124

    monkeypatch.setattr(quick_setup, "_launchagent_gateway_port", _fake_launchagent_port)

    def _fake_interactive(args: list[str], *, timeout: int = 0) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setattr(runner, "_run_openclaw_interactive", _fake_interactive)
    assert runner._ensure_gateway_service_port_alignment() is True
    assert calls == [["gateway", "--port", "19124", "install", "--force"]]


def test_quick_setup_blocks_shared_openclaw_writes_without_explicit_write_override(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MAESTRO_ALLOW_SHARED_OPENCLAW", "1")
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "shared")
    monkeypatch.delenv("MAESTRO_ALLOW_SHARED_OPENCLAW_WRITE", raising=False)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    assert runner.openclaw_root == Path(tmp_path / "home" / ".openclaw")
    assert runner._configure_openclaw_and_workspace_step() is False
    assert not Path(tmp_path / "home" / ".openclaw" / "openclaw.json").exists()


def test_openai_oauth_plugin_bootstrap_blocks_shared_openclaw_without_write_override(monkeypatch, tmp_path):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MAESTRO_ALLOW_SHARED_OPENCLAW", "1")
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "shared")
    monkeypatch.delenv("MAESTRO_ALLOW_SHARED_OPENCLAW_WRITE", raising=False)

    runner = quick_setup.QuickSetup(company_name="Trace", replay=False)
    assert runner.openclaw_root == Path(tmp_path / "home" / ".openclaw")
    assert runner._ensure_openai_oauth_provider_plugin() is False
