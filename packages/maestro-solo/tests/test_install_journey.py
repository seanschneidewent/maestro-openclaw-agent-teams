from __future__ import annotations

from maestro_solo.install_journey import InstallJourneyOptions, run_install_journey


def _opts(**overrides) -> InstallJourneyOptions:
    payload = {
        "flow": "free",
        "channel": "core",
        "solo_home": "/tmp/maestro-solo",
        "billing_url": "https://billing.example.com",
        "plan_id": "solo_monthly",
        "purchase_email": "",
        "force_pro_purchase": False,
        "replay_setup": True,
    }
    payload.update(overrides)
    return InstallJourneyOptions(**payload)


def test_journey_free_replay_runs_all_step_commands(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("maestro_solo.install_journey._has_existing_setup", lambda _solo_home: True)
    monkeypatch.setattr("maestro_solo.install_journey._resolve_purchase_email", lambda **_: "you@example.com")

    def _fake_run(args: list[str], *, options: InstallJourneyOptions) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setattr("maestro_solo.install_journey._run_cli_stream", _fake_run)

    code = run_install_journey(_opts(flow="free"))
    assert code == 0
    assert calls[0] == ["setup", "--quick", "--replay"]
    assert ["auth", "status", "--billing-url", "https://billing.example.com"] in calls
    assert ["entitlements", "status"] in calls
    assert any(cmd[:2] == ["purchase", "--email"] and "--preview" in cmd for cmd in calls)
    assert calls[-1] == ["up", "--tui"]


def test_journey_pro_with_active_entitlement_skips_real_purchase(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("maestro_solo.install_journey._has_existing_setup", lambda _solo_home: True)
    monkeypatch.setattr("maestro_solo.install_journey._pro_entitlement_active", lambda: (True, "local_license", "2026-03-01T00:00:00Z"))
    monkeypatch.setattr("maestro_solo.install_journey._resolve_purchase_email", lambda **_: "owner@example.com")

    def _fake_run(args: list[str], *, options: InstallJourneyOptions) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setattr("maestro_solo.install_journey._run_cli_stream", _fake_run)

    code = run_install_journey(_opts(flow="pro", channel="pro"))
    assert code == 0
    assert ["auth", "login", "--billing-url", "https://billing.example.com"] in calls
    preview_calls = [cmd for cmd in calls if cmd and cmd[0] == "purchase" and "--preview" in cmd]
    assert len(preview_calls) == 1
    real_calls = [cmd for cmd in calls if cmd and cmd[0] == "purchase" and "--preview" not in cmd]
    assert len(real_calls) == 0


def test_journey_pro_fresh_runs_real_purchase(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("maestro_solo.install_journey._has_existing_setup", lambda _solo_home: False)
    monkeypatch.setattr("maestro_solo.install_journey._pro_entitlement_active", lambda: (False, "", ""))
    monkeypatch.setattr("maestro_solo.install_journey._resolve_purchase_email", lambda **_: "buyer@example.com")

    def _fake_run(args: list[str], *, options: InstallJourneyOptions) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setattr("maestro_solo.install_journey._run_cli_stream", _fake_run)

    code = run_install_journey(_opts(flow="pro", channel="pro"))
    assert code == 0
    assert calls[0] == ["setup", "--quick"]
    real_calls = [cmd for cmd in calls if cmd and cmd[0] == "purchase" and "--preview" not in cmd]
    assert len(real_calls) == 1
    assert real_calls[0][1:3] == ["--email", "buyer@example.com"]


def test_journey_replay_falls_back_to_preflight_when_setup_replay_fails(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("maestro_solo.install_journey._has_existing_setup", lambda _solo_home: True)
    monkeypatch.setattr("maestro_solo.install_journey._resolve_purchase_email", lambda **_: "you@example.com")

    def _fake_run(args: list[str], *, options: InstallJourneyOptions) -> int:
        calls.append(list(args))
        if args[:3] == ["setup", "--quick", "--replay"]:
            return 1
        return 0

    monkeypatch.setattr("maestro_solo.install_journey._run_cli_stream", _fake_run)

    code = run_install_journey(_opts(flow="free"))
    assert code == 0
    assert ["doctor", "--fix", "--no-restart"] in calls
