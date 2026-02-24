"""Tests for shared workspace template helpers."""

from __future__ import annotations

from maestro.workspace_templates import (
    provider_env_key_for_model,
    render_company_agents_md,
    render_tools_md,
    render_workspace_env,
)


def test_provider_env_key_for_model_mapping():
    assert provider_env_key_for_model("openai/gpt-5.2") == "OPENAI_API_KEY"
    assert provider_env_key_for_model("openai-codex/gpt-5.2") == "OPENAI_API_KEY"
    assert provider_env_key_for_model("google/gemini-3-pro-preview") == "GEMINI_API_KEY"
    assert provider_env_key_for_model("anthropic/claude-opus-4-6") == "ANTHROPIC_API_KEY"
    assert provider_env_key_for_model("unknown/model") is None


def test_render_tools_md_includes_active_provider():
    content = render_tools_md(company_name="TestCo", active_provider_env_key="OPENAI_API_KEY")
    assert "Name:** TestCo" in content
    assert "`OPENAI_API_KEY` — Active default model key" in content
    assert "http://<tailscale-ip>:3000/command-center" in content


def test_render_workspace_env_for_non_gemini_primary():
    content = render_workspace_env(
        store_path="knowledge_store/",
        provider_env_key="OPENAI_API_KEY",
        provider_key="sk-openai",
        gemini_key="gem-123",
    )
    assert "OPENAI_API_KEY=sk-openai" in content
    assert "GEMINI_API_KEY=gem-123" in content
    assert "MAESTRO_STORE=knowledge_store/" in content


def test_render_workspace_env_for_gemini_primary():
    content = render_workspace_env(
        store_path="knowledge_store/",
        provider_env_key="GEMINI_API_KEY",
        provider_key="gem-primary",
        gemini_key="gem-primary",
    )
    assert "GEMINI_API_KEY=gem-primary" in content
    # primary provider is Gemini, so no duplicated Gemini line
    assert content.count("GEMINI_API_KEY=") == 1


def test_render_workspace_env_includes_agent_role_when_set():
    content = render_workspace_env(
        store_path="knowledge_store/",
        provider_env_key="OPENAI_API_KEY",
        provider_key="sk-openai",
        agent_role="company",
    )
    assert "MAESTRO_AGENT_ROLE=company" in content


def test_render_workspace_env_includes_model_auth_method_when_set():
    content = render_workspace_env(
        store_path="knowledge_store/",
        provider_env_key="OPENAI_API_KEY",
        provider_key="",
        model_auth_method="openclaw_oauth",
    )
    assert "MAESTRO_MODEL_AUTH_METHOD=openclaw_oauth" in content
    assert "OPENAI_API_KEY=" not in content


def test_render_company_agents_md_has_control_plane_boundary():
    content = render_company_agents_md()
    assert "The Commander control-plane orchestrator" in content
    assert "Do not inspect or enumerate project plan files under `knowledge_store/`" in content
