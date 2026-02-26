from __future__ import annotations

from maestro_solo.openclaw_config_transform import SoloConfigTransformRequest, transform_openclaw_config


def _request(**overrides) -> SoloConfigTransformRequest:
    payload = {
        "workspace": "/tmp/workspace-maestro-solo",
        "model": "openai-codex/gpt-5.2",
        "gemini_key": "GEMINI_KEY_FOR_TEST",
        "telegram_token": "123456:abcDEF123_token",
        "native_plugin_enabled": True,
        "native_plugin_id": "maestro-native-tools",
        "native_plugin_deny_tools": ("browser", "web_search"),
        "provider_env_key": "OPENAI_API_KEY",
        "provider_key": "",
        "provider_auth_method": "openclaw_oauth",
        "clear_env_keys": ("OPENAI_API_KEY",),
    }
    payload.update(overrides)
    return SoloConfigTransformRequest(**payload)


def test_transform_applies_gateway_agent_plugins_and_telegram():
    base = {
        "maestro": {"legacy": True},
        "env": {"OPENAI_API_KEY": "sk-legacy", "OTHER": "value"},
        "agents": {"list": [{"id": "main", "default": True}, {"id": "maestro", "default": True}]},
        "plugins": {"allow": ["existing"]},
    }

    transformed = transform_openclaw_config(base, request=_request())

    assert transformed["gateway"]["mode"] == "local"
    assert "maestro" not in transformed
    assert transformed["env"]["GEMINI_API_KEY"] == "GEMINI_KEY_FOR_TEST"
    assert "OPENAI_API_KEY" not in transformed["env"]
    assert transformed["env"]["OTHER"] == "value"

    agent_ids = [item.get("id") for item in transformed["agents"]["list"]]
    assert "maestro" not in agent_ids
    assert "maestro-solo-personal" in agent_ids
    assert transformed["agents"]["list"][0]["default"] is False

    assert transformed["plugins"]["entries"]["maestro-native-tools"]["enabled"] is True
    assert "maestro-native-tools" in transformed["plugins"]["allow"]
    assert transformed["channels"]["telegram"]["streamMode"] == "partial"
    assert transformed["channels"]["telegram"]["accounts"]["maestro-solo-personal"]["streamMode"] == "partial"


def test_transform_disables_native_plugin_without_touching_other_allow_entries():
    base = {
        "plugins": {
            "entries": {"maestro-native-tools": {"enabled": True}, "other-plugin": {"enabled": True}},
            "allow": ["maestro-native-tools", "other-plugin"],
        },
    }

    transformed = transform_openclaw_config(
        base,
        request=_request(native_plugin_enabled=False, telegram_token=""),
    )

    entries = transformed["plugins"]["entries"]
    assert "maestro-native-tools" not in entries
    assert "other-plugin" in entries
    assert transformed["plugins"]["allow"] == ["other-plugin"]
    assert "channels" not in transformed or "telegram" not in transformed.get("channels", {})


def test_transform_does_not_mutate_input_payload():
    base = {"env": {"OPENAI_API_KEY": "sk-old"}}
    request = _request()

    _ = transform_openclaw_config(base, request=request)

    assert base["env"]["OPENAI_API_KEY"] == "sk-old"
