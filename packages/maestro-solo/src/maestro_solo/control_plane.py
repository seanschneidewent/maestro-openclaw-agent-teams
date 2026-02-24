"""Solo control-plane compatibility helpers."""

from __future__ import annotations

from typing import Any

from maestro_engine.network import resolve_network_urls


def _telegram_account_ids(config: dict[str, Any]) -> list[str]:
    channels = config.get("channels", {}) if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        return []
    accounts = telegram.get("accounts")
    if not isinstance(accounts, dict):
        return []

    ids: list[str] = []
    for key, value in accounts.items():
        if not isinstance(value, dict):
            continue
        account_id = str(key).strip()
        if account_id:
            ids.append(account_id)
    return ids


def ensure_telegram_account_bindings(config: dict[str, Any]) -> list[str]:
    """Ensure each Telegram account has a matching OpenClaw binding."""
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    known_agent_ids = {
        str(agent.get("id", "")).strip()
        for agent in agent_list
        if isinstance(agent, dict) and str(agent.get("id", "")).strip()
    }

    account_ids = _telegram_account_ids(config)
    if not account_ids:
        return []

    bindings = config.get("bindings")
    if not isinstance(bindings, list):
        bindings = []
        config["bindings"] = bindings

    existing_pairs: set[tuple[str, str, str]] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        agent_id = str(binding.get("agentId", "")).strip()
        match = binding.get("match")
        if not isinstance(match, dict):
            continue
        channel = str(match.get("channel", "")).strip().lower()
        account_id = str(match.get("accountId", "")).strip()
        if agent_id and channel and account_id:
            existing_pairs.add((agent_id, channel, account_id))

    changes: list[str] = []
    for account_id in account_ids:
        if account_id not in known_agent_ids:
            continue
        key = (account_id, "telegram", account_id)
        if key in existing_pairs:
            continue
        bindings.append(
            {
                "agentId": account_id,
                "match": {
                    "channel": "telegram",
                    "accountId": account_id,
                },
            }
        )
        existing_pairs.add(key)
        changes.append(f"Added Telegram binding: {account_id} -> telegram:{account_id}")

    return changes


__all__ = ["ensure_telegram_account_bindings", "resolve_network_urls"]
