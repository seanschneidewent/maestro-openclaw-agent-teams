from __future__ import annotations

import json
from types import SimpleNamespace

from maestro_solo.setup_wizard import SetupWizard


def test_openclaw_oauth_profile_detected_from_auth_profiles_json(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    auth_profiles = home / ".openclaw-maestro-solo" / "agents" / "main" / "agent" / "auth-profiles.json"
    auth_profiles.parent.mkdir(parents=True, exist_ok=True)
    auth_profiles.write_text(
        json.dumps(
            {
                "version": 1,
                "profiles": {
                    "openai-codex:default": {
                        "type": "oauth",
                        "provider": "openai-codex",
                        "access": "access-token",
                        "refresh": "refresh-token",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    wizard = SetupWizard()
    assert wizard._openclaw_oauth_profile_exists("openai-codex") is True


def test_openclaw_oauth_profile_missing_returns_false(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    (home / ".openclaw-maestro-solo" / "agents" / "main" / "agent").mkdir(parents=True, exist_ok=True)

    wizard = SetupWizard()
    assert wizard._openclaw_oauth_profile_exists("openai-codex") is False


def test_setup_wizard_run_command_injects_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    captured: dict[str, str] = {}

    def _fake_run(cmd, shell, capture_output, text, check):  # noqa: ANN001
        captured["cmd"] = str(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("maestro_solo.setup_wizard.subprocess.run", _fake_run)

    wizard = SetupWizard()
    wizard.run_command("openclaw status", check=False)

    assert captured["cmd"] == "openclaw --profile maestro-solo status"


def test_setup_wizard_configure_openclaw_writes_isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    wizard = SetupWizard()
    wizard.progress.update(
        {
            "provider_env_key": "OPENAI_API_KEY",
            "provider_key": "",
            "provider_auth_method": "openclaw_oauth",
            "model": "openai-codex/gpt-5.2",
            "gemini_key": "GEMINI_KEY_FOR_TEST",
            "telegram_token": "",
        }
    )

    assert wizard.step_configure_openclaw() is True

    isolated = home / ".openclaw-maestro-solo" / "openclaw.json"
    shared = home / ".openclaw" / "openclaw.json"
    assert isolated.exists()
    assert not shared.exists()
