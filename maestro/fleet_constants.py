"""Shared constants for Maestro Fleet runtime and deploy flows."""

from __future__ import annotations

FLEET_PROFILE = "maestro-fleet"
FLEET_GATEWAY_PORT = 18789

KEY_ORDER = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")

MODEL_CHOICES = {
    "1": "anthropic/claude-opus-4-6",
    "2": "openai/gpt-5.2",
    "3": "google/gemini-3-pro-preview",
}

MODEL_LABELS = {
    "anthropic/claude-opus-4-6": "Anthropic Claude Opus 4.6",
    "openai/gpt-5.2": "OpenAI GPT-5.2",
    "google/gemini-3-pro-preview": "Google Gemini 3 Pro",
}

KEY_LABELS = {
    "GEMINI_API_KEY": "Gemini key (Vertex/Gemini)",
    "OPENAI_API_KEY": "OpenAI API key",
    "ANTHROPIC_API_KEY": "Anthropic API key",
}

# Ordered deploy step names for runbook + terminal output alignment.
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

