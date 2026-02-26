"""Pure transforms for Maestro Solo OpenClaw config updates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SoloConfigTransformRequest:
    workspace: str
    model: str
    gemini_key: str
    telegram_token: str
    native_plugin_enabled: bool
    native_plugin_id: str
    native_plugin_deny_tools: tuple[str, ...]
    agent_id: str = "maestro-solo-personal"
    agent_name: str = "Maestro Solo Personal"
    provider_env_key: str = ""
    provider_key: str = ""
    provider_auth_method: str = ""
    clear_env_keys: tuple[str, ...] = ("OPENAI_API_KEY",)
    remove_agent_ids: tuple[str, ...] = ("maestro", "maestro-personal", "maestro-solo-personal")


def _as_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return deepcopy(payload)


def transform_openclaw_config(
    current: dict[str, Any] | None,
    *,
    request: SoloConfigTransformRequest,
) -> dict[str, Any]:
    """Return a transformed config without side effects."""
    config = _as_config(current)

    gateway = config.get("gateway") if isinstance(config.get("gateway"), dict) else {}
    gateway["mode"] = "local"
    config["gateway"] = gateway
    config.pop("maestro", None)

    env = config.get("env") if isinstance(config.get("env"), dict) else {}
    for key in request.clear_env_keys:
        clean = str(key or "").strip()
        if clean:
            env.pop(clean, None)

    provider_env_key = str(request.provider_env_key or "").strip()
    provider_key = str(request.provider_key or "").strip()
    provider_auth_method = str(request.provider_auth_method or "").strip().lower()
    if provider_env_key:
        if provider_key:
            env[provider_env_key] = provider_key
        elif provider_auth_method == "openclaw_oauth":
            env.pop(provider_env_key, None)

    gemini_key = str(request.gemini_key or "").strip()
    if gemini_key:
        env["GEMINI_API_KEY"] = gemini_key
    config["env"] = env

    agents = config.get("agents") if isinstance(config.get("agents"), dict) else {}
    existing = agents.get("list") if isinstance(agents.get("list"), list) else []
    remove_ids = {str(item).strip() for item in request.remove_agent_ids if str(item).strip()}

    clean_list: list[dict[str, Any]] = []
    for item in existing:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        if item_id in remove_ids:
            continue
        next_item = deepcopy(item)
        if next_item.get("default"):
            next_item["default"] = False
        clean_list.append(next_item)

    clean_list.append(
        {
            "id": request.agent_id,
            "name": request.agent_name,
            "default": True,
            "model": request.model,
            "workspace": request.workspace,
            "tools": {
                "deny": list(request.native_plugin_deny_tools),
            },
        }
    )
    agents["list"] = clean_list
    config["agents"] = agents

    plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    entries = plugins.get("entries") if isinstance(plugins.get("entries"), dict) else {}
    if request.native_plugin_enabled:
        plugin_entry = (
            entries.get(request.native_plugin_id)
            if isinstance(entries.get(request.native_plugin_id), dict)
            else {}
        )
        plugin_entry["enabled"] = True
        entries[request.native_plugin_id] = plugin_entry
    else:
        entries.pop(request.native_plugin_id, None)
    if entries:
        plugins["entries"] = entries
    else:
        plugins.pop("entries", None)

    allow = plugins.get("allow")
    if isinstance(allow, list):
        cleaned = [str(item).strip() for item in allow if str(item).strip()]
        if request.native_plugin_enabled:
            if request.native_plugin_id not in cleaned:
                cleaned.append(request.native_plugin_id)
        else:
            cleaned = [item for item in cleaned if item != request.native_plugin_id]
        if cleaned:
            plugins["allow"] = cleaned
        else:
            plugins.pop("allow", None)
    elif request.native_plugin_enabled:
        plugins["allow"] = [request.native_plugin_id]
    config["plugins"] = plugins

    telegram_token = str(request.telegram_token or "").strip()
    if telegram_token:
        channels = config.get("channels") if isinstance(config.get("channels"), dict) else {}
        channels["telegram"] = {
            "enabled": True,
            "botToken": telegram_token,
            "dmPolicy": "pairing",
            "groupPolicy": "allowlist",
            "streamMode": "partial",
            "accounts": {
                request.agent_id: {
                    "botToken": telegram_token,
                    "dmPolicy": "pairing",
                    "groupPolicy": "allowlist",
                    "streamMode": "partial",
                }
            },
        }
        config["channels"] = channels

    return config
