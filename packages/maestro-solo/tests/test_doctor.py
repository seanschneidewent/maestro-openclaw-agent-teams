from __future__ import annotations

from pathlib import Path

import maestro_solo.doctor as doctor


def _write_launchagent(path: Path, port: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>ProgramArguments</key>
  <array>
    <string>openclaw</string>
    <string>gateway</string>
    <string>--port</string>
    <string>{port}</string>
  </array>
</dict>
</plist>
""",
        encoding="utf-8",
    )


def test_launchagent_path_uses_profile_label(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-solo")

    path = doctor._launchagent_path(home)
    assert path.name == "ai.openclaw.maestro-solo.plist"
    assert doctor._launchagent_label() == "ai.openclaw.maestro-solo"


def test_sync_gateway_service_port_reports_mismatch_without_fix(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-solo")

    plist_path = doctor._launchagent_path(home)
    _write_launchagent(plist_path, 18789)
    result = doctor._sync_gateway_service_port(home, config={"gateway": {"port": 19124}}, fix=False)
    assert result.ok is False
    assert result.warning is True
    assert "does not match service port" in result.detail


def test_sync_gateway_service_port_reinstalls_with_expected_port(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-solo")

    plist_path = doctor._launchagent_path(home)
    _write_launchagent(plist_path, 18789)

    calls: list[list[str]] = []
    observed = {"count": 0}

    def _fake_run_cmd(args: list[str], timeout: int = 25):
        calls.append(list(args))
        return True, "ok"

    def _fake_launchagent_gateway_port(_path: Path):
        observed["count"] += 1
        if observed["count"] == 1:
            return 18789
        return 19124

    monkeypatch.setattr(doctor, "_run_cmd", _fake_run_cmd)
    monkeypatch.setattr(doctor, "_launchagent_gateway_port", _fake_launchagent_gateway_port)

    result = doctor._sync_gateway_service_port(home, config={"gateway": {"port": 19124}}, fix=True)
    assert result.ok is True
    assert result.fixed is True
    assert ["openclaw", "gateway", "install", "--force", "--port", "19124"] in calls


def test_gateway_running_false_when_status_reports_unreachable(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "_run_cmd",
        lambda args, timeout=25: (
            True,
            "Gateway service running\nGateway local · ws://127.0.0.1:19124 · unreachable (connect ECONNREFUSED)",
        ),
    )
    assert doctor._gateway_running() is False

