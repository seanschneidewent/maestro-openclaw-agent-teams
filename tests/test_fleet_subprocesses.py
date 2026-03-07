from __future__ import annotations

import pytest
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
