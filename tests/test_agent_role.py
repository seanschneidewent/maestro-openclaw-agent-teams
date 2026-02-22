"""Tests for agent role resolution helpers."""

from __future__ import annotations

from pathlib import Path

from maestro.agent_role import (
    ROLE_COMPANY,
    ROLE_PROJECT,
    is_company_role,
    normalize_agent_role,
    resolve_agent_role,
)


def test_normalize_agent_role():
    assert normalize_agent_role("company") == ROLE_COMPANY
    assert normalize_agent_role(" PROJECT ") == ROLE_PROJECT
    assert normalize_agent_role("unknown") is None
    assert normalize_agent_role(None) is None


def test_resolve_agent_role_from_env_mapping():
    env = {"MAESTRO_AGENT_ROLE": "company"}
    assert resolve_agent_role(environ=env) == ROLE_COMPANY
    assert is_company_role(environ=env) is True


def test_resolve_agent_role_from_workspace_env_file(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".env").write_text("MAESTRO_AGENT_ROLE=project\n", encoding="utf-8")
    assert resolve_agent_role(workspace) == ROLE_PROJECT
    assert is_company_role(workspace) is False
