from __future__ import annotations

from argparse import Namespace

from maestro_solo.install_journey import InstallJourneyOptions, run_install_journey


def _opts(**overrides) -> InstallJourneyOptions:
    payload = {
        "flow": "free",
        "intent": "",
        "channel": "core",
        "solo_home": "/tmp/maestro-solo",
        "billing_url": "https://billing.example.com",
        "plan_id": "solo_monthly",
        "purchase_email": "",
        "force_pro_purchase": False,
        "replay_setup": True,
        "openclaw_profile": "maestro-solo",
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


def test_journey_install_intent_pro_can_be_skipped(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.delenv("MAESTRO_INSTALL_AUTO", raising=False)
    monkeypatch.setattr("maestro_solo.install_journey._has_existing_setup", lambda _solo_home: False)
    monkeypatch.setattr("maestro_solo.install_journey._resolve_purchase_email", lambda **_: "you@example.com")
    monkeypatch.setattr("maestro_solo.install_journey.Confirm.ask", lambda *_args, **_kwargs: False)

    def _fake_run(args: list[str], *, options: InstallJourneyOptions) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setattr("maestro_solo.install_journey._run_cli_stream", _fake_run)

    code = run_install_journey(_opts(flow="install", intent="pro", channel="pro"))
    assert code == 0
    assert ["auth", "login", "--billing-url", "https://billing.example.com"] not in calls
    assert any(cmd[:2] == ["purchase", "--email"] and "--preview" in cmd for cmd in calls)
    assert calls[-1] == ["up", "--tui"]


def test_journey_install_intent_pro_runs_pro_path_when_confirmed(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.delenv("MAESTRO_INSTALL_AUTO", raising=False)
    monkeypatch.setattr("maestro_solo.install_journey._has_existing_setup", lambda _solo_home: False)
    monkeypatch.setattr("maestro_solo.install_journey._pro_entitlement_active", lambda: (False, "", ""))
    monkeypatch.setattr("maestro_solo.install_journey._resolve_purchase_email", lambda **_: "buyer@example.com")
    monkeypatch.setattr("maestro_solo.install_journey.Confirm.ask", lambda *_args, **_kwargs: True)

    def _fake_run(args: list[str], *, options: InstallJourneyOptions) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setattr("maestro_solo.install_journey._run_cli_stream", _fake_run)

    code = run_install_journey(_opts(flow="install", intent="pro", channel="pro"))
    assert code == 0
    assert ["auth", "login", "--billing-url", "https://billing.example.com"] in calls
    real_calls = [cmd for cmd in calls if cmd and cmd[0] == "purchase" and "--preview" not in cmd]
    assert len(real_calls) == 1


def test_journey_install_intent_pro_auto_approve_skips_prompt(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setenv("MAESTRO_INSTALL_AUTO", "1")
    monkeypatch.setattr("maestro_solo.install_journey._has_existing_setup", lambda _solo_home: False)
    monkeypatch.setattr("maestro_solo.install_journey._pro_entitlement_active", lambda: (False, "", ""))
    monkeypatch.setattr("maestro_solo.install_journey._resolve_purchase_email", lambda **_: "buyer@example.com")

    def _should_not_prompt(*_args, **_kwargs):
        raise AssertionError("Confirm.ask should not run when MAESTRO_INSTALL_AUTO=1")

    monkeypatch.setattr("maestro_solo.install_journey.Confirm.ask", _should_not_prompt)

    def _fake_run(args: list[str], *, options: InstallJourneyOptions) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setattr("maestro_solo.install_journey._run_cli_stream", _fake_run)

    code = run_install_journey(_opts(flow="install", intent="pro", channel="pro"))
    assert code == 0
    assert ["auth", "login", "--billing-url", "https://billing.example.com"] in calls
    real_calls = [cmd for cmd in calls if cmd and cmd[0] == "purchase" and "--preview" not in cmd]
    assert len(real_calls) == 1


def test_options_from_env_and_args_auto_channel_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path / "solo-home"))
    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-solo")

    from maestro_solo.install_journey import options_from_env_and_args

    args = Namespace(
        flow="install",
        intent="pro",
        channel="auto",
        billing_url="https://billing.example.com/",
        plan="solo_monthly",
        email="owner@example.com",
        force_pro_purchase=False,
        no_replay_setup=False,
    )
    opts = options_from_env_and_args(args)
    assert opts.flow == "install"
    assert opts.intent == "pro"
    assert opts.channel == "pro"
    assert opts.solo_home == str((tmp_path / "solo-home").resolve())
    assert opts.openclaw_profile == "maestro-solo"
    assert opts.replay_setup is True


def test_options_from_env_and_args_invalid_values_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("MAESTRO_SOLO_HOME", str(tmp_path / "solo-home"))
    monkeypatch.setenv("MAESTRO_INSTALL_INTENT", "core")

    from maestro_solo.install_journey import options_from_env_and_args

    args = Namespace(
        flow="weird",
        intent="",
        channel="broken",
        billing_url="",
        plan="solo_monthly",
        email="",
        force_pro_purchase=False,
        no_replay_setup=True,
    )
    opts = options_from_env_and_args(args)
    assert opts.flow == "free"
    assert opts.intent == "free"
    assert opts.channel == "core"
    assert opts.replay_setup is False
