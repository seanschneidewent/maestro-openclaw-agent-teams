"""Shared templates/helpers for Maestro workspace files."""

from __future__ import annotations


def provider_env_key_for_model(model: str | None) -> str | None:
    """Resolve the required provider env key for a model id."""
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


def render_tools_md(company_name: str, active_provider_env_key: str | None = None) -> str:
    provider_line = (
        f"- `{active_provider_env_key}` — Active default model key\n"
        if active_provider_env_key
        else "- Model provider key — see openclaw.json\n"
    )
    clean_name = company_name.strip() if isinstance(company_name, str) and company_name.strip() else "Company"
    return (
        "# TOOLS.md — The Commander\n\n"
        "## Company\n"
        f"- **Name:** {clean_name}\n"
        "- **Role:** The Commander — control-plane orchestrator\n"
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
        "- `MAESTRO_AGENT_ROLE` — `company` for commander workspace, `project` for project nodes\n"
        "- `OPENAI_API_KEY` — Optional provider key\n"
        "- `GEMINI_API_KEY` — Optional provider key (also used for plan vision)\n"
        "- `ANTHROPIC_API_KEY` — Optional provider key\n"
    )


def render_company_agents_md() -> str:
    """Render AGENTS.md for the default Commander workspace."""
    return (
        "# AGENTS.md — The Commander\n\n"
        "## Every Session\n"
        "1. Read `SOUL.md`\n"
        "2. Read `IDENTITY.md`\n"
        "3. Read `USER.md`\n"
        "4. Read `TOOLS.md`\n\n"
        "## Role\n"
        "You are The Commander control-plane orchestrator.\n"
        "You coordinate project maestros, system health, and command-center operations.\n\n"
        "## Hard Boundary\n"
        "- Do not inspect or enumerate project plan files under `knowledge_store/`\n"
        "- Do not run project knowledge tools from this workspace\n"
        "- Do not answer plan-detail questions directly from filesystem data\n"
        "- For project content, route to the assigned project maestro node\n\n"
        "## What You Can Do\n"
        "- Create and register project maestros\n"
        "- Generate exact ingest/index/start commands for project nodes\n"
        "- Diagnose runtime issues (`maestro doctor --fix`)\n"
        "- Keep command center and fleet registry healthy\n\n"
        "## Messaging Discipline\n"
        "- One complete response per turn\n"
        "- If project context is requested, ask which project node should handle it\n"
    )


def render_personal_agents_md() -> str:
    """Render AGENTS.md for a Solo personal workspace."""
    return (
        "# AGENTS.md — Maestro Personal\n\n"
        "## Every Session\n"
        "1. Read `SOUL.md`\n"
        "2. Read `IDENTITY.md`\n"
        "3. Read `USER.md`\n"
        "4. Check `knowledge_store/`\n\n"
        "## Role\n"
        "You are a project-capable personal Maestro agent.\n"
        "You answer plan questions, maintain workspaces, and manage schedule tasks.\n\n"
        "## Tooling Rules (Critical)\n"
        "1. Use native Maestro tools (`maestro_*`) first for all project/workspace/schedule work.\n"
        "2. Do not use browser/web tools for plan tasks when a Maestro tool exists.\n"
        "3. Do not inspect Maestro source code to discover normal product behavior.\n"
        "4. Do not run recursive filesystem scans across `knowledge_store/` for answers.\n"
        "5. Use shell only for narrow runtime diagnostics with bounded output.\n\n"
        "Hard guardrails:\n"
        "- Never dump `pass1.json` or `pass2.json` blobs into context.\n"
        "- Never use broad `grep -R` / `find` as a substitute for Maestro tools.\n"
        "- Never open external browser automation for workspace plan operations.\n\n"
        "Highlight guardrails:\n"
        "- Never use `canvas`/`nodes` for plan row highlighting.\n"
        "- Never guess bbox coordinates; use evidence from the page image.\n\n"
        "## Tooling Scope\n"
        "- Use project knowledge tools in this workspace\n"
        "- Use workspace and schedule tools to track progress\n"
        "- If user asks for fleet orchestration, guide them to `maestro fleet enable`\n"
    )


