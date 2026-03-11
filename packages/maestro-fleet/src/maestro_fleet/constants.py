"""Shared constants and model helpers for Maestro Fleet runtime and deploy flows.

Keep Fleet's customer-facing model choices here so deploy, provisioning, doctor,
and runtime UIs all stay in sync.
"""

from __future__ import annotations

from typing import Any

FLEET_PROFILE = "maestro-fleet"
FLEET_GATEWAY_PORT = 18789

KEY_ORDER = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")

DEFAULT_COMMANDER_MODEL = "openai/gpt-5.4"
DEFAULT_PROJECT_MODEL = DEFAULT_COMMANDER_MODEL

LEGACY_MODEL_ALIASES = {
    "openai/gpt-5.2": DEFAULT_COMMANDER_MODEL,
    "google/gemini-3-pro-preview": "google/gemini-3.1-pro-preview",
}

FLEET_MODEL_OPTIONS = (
    ("1", "anthropic/claude-opus-4-6", "Anthropic Claude Opus 4.6"),
    ("2", DEFAULT_COMMANDER_MODEL, "OpenAI GPT-5.4"),
    ("3", "google/gemini-3.1-pro-preview", "Google Gemini 3.1 Pro"),
)

MODEL_CHOICES = {choice: model for choice, model, _label in FLEET_MODEL_OPTIONS}

MODEL_LABELS = {model: label for _choice, model, label in FLEET_MODEL_OPTIONS}

PROJECT_MODEL_OPTIONS = (
    ("1", "inherit"),
    ("2", DEFAULT_COMMANDER_MODEL),
    ("3", "google/gemini-3.1-pro-preview"),
    ("4", "anthropic/claude-opus-4-6"),
)

KEY_LABELS = {
    "GEMINI_API_KEY": "Gemini key (Vertex/Gemini)",
    "OPENAI_API_KEY": "OpenAI API key",
    "ANTHROPIC_API_KEY": "Anthropic API key",
}

DEPLOY_STEP_TITLES = (
    "Prerequisites",
    "Commander + Project Models",
    "Company Profile",
    "Provider Keys",
    "Commander Telegram",
    "Initial Project Maestro",
    "Doctor + Runtime Health",
    "Commander Commissioning",
)


def canonicalize_model(model: Any, *, fallback: str = "") -> str:
    clean = str(model or "").strip()
    if not clean:
        return str(fallback or "").strip()
    return LEGACY_MODEL_ALIASES.get(clean, clean)


def model_label(model: Any) -> str:
    canonical = canonicalize_model(model)
    if not canonical:
        return "unknown"
    return MODEL_LABELS.get(canonical, canonical)


def format_model_display(model: Any) -> str:
    canonical = canonicalize_model(model)
    if not canonical:
        return "unknown"
    label = MODEL_LABELS.get(canonical, "")
    if not label:
        return canonical
    return f"{label} ({canonical})"


def default_model_from_agents(agent_list: list[dict[str, Any]], *, fallback: str = DEFAULT_PROJECT_MODEL) -> str:
    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        if agent.get("id") == "maestro-company":
            model = canonicalize_model(agent.get("model"))
            if model:
                return model
    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        model = canonicalize_model(agent.get("model"))
        if model:
            return model
    return canonicalize_model(fallback, fallback=DEFAULT_PROJECT_MODEL)
