from __future__ import annotations

import pytest
import json
from pathlib import Path
from types import SimpleNamespace

from maestro.fleet.shared import subprocesses as shared_subprocesses
from maestro_fleet import monitor


def test_sanitized_subprocess_env_drops_disabled_malloc_stack_flags_on_macos(monkeypatch):
    monkeypatch.setenv("MallocStackLogging", "0")
    monkeypatch.setenv("MallocStackLoggingNoCompact", "false")
    monkeypatch.setenv("MallocNanoZone", "0")
    monkeypatch.setattr(shared_subprocesses.sys, "platform", "darwin")

    env = shared_subprocesses.sanitized_subprocess_env()

    assert "MallocStackLogging" not in env
    assert "MallocStackLoggingNoCompact" not in env
    assert env.get("MallocNanoZone") == "0"


def test_sanitized_subprocess_env_keeps_enabled_malloc_stack_logging_on_macos(monkeypatch):
    monkeypatch.setenv("MallocStackLogging", "1")
    monkeypatch.setattr(shared_subprocesses.sys, "platform", "darwin")

    env = shared_subprocesses.sanitized_subprocess_env()

    assert env.get("MallocStackLogging") == "1"


def test_fleet_monitor_safe_run_uses_sanitized_env(monkeypatch):
    monkeypatch.setenv("MallocStackLogging", "0")
    monkeypatch.setattr(shared_subprocesses.sys, "platform", "darwin")
    monkeypatch.setattr(
        monitor,
        "prepend_openclaw_profile_args",
        lambda args, default_profile=None: ["openclaw", *args],
    )

    observed: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        observed["args"] = args[0]
        observed["env"] = kwargs.get("env")
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(monitor.subprocess, "run", _fake_run)

    ok, output = monitor._safe_run(["gateway", "status", "--json"])

    assert ok is True
    assert output == '{"ok":true}'
    assert observed["args"] == ["openclaw", "gateway", "status", "--json"]
    assert "MallocStackLogging" not in observed["env"]


