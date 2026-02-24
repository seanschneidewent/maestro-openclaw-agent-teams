"""Tests for setup wizard OpenClaw OAuth profile detection."""

from __future__ import annotations

import json
from pathlib import Path

from maestro.setup_wizard import SetupWizard


def test_openclaw_oauth_profile_detected_from_auth_profiles_json(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    auth_profiles = home / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
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
    (home / ".openclaw" / "agents" / "main" / "agent").mkdir(parents=True, exist_ok=True)

    wizard = SetupWizard()
    assert wizard._openclaw_oauth_profile_exists("openai-codex") is False

