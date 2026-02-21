"""Shared templates/helpers for Maestro workspace files."""

from __future__ import annotations


def provider_env_key_for_model(model: str | None) -> str | None:
    """Resolve the required provider env key for a model id."""
    if not isinstance(model, str) or not model.strip():
        return None

    lowered = model.strip().lower()
    if lowered.startswith("openai/"):
        return "OPENAI_API_KEY"
    if lowered.startswith("google/") or lowered.startswith("gemini/"):
        return "GEMINI_API_KEY"
    if lowered.startswith("anthropic/"):
        return "ANTHROPIC_API_KEY"
    return None


def render_tools_md(company_name: str, active_provider_env_key: str | None = None) -> str:
    provider_line = (
        f"- `{active_provider_env_key}` — Active default model key\n"
        if active_provider_env_key
        else "- Model provider key — see openclaw.json\n"
    )
    clean_name = company_name.strip() if isinstance(company_name, str) and company_name.strip() else "Company"
    return (
        "# TOOLS.md — Company Maestro\n\n"
        "## Company\n"
        f"- **Name:** {clean_name}\n"
        "- **Role:** Company Maestro — orchestrator agent\n"
        "- **Status:** Active\n\n"
        "## What You Do\n"
        "- Manage project agents (create, monitor, archive)\n"
        "- Provide cross-project visibility via the Command Center\n"
        "- Handle billing and licensing conversations\n"
        "- Route questions to the right project agent\n\n"
        "## Key Paths\n"
        "- **Knowledge store:** `knowledge_store/`\n"
        "- **Command Center (tailnet):** http://<tailscale-ip>:3000/command-center\n"
        "- **Command Center (local):** http://localhost:3000/command-center\n\n"
        "## Provisioning\n"
        "- **Project maestro command:** `maestro-purchase`\n\n"
        "## Environment Variables\n"
        f"{provider_line}"
        "- `OPENAI_API_KEY` — Optional provider key\n"
        "- `GEMINI_API_KEY` — Optional provider key (also used for plan vision)\n"
        "- `ANTHROPIC_API_KEY` — Optional provider key\n"
    )


def render_workspace_env(
    *,
    store_path: str = "knowledge_store/",
    provider_env_key: str | None = None,
    provider_key: str | None = None,
    gemini_key: str | None = None,
) -> str:
    """Render the workspace .env file from setup/update state."""
    lines = ["# Maestro Environment"]

    active_env_key = provider_env_key.strip() if isinstance(provider_env_key, str) and provider_env_key.strip() else ""
    active_key = provider_key.strip() if isinstance(provider_key, str) and provider_key.strip() else ""
    if active_env_key and active_key:
        lines.append(f"{active_env_key}={active_key}")

    gem_key = gemini_key.strip() if isinstance(gemini_key, str) and gemini_key.strip() else ""
    if active_env_key != "GEMINI_API_KEY" and gem_key:
        lines.append(f"GEMINI_API_KEY={gem_key}")

    clean_store = store_path.strip() if isinstance(store_path, str) and store_path.strip() else "knowledge_store/"
    lines.append(f"MAESTRO_STORE={clean_store}")
    return "\n".join(lines) + "\n"
