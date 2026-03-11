from __future__ import annotations

import json
from pathlib import Path

from maestro import fleet_deploy
from maestro.workspace_templates import render_workspace_env
from maestro_fleet.workspace import sync_company_workspace_runtime_files


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def test_commander_workspace_contract(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    state_root = home / ".openclaw-maestro-fleet"
    workspace = state_root / "workspace-maestro"
    config_path = state_root / "openclaw.json"
    _write_json(
        config_path,
        {
            "env": {},
            "agents": {"list": []},
            "channels": {"telegram": {"enabled": True, "accounts": {}}},
        },
    )

    monkeypatch.setenv("MAESTRO_OPENCLAW_PROFILE", "maestro-fleet")
    monkeypatch.setattr(
        fleet_deploy,
        "_load_openclaw_config",
        lambda: (json.loads(config_path.read_text(encoding="utf-8")), config_path),
    )
    monkeypatch.setattr(fleet_deploy, "openclaw_workspace_root", lambda enforce_profile=True: workspace)
    monkeypatch.setattr(
        fleet_deploy,
        "ensure_openclaw_override_allowed",
        lambda config, allow_override=False: (True, ""),
    )

    result = fleet_deploy._configure_company_openclaw(
        model="openai/gpt-5.4",
        api_key="sk-test-openai-key",
        telegram_token="123456:ABCDEF",
        allow_openclaw_override=False,
    )

    assert result["workspace_root"] == str(workspace)

    env_path = workspace / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(
        render_workspace_env(
            store_path="knowledge_store/",
            provider_env_key="OPENAI_API_KEY",
            provider_key="sk-test-openai-key",
            agent_role="company",
        ),
        encoding="utf-8",
    )

    sync_result = sync_company_workspace_runtime_files(
        workspace=workspace,
        model="openai/gpt-5.4",
        company_name="Acme Co",
        store_root="knowledge_store/",
        generated_by="characterization",
        resolve_network_urls_fn=lambda **kwargs: {
            "recommended_url": "http://localhost:3000/command-center",
            "localhost_url": "http://localhost:3000/command-center",
            "tailnet_url": "",
        },
        active_provider_env_key="OPENAI_API_KEY",
        dry_run=False,
    )

    assert sync_result == {
        "awareness_updated": True,
        "agents_updated": True,
        "tools_updated": True,
        "commander_skill_synced": True,
        "maestro_skill_removed": False,
        "native_extension_synced": True,
    }

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["agents"]["list"] == [
        {
            "id": "maestro-company",
            "name": "The Commander",
            "default": True,
            "model": "openai/gpt-5.4",
            "workspace": str(workspace),
        }
    ]
    assert config["gateway"]["mode"] == "local"
    assert config["gateway"]["remote"]["url"] == "ws://127.0.0.1:18789"
    assert config["channels"]["telegram"]["accounts"]["maestro-company"] == {
        "botToken": "123456:ABCDEF",
        "dmPolicy": "pairing",
        "groupPolicy": "allowlist",
        "streamMode": "partial",
    }

    env = _read_env(env_path)
    assert env == {
        "OPENAI_API_KEY": "sk-test-openai-key",
        "MAESTRO_AGENT_ROLE": "company",
        "MAESTRO_STORE": "knowledge_store/",
    }

    files = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file())
    assert "skills/commander/SKILL.md" in files
    assert "skills/commander/references/maestro-project.md" in files
    assert "TOOLS.md" in files
    assert "AGENTS.md" in files
    assert "AWARENESS.md" in files
    assert ".openclaw/extensions/maestro-native-tools/openclaw.plugin.json" in files
    assert not any(path.startswith("skills/maestro/") for path in files)
