from __future__ import annotations

from types import SimpleNamespace

from maestro_fleet import gateway


def test_run_profiled_gateway_cmd_prepends_fleet_profile(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _fake_prepend(args: list[str], *, default_profile: str = "") -> list[str]:
        observed["default_profile"] = default_profile
        observed["args"] = list(args)
        return ["openclaw", "--profile", default_profile, *args[1:]]

    def _fake_run(args, **kwargs):
        observed["cmd"] = list(args)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(gateway, "prepend_openclaw_profile_args", _fake_prepend)
    monkeypatch.setattr(gateway.subprocess, "run", _fake_run)

    ok, output = gateway.run_profiled_gateway_cmd(["openclaw", "gateway", "status", "--json"], 12)

    assert ok is True
    assert output == '{"ok":true}'
    assert observed["default_profile"] == "maestro-fleet"
    assert observed["cmd"] == ["openclaw", "--profile", "maestro-fleet", "gateway", "status", "--json"]


def test_restart_openclaw_gateway_report_contract(monkeypatch) -> None:
    snapshots = iter(
        [
            (False, {"rpc": {"ok": False}, "service": {"runtime": {"status": "stopped"}}}, "stopped"),
            (False, {"rpc": {"ok": False}, "service": {"runtime": {"status": "stopped"}}}, "still stopped"),
            (True, {"rpc": {"ok": True}, "service": {"runtime": {"status": "running"}}}, "running"),
        ]
    )
    commands: list[list[str]] = []

    def _fake_status_snapshot(*, timeout: int = 12):
        return next(snapshots)

    def _fake_run(args: list[str], timeout: int):
        commands.append(list(args))
        return True, "ok"

    monkeypatch.setattr(gateway, "gateway_status_snapshot", _fake_status_snapshot)
    monkeypatch.setattr(gateway, "run_profiled_gateway_cmd", _fake_run)

    report = gateway.restart_openclaw_gateway_report(dry_run=False)

    assert report == {
        "ok": True,
        "detail": "gateway restart: ok\nok\ngateway start: ok\nok",
        "gateway_status_ok": True,
    }
    assert commands == [
        ["openclaw", "gateway", "restart"],
        ["openclaw", "gateway", "start"],
    ]