def test_maybe_reexec_without_disabled_malloc_stack_logging_reexecs_clean_module(monkeypatch):
    monkeypatch.setenv("MallocStackLogging", "0")
    monkeypatch.delenv("MAESTRO_MALLOC_ENV_CLEANED", raising=False)
    monkeypatch.setattr(shared_subprocesses.sys, "platform", "darwin")
    monkeypatch.setattr(shared_subprocesses.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(shared_subprocesses.sys, "argv", ["maestro-fleet", "up", "--tui"])

    observed: dict[str, object] = {}

    def _fake_execve(path, argv, env):
        observed["path"] = path
        observed["argv"] = argv
        observed["env"] = env
        raise SystemExit(0)

    monkeypatch.setattr(shared_subprocesses.os, "execve", _fake_execve)

    with pytest.raises(SystemExit):
        shared_subprocesses.maybe_reexec_without_disabled_malloc_stack_logging(module="maestro_fleet")

    assert observed["path"] == "/usr/bin/python3"
    assert observed["argv"] == ["/usr/bin/python3", "-m", "maestro_fleet", "up", "--tui"]
    assert observed["env"]["MAESTRO_MALLOC_ENV_CLEANED"] == "1"
    assert "MallocStackLogging" not in observed["env"]


def test_run_up_tui_restarts_existing_maestro_server_listener_and_stops_gateway_on_exit(monkeypatch, tmp_path):
    store = tmp_path / "fleet-store"
    store.mkdir()
    stopped: list[tuple[int, float]] = []
    started: list[list[str]] = []
    gateway_events: list[str] = []

    monkeypatch.setattr(
        monitor,
        "resolve_network_urls",
        lambda web_port, route_path: {
            "recommended_url": f"http://localhost:{web_port}{route_path}",
            "localhost_url": f"http://localhost:{web_port}{route_path}",
            "tailnet_url": None,
        },
    )
    monkeypatch.setattr(monitor, "_resolve_commander_agent", lambda: ("commander-agent", "/tmp/workspace"))
    monkeypatch.setattr(monitor, "_resolve_fleet_models", lambda: ("openai/gpt-5.4", "google/gemini-3.1-pro-preview"))
    monkeypatch.setattr(monitor, "load_install_state", lambda: {"company_name": "ACME"})
    monkeypatch.setattr(monitor, "_maestro_server_listener_pids", lambda port: [4242])
    monkeypatch.setattr(monitor, "listener_pids", lambda port: [4242])
    monkeypatch.setattr(monitor, "_start_gateway_log_stream", lambda *args, **kwargs: None)
    monkeypatch.setattr(monitor, "_install_shutdown_signal_handlers", lambda: {})
    monkeypatch.setattr(monitor, "_restore_shutdown_signal_handlers", lambda previous: None)
    monkeypatch.setattr(monitor, "_shutdown_process", lambda process, *, timeout_sec: None)
    monkeypatch.setattr(monitor, "_shutdown_pid", lambda pid, *, timeout_sec: stopped.append((pid, timeout_sec)))
    monkeypatch.setattr(
        monitor,
        "_restart_fleet_gateway_for_tui",
        lambda gateway_logs: gateway_events.append("restart") or {"ok": True},
    )
    monkeypatch.setattr(
        monitor,
        "_stop_fleet_gateway_for_tui",
        lambda gateway_logs: gateway_events.append("stop") or {"ok": True},
    )
    monkeypatch.setattr(monitor, "_update_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(monitor, "_build_layout", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        monitor.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    fake_process = SimpleNamespace(pid=5151, returncode=None, stdout=None)
    fake_process.poll = lambda: None

    monkeypatch.setattr(
        monitor,
        "_start_text_process",
        lambda cmd, **kwargs: started.append(list(cmd)) or fake_process,
    )

    class FakeLive:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(monitor, "Live", FakeLive)

    monitor.run_up_tui(port=3000, store=str(store), host="0.0.0.0")

    assert stopped == [(4242, 8.0)]
    assert started
    assert started[0][0:3] == [monitor.sys.executable, "-m", "maestro_fleet.server"]
    assert gateway_events == ["restart", "stop"]


def test_stop_existing_fleet_server_uses_pidfile_state_and_clears_it(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    state_dir = home / ".maestro" / "fleet"
    state_dir.mkdir(parents=True)
    pid_path = state_dir / "serve.pid.json"
    pid_path.write_text(json.dumps({"pid": 4242, "port": 3000}), encoding="utf-8")

    stopped: list[tuple[int, float]] = []

    monkeypatch.setattr(monitor, "_maestro_server_listener_pids", lambda port: [])
    monkeypatch.setattr(monitor, "listener_pids", lambda port: [])
    monkeypatch.setattr(monitor, "_pid_running", lambda pid: pid == 4242)
    monkeypatch.setattr(
        monitor,
        "read_process_command",
        lambda pid: "python -m maestro_fleet.server --port 3000 --store /tmp/fleet-store --host 0.0.0.0",
    )
    monkeypatch.setattr(monitor, "_shutdown_pid", lambda pid, *, timeout_sec: stopped.append((pid, timeout_sec)))

    result = monitor._stop_existing_fleet_server(3000, timeout_sec=8.0)

    assert result == [4242]
    assert stopped == [(4242, 8.0)]
    assert not pid_path.exists()


def test_start_text_process_uses_new_session_on_posix(monkeypatch):
    observed: dict[str, object] = {}

    def _fake_popen(cmd, **kwargs):
        observed["cmd"] = cmd
        observed["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(monitor.os, "name", "posix", raising=False)
    monkeypatch.setattr(monitor.subprocess, "Popen", _fake_popen)

    monitor._start_text_process(["python", "-m", "maestro.cli", "serve"])

    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("text") is True
    assert kwargs.get("bufsize") == 1


def test_install_shutdown_signal_handlers_maps_sigterm_to_keyboard_interrupt(monkeypatch):
    registered: dict[int, object] = {}

    monkeypatch.setattr(monitor.signal, "getsignal", lambda sig: f"previous:{sig}")

    def _fake_signal(sig, handler):
        registered[sig] = handler

    monkeypatch.setattr(monitor.signal, "signal", _fake_signal)

    previous = monitor._install_shutdown_signal_handlers()

    assert monitor.signal.SIGTERM in previous
    assert monitor.signal.SIGTERM in registered
    with pytest.raises(KeyboardInterrupt):
        registered[monitor.signal.SIGTERM](monitor.signal.SIGTERM, None)


def test_render_compute_includes_commander_and_project_models():
    state = monitor.MonitorState(
        store_path=Path("/tmp/fleet-store"),
        web_port=3000,
        company_name="ACME",
        primary_url="http://localhost:3000/command-center",
        local_url="http://localhost:3000/command-center",
        tailnet_url=None,
        commander_agent_id="maestro-company",
        commander_workspace="/tmp/workspace",
        commander_model="openai/gpt-5.4",
        project_model="google/gemini-3.1-pro-preview",
    )

    panel = monitor._render_compute(state)
    text = str(panel.renderable)

    assert "OpenAI GPT-5.4" in text
    assert "Google Gemini 3.1 Pro" in text
