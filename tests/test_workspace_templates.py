"""Tests for shared workspace template helpers."""

from __future__ import annotations

from pathlib import Path

import maestro.workspace_templates as workspace_templates

from maestro.workspace_templates import (
    provider_env_key_for_model,
    render_company_agents_md,
    render_company_identity_md,
    render_company_soul_md,
    render_company_user_md,
    render_project_agents_md,
    render_project_tools_md,
    render_tools_md,
    render_workspace_awareness_md,
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
    assert "Commander Behavior Contract" in content
    assert "maestro-fleet project create" in content
    assert "Existing project-store onboarding" in content
    assert "Existing project root means `project.json` plus populated `pages/`" in content
    assert "verify page count and pointer count before saying the project is ready" in content
    assert "Instruction Priority" in content
    assert "Tool Decision Rules" in content
    assert "Verification Evidence" in content
    assert "Stop And Ask Rules" in content
    assert "Worked Examples" in content
    assert "Use `AWARENESS.md` as the quick runtime summary for live URLs and access facts." in content
    assert "Use `.env`, OpenClaw config, and `project.json` for machine-readable state." in content


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
    assert "Read `AWARENESS.md` for current model + access URLs" in content
    assert "Do not ask whether the Commander should be set up." in content
    assert "company formation mode" in content
    assert "Do not inspect or enumerate project plan files under `knowledge_store/`" in content
    assert "Routing Rules" in content
    assert "project-detail questions" in content
    assert "existing project root, a multi-project store root, or a raw PDF folder" in content
    assert "Do not append `/<slug>` under a path that is already the real project root" in content
    assert "verify: resolved store path, nonzero page count, nonzero pointer count" in content
    assert "Session Operating Protocol" in content
    assert "Request Classification Rules" in content
    assert "Dependency Checks" in content
    assert "Completion Contract" in content
    assert "Stop Conditions" in content
    assert "High-Risk Examples" in content


def test_render_project_agents_md_reads_awareness_first():
    content = render_project_agents_md()
    assert "Read `AWARENESS.md` for current model + workspace URLs" in content
    assert "You are a project-scoped Maestro agent inside Fleet." in content
    assert "construction understanding" in content
    assert "synthesize concept evidence first" in content
    assert "If asked about company-wide orchestration, route to the Commander." in content


def test_render_project_tools_md_uses_awareness_for_workspace_url():
    content = render_project_tools_md(active_provider_env_key="OPENAI_API_KEY")
    assert "Read `AWARENESS.md` and use the recommended workspace URL." in content
    assert "`maestro_get_access_urls`" in content
    assert "`maestro_concept_trace`" in content
    assert "`maestro_governing_scope`" in content
    assert "`maestro_detect_conflicts`" in content
    assert "`OPENAI_API_KEY` — Active project model key" in content


def test_render_personal_tools_md_returns_solo_tools_content():
    from maestro.workspace_templates import render_personal_tools_md

    content = render_personal_tools_md(active_provider_env_key="OPENAI_API_KEY")
    assert content is not None
    assert "# TOOLS.md — Maestro Personal" in content
    assert "`OPENAI_API_KEY` — Active default model key" in content
    assert "`maestro_delete_workspace`" in content
    assert "`maestro_governing_scope`" in content
    assert "`maestro_detect_conflicts`" in content


def test_render_workspace_awareness_md_prefers_tailnet_when_available():
    content = render_workspace_awareness_md(
        model="openai/gpt-5.4",
        preferred_url="http://100.64.0.1:3000/alpha-project/",
        local_url="http://localhost:3000/alpha-project/",
        tailnet_url="http://100.64.0.1:3000/alpha-project/",
        store_root="/tmp/alpha-project",
    )
    assert "Recommended Workspace URL: `http://100.64.0.1:3000/alpha-project/`" in content
    assert "Tailnet Workspace URL: `http://100.64.0.1:3000/alpha-project/`" in content
    assert "Field Access Status: `ready`" in content
    assert "Use this file as a quick summary for model, network, and access-link questions." in content
    assert "If it conflicts with `.env`, OpenClaw config, or `project.json`, trust the machine-readable files." in content


def test_render_company_identity_files_describe_company_setup_role():
    soul = render_company_soul_md()
    identity = render_company_identity_md()
    user = render_company_user_md()

    assert "You are **The Commander**" in soul
    assert "Do not ask whether the commander should be set up." in soul
    assert "Prefer explicit checklists, classification, and verification over intuitive leaps" in soul
    assert "Use explicit dependency checks before taking actions that mutate config, routing, or project state" in soul
    assert "I am The Commander for this company." in identity
    assert "company-level Maestro orchestrator" in identity
    assert "Company Leadership" in user
    assert "Specialty teams desired" in user


def test_workspace_template_helpers_support_installed_package_layout(tmp_path: Path, monkeypatch):
    package_root = tmp_path / "site-packages" / "maestro"
    skill_dir = package_root / "agent" / "skills" / "commander"
    extension_dir = package_root / "agent" / "extensions" / "maestro-native-tools"
    skill_dir.mkdir(parents=True, exist_ok=True)
    extension_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Commander\n", encoding="utf-8")
    (extension_dir / "openclaw.plugin.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(workspace_templates, "__file__", str(package_root / "workspace_templates.py"))

    assert workspace_templates._skill_template_source("commander") == skill_dir
    assert workspace_templates._native_extension_source() == extension_dir
