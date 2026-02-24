"""Templates/helpers for Maestro Solo workspace files."""

from __future__ import annotations


def provider_env_key_for_model(model: str | None) -> str | None:
    if not isinstance(model, str) or not model.strip():
        return None

    lowered = model.strip().lower()
    if lowered.startswith("openai/") or lowered.startswith("openai-codex/"):
        return "OPENAI_API_KEY"
    if lowered.startswith("google/") or lowered.startswith("gemini/"):
        return "GEMINI_API_KEY"
    if lowered.startswith("anthropic/"):
        return "ANTHROPIC_API_KEY"
    return None


def render_personal_agents_md() -> str:
    return (
        "# AGENTS.md — Maestro Solo Personal\n\n"
        "## Every Session\n"
        "1. Read `SOUL.md`\n"
        "2. Read `IDENTITY.md`\n"
        "3. Read `USER.md`\n"
        "4. Check `knowledge_store/`\n\n"
        "## Role\n"
        "You are a project-capable personal Maestro Solo agent.\n"
        "You answer plan questions, maintain workspaces, and manage schedule tasks.\n\n"
        "## Tooling Scope\n"
        "- Use project knowledge tools in this workspace\n"
        "- Use workspace and schedule tools to track progress\n"
    )


def render_company_agents_md() -> str:
    """Compatibility shim for legacy doctor/update paths."""
    return render_personal_agents_md()


def render_personal_tools_md(active_provider_env_key: str | None = None) -> str:
    provider_line = (
        f"- `{active_provider_env_key}` — Active default model key\n"
        if active_provider_env_key
        else "- Model provider key — see openclaw.json\n"
    )
    return (
        "# TOOLS.md — Maestro Solo Personal\n\n"
        "## Role\n"
        "- **Mode:** Solo\n"
        "- **Agent:** `maestro-solo-personal`\n"
        "- **Purpose:** Project reasoning + workspace + schedule management\n\n"
        "## Core Commands\n"
        "- `maestro-solo up --tui`\n"
        "- `maestro-solo ingest <path-to-pdfs>`\n"
        "- `maestro-solo doctor --fix`\n"
        "- `maestro-solo migrate-legacy`\n\n"
        "## UI\n"
        "- **Workspace:** http://localhost:3000/workspace\n\n"
        "## Environment Variables\n"
        f"{provider_line}"
        "- `MAESTRO_AGENT_ROLE` — `project` in Solo\n"
        "- `MAESTRO_STORE` — active knowledge store root\n"
        "- `OPENAI_API_KEY` — Optional provider key\n"
        "- `GEMINI_API_KEY` — Optional (required for vision/image features)\n"
        "- `ANTHROPIC_API_KEY` — Optional provider key\n"
    )


def render_tools_md(company_name: str, active_provider_env_key: str | None = None) -> str:
    """Compatibility shim for legacy doctor/update paths."""
    _ = company_name
    return render_personal_tools_md(active_provider_env_key=active_provider_env_key)


def render_workspace_env(
    *,
    store_path: str = "knowledge_store/",
    provider_env_key: str | None = None,
    provider_key: str | None = None,
    gemini_key: str | None = None,
    agent_role: str | None = None,
    model_auth_method: str | None = None,
) -> str:
    lines = ["# Maestro Solo Environment"]

    active_env_key = provider_env_key.strip() if isinstance(provider_env_key, str) and provider_env_key.strip() else ""
    active_key = provider_key.strip() if isinstance(provider_key, str) and provider_key.strip() else ""
    if active_env_key and active_key:
        lines.append(f"{active_env_key}={active_key}")

    gem_key = gemini_key.strip() if isinstance(gemini_key, str) and gemini_key.strip() else ""
    if active_env_key != "GEMINI_API_KEY" and gem_key:
        lines.append(f"GEMINI_API_KEY={gem_key}")

    role = agent_role.strip().lower() if isinstance(agent_role, str) and agent_role.strip() else ""
    if role:
        lines.append(f"MAESTRO_AGENT_ROLE={role}")

    auth_method = (
        model_auth_method.strip().lower()
        if isinstance(model_auth_method, str) and model_auth_method.strip()
        else ""
    )
    if auth_method:
        lines.append(f"MAESTRO_MODEL_AUTH_METHOD={auth_method}")

    clean_store = store_path.strip() if isinstance(store_path, str) and store_path.strip() else "knowledge_store/"
    lines.append(f"MAESTRO_STORE={clean_store}")
    return "\n".join(lines) + "\n"
