"""
Maestro configuration — centralized defaults and environment handling.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Gemini Models ─────────────────────────────────────────────────────────────

INGEST_MODEL = "gemini-3-flash-preview"
HIGHLIGHT_MODEL = "gemini-3-flash-preview"
IMAGE_GEN_MODEL = "gemini-3-pro-image-preview"

# ── Ingest Defaults ───────────────────────────────────────────────────────────

DEFAULT_DPI = 200
DEFAULT_THINKING_LEVEL = "high"
MAX_GEMINI_BYTES = 9 * 1024 * 1024  # 9 MB safety margin for image uploads

# ── Bbox ──────────────────────────────────────────────────────────────────────

BBOX_SCALE = 1000  # Gemini uses 0-1000 normalized coordinate space

# ── Paths ─────────────────────────────────────────────────────────────────────

DEFAULT_STORE_DIR = "knowledge_store"
THUMBNAIL_CACHE_DIR = ".cache"


def get_gemini_api_key() -> str | None:
    """Get Gemini API key from environment."""
    return os.environ.get("GEMINI_API_KEY")


def get_store_path(override: str | Path | None = None) -> Path:
    """Resolve knowledge store path from override or environment or default."""
    if override:
        return Path(override)
    env = os.environ.get("MAESTRO_STORE")
    if env:
        return Path(env)
    return Path(DEFAULT_STORE_DIR)


def load_dotenv(workspace: Path | None = None):
    """Load .env file from workspace or cwd."""
    candidates = []
    if workspace:
        candidates.append(workspace / ".env")
    candidates.append(Path(".env"))

    for env_path in candidates:
        if env_path.exists():
            with env_path.open() as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
            return