def render_personal_tools_md(active_provider_env_key: str | None = None) -> str:
    provider_line = (
        f"- `{active_provider_env_key}` — Active default model key\n"
        if active_provider_env_key
        else "- Model provider key — see openclaw.json\n"
    )
    return (
        "# TOOLS.md — Maestro Personal\n\n"
        "## Role\n"
        "- **Mode:** Solo\n"
        "- **Agent:** `maestro-personal`\n"
        "- **Purpose:** Project reasoning + workspace + schedule management\n\n"
        "## Core Commands\n"
        "- `maestro-solo up --tui`\n"
        "- `maestro ingest <path-to-pdfs>`\n"
        "- `maestro doctor --fix`\n"
        "- `maestro update`\n\n"
        "## UI\n"
        "- **Workspace:** http://localhost:3000/workspace\n\n"
        "## Native Agent Tools (Direct)\n"
        "### Project\n"
        "- `maestro_project_context`\n"
        "- `maestro_get_access_urls`\n"
        "- `maestro_list_pages`\n"
        "- `maestro_search`\n"
        "- `maestro_get_sheet_summary`\n"
        "- `maestro_list_regions`\n"
        "- `maestro_get_region_detail`\n"
        "- `maestro_find_cross_references`\n\n"
        "### Workspaces\n"
        "- `maestro_list_workspaces`\n"
        "- `maestro_get_workspace`\n"
        "- `maestro_create_workspace`\n"
        "- `maestro_add_page`\n"
        "- `maestro_remove_page`\n"
        "- `maestro_select_pointers`\n"
        "- `maestro_deselect_pointers`\n"
        "- `maestro_add_description`\n"
        "- `maestro_set_custom_highlight`\n"
        "- `maestro_clear_custom_highlights`\n\n"
        "### Project Notes (Project-wide)\n"
        "- `maestro_get_project_notes`\n"
        "- `maestro_upsert_note_category`\n"
        "- `maestro_add_note`\n"
        "- `maestro_update_note_state`\n\n"
        "### Schedule (Project-wide)\n"
        "- `maestro_get_schedule_status`\n"
        "- `maestro_get_schedule_timeline`\n"
        "- `maestro_list_schedule_items`\n"
        "- `maestro_upsert_schedule_item`\n"
        "- `maestro_set_schedule_constraint`\n"
        "- `maestro_close_schedule_item`\n\n"
        "## Execution Guardrails\n"
        "- Use native Maestro tools above before any generic shell/file operations.\n"
        "- Do not call browser/web tools for plan discovery, workspace edits, or schedule updates.\n"
        "- Do not use `canvas` or `nodes` for plan highlighting/navigation.\n"
        "- Do not recursively scan `knowledge_store/` with `grep -R` or `find` for normal Q&A.\n"
        "- Do not dump large JSON files (`pass1.json`, `pass2.json`) into model context.\n"
        "- For row-level highlights, get bbox from image evidence; do not estimate coordinates.\n"
        "- If a helper command is missing, stay on Maestro tools instead of broad fallback scans.\n\n"
        "## Optional Fleet\n"
        "- Enable enterprise mode when needed: `maestro fleet enable`\n"
        "- Command Center (fleet only): `/command-center`\n\n"
        "## Environment Variables\n"
        f"{provider_line}"
        "- `MAESTRO_AGENT_ROLE` — `project` in Solo\n"
        "- `MAESTRO_STORE` — active knowledge store root\n"
        "- `OPENAI_API_KEY` — Optional provider key\n"
        "- `GEMINI_API_KEY` — Optional (required for vision/image features)\n"
        "- `ANTHROPIC_API_KEY` — Optional provider key\n"
    )


def render_workspace_env(
    *,
    store_path: str = "knowledge_store/",
    provider_env_key: str | None = None,
    provider_key: str | None = None,
    gemini_key: str | None = None,
    agent_role: str | None = None,
    model_auth_method: str | None = None,
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
