"""Tests for maestro-purchase workflow."""

from __future__ import annotations

import json
from pathlib import Path

import maestro.purchase as purchase


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _base_config(workspace: Path) -> dict:
    return {
        "env": {"OPENAI_API_KEY": "sk-test-openai-key"},
        "agents": {
            "list": [
                {
                    "id": "maestro-company",
                    "name": "Maestro (TestCo)",
                    "default": True,
                    "model": "openai/gpt-5.2",
                    "workspace": str(workspace),
                }
            ]
        },
        "channels": {"telegram": {"enabled": True, "accounts": {}}},
    }


def test_run_purchase_non_interactive_dry_run(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    store_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        purchase,
        "_load_openclaw_config",
        lambda: (config, config_path),
    )
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    monkeypatch.setattr(purchase, "_load_billing_state", lambda: {"card_on_file": True, "card_last4": "4242"})

    code = purchase.run_purchase(
        project_name="Alpha Build",
        assignee="Mike",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=True,
        skip_remote_validation=True,
    )

    assert code == 0
    assert not (store_root / "alpha-build").exists()


def test_run_purchase_requires_license_after_free_slot(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    existing = store_root / "existing-project"
    existing.mkdir(parents=True, exist_ok=True)
    _write_json(existing / "project.json", {"name": "Existing Project", "slug": "existing-project"})

    monkeypatch.setattr(
        purchase,
        "_load_openclaw_config",
        lambda: (config, config_path),
    )
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    monkeypatch.setattr(purchase, "_load_billing_state", lambda: {"card_on_file": False})

    code = purchase.run_purchase(
        project_name="Second Project",
        assignee="Sarah",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=True,
        skip_remote_validation=True,
    )
    assert code == 1


def test_run_purchase_paid_slot_auto_activates_maestro_license(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    existing = store_root / "existing-project"
    existing.mkdir(parents=True, exist_ok=True)
    _write_json(existing / "project.json", {"name": "Existing Project", "slug": "existing-project"})

    monkeypatch.setattr(
        purchase,
        "_load_openclaw_config",
        lambda: (config, config_path),
    )
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    monkeypatch.setattr(purchase, "_load_billing_state", lambda: {"card_on_file": True, "card_last4": "4242"})

    code = purchase.run_purchase(
        project_name="Second Project",
        assignee="Sarah",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=True,
        skip_remote_validation=True,
    )
    assert code == 0


def test_card_on_file_retry_loop(monkeypatch, tmp_path: Path):
    # First attempt invalid expiry, second attempt valid.
    answers = iter([
        "Sean",
        "1234",
        "1234",  # invalid MM/YY
        "Sean",
        "1234",
        "12/34",  # valid MM/YY pattern
    ])

    monkeypatch.setattr(purchase, "_load_billing_state", lambda: {"card_on_file": False})
    saved_payload = {}

    def _capture_save(state):
        saved_payload.update(state)

    monkeypatch.setattr(purchase, "_save_billing_state", _capture_save)
    monkeypatch.setattr(purchase.Prompt, "ask", lambda *args, **kwargs: next(answers))

    confirm_answers = iter([True, True])  # add card now, retry after invalid expiry
    monkeypatch.setattr(purchase.Confirm, "ask", lambda *args, **kwargs: next(confirm_answers))

    state, ok = purchase._ensure_card_on_file(non_interactive=False, dry_run=False)
    assert ok is True
    assert state["card_on_file"] is True
    assert saved_payload["card_expiry"] == "12/34"


def test_run_purchase_preserves_registered_project_agent(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = home / ".openclaw" / "workspace-maestro"
    config_path = home / ".openclaw" / "openclaw.json"
    config = _base_config(workspace)
    _write_json(config_path, config)

    store_root = tmp_path / "store-root"
    store_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(purchase.Path, "home", staticmethod(lambda: home))

    def _fake_create_project_node(**kwargs):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        agents = payload.setdefault("agents", {}).setdefault("list", [])
        agents.append({
            "id": "maestro-project-alpha-build",
            "name": "Maestro (Alpha Build)",
            "default": False,
            "model": "openai/gpt-5.2",
            "workspace": str(workspace / "projects" / "alpha-build"),
        })
        config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "project": {"project_store_path": str(store_root / "alpha-build")},
            "agent_registration": {"workspace": str(workspace / "projects" / "alpha-build")},
        }

    monkeypatch.setattr(purchase, "create_project_node", _fake_create_project_node)
    monkeypatch.setattr(purchase, "resolve_fleet_store_root", lambda _: store_root)
    monkeypatch.setattr(purchase, "project_control_payload", lambda *args, **kwargs: {"ingest": {"command": "maestro ingest"}})
    monkeypatch.setattr(purchase, "_restart_openclaw_gateway", lambda **kwargs: {"ok": True, "detail": "ok"})
    monkeypatch.setattr(purchase, "_validate_api_key", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(purchase, "_validate_telegram_token", lambda *args, **kwargs: (True, "alpha_bot", "ok"))

    code = purchase.run_purchase(
        project_name="Alpha Build",
        assignee="Andy",
        telegram_token="123456:ABCDEF",
        non_interactive=True,
        dry_run=False,
        skip_remote_validation=True,
    )
    assert code == 0

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    agent_ids = [a.get("id") for a in saved.get("agents", {}).get("list", []) if isinstance(a, dict)]
    assert "maestro-company" in agent_ids
    assert "maestro-project-alpha-build" in agent_ids
    assert "maestro-project-alpha-build" in saved.get("channels", {}).get("telegram", {}).get("accounts", {})
