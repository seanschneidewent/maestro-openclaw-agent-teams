"""
Maestro shared utilities — JSON parsing, bbox normalization, Gemini helpers.

These functions are shared between ingest, tools, and server modules.
Canonical implementations live here; no duplication.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import BBOX_SCALE


# ── JSON Parsing ──────────────────────────────────────────────────────────────

def clean_json_string(s: str) -> str:
    """Remove trailing commas before } or ] (common Gemini output artifact)."""
    return re.sub(r",\s*([}\]])", r"\1", s).strip()


def parse_json(text: str) -> dict:
    """
    Extract a JSON object from Gemini's text output.

    Handles: raw JSON, ```json code blocks, and brace-matched extraction.
    Returns empty dict on failure.
    """
    if not text:
        return {}
    s = text.strip()

    # Direct parse
    try:
        p = json.loads(s)
        if isinstance(p, dict):
            return p
    except json.JSONDecodeError:
        pass

    # Code block extraction
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)\n?```", s, re.DOTALL | re.IGNORECASE):
        try:
            p = json.loads(clean_json_string(m.group(1)))
            if isinstance(p, dict):
                return p
        except json.JSONDecodeError:
            continue

    # Brace match fallback
    start = s.find("{")
    end = s.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(clean_json_string(s[start:end]))
        except json.JSONDecodeError:
            pass

    return {}


def parse_json_list(text: str, list_key: str | None = None) -> list | None:
    """
    Extract a JSON list from Gemini's text output.

    If list_key is provided, looks for that key in a parsed dict.
    Also tries direct list parsing and bracket-matched extraction.
    Returns None on failure (distinct from empty list).
    """
    if not text:
        return None
    s = text.strip()

    def _extract(parsed):
        if isinstance(parsed, dict) and list_key:
            return parsed.get(list_key, [])
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and list_key:
            return parsed.get(list_key)
        return None

    # Direct parse
    try:
        p = json.loads(s)
        result = _extract(p)
        if result is not None:
            return result
    except json.JSONDecodeError:
        pass

    # Code block extraction
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)\n?```", s, re.DOTALL | re.IGNORECASE):
        try:
            p = json.loads(m.group(1).strip())
            result = _extract(p)
            if result is not None:
                return result
        except json.JSONDecodeError:
            continue

    # Brace match (object with list_key)
    start = s.find("{")
    end = s.rfind("}") + 1
    if start != -1 and end > start:
        try:
            p = json.loads(clean_json_string(s[start:end]))
            result = _extract(p)
            if result is not None:
                return result
        except json.JSONDecodeError:
            pass

    # Bracket match (direct list)
    start = s.find("[")
    end = s.rfind("]") + 1
    if start != -1 and end > start:
        try:
            p = json.loads(s[start:end])
            if isinstance(p, list):
                return p
        except json.JSONDecodeError:
            pass

    return None


# ── Bbox Normalization ────────────────────────────────────────────────────────

def _safe_int(v, default: int = 0) -> int:
    """Safely convert to int, returning default on failure."""
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def normalize_bbox(raw) -> dict[str, int]:
    """
    Convert Gemini's box_2d [ymin, xmin, ymax, xmax] or legacy {x0,y0,x1,y1}
    to normalized {x0, y0, x1, y1} in 0-1000 space.

    Gemini's native spatial format is [ymin, xmin, ymax, xmax].
    Our internal format is {x0, y0, x1, y1} where x=horizontal, y=vertical.
    """
    S = BBOX_SCALE

    if isinstance(raw, list) and len(raw) >= 4:
        # Gemini native: [ymin, xmin, ymax, xmax]
        ymin, xmin, ymax, xmax = (
            _safe_int(raw[0]), _safe_int(raw[1]),
            _safe_int(raw[2]), _safe_int(raw[3]),
        )
        x0, y0, x1, y1 = xmin, ymin, xmax, ymax
    elif isinstance(raw, dict):
        x0 = _safe_int(raw.get("x0"))
        y0 = _safe_int(raw.get("y0"))
        x1 = _safe_int(raw.get("x1"), S)
        y1 = _safe_int(raw.get("y1"), S)
    else:
        return {"x0": 0, "y0": 0, "x1": S, "y1": S}

    # Clamp to valid range
    x0, y0 = max(0, min(S, x0)), max(0, min(S, y0))
    x1, y1 = max(0, min(S, x1)), max(0, min(S, y1))

    # Ensure non-zero dimensions
    if x1 <= x0:
        x1 = min(S, x0 + 1)
    if y1 <= y0:
        y1 = min(S, y0 + 1)

    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def bbox_to_region_id(bbox: dict[str, int]) -> str:
    """Generate a deterministic region ID from a bbox."""
    return f"r_{bbox['x0']}_{bbox['y0']}_{bbox['x1']}_{bbox['y1']}"


def bbox_valid(bbox: dict[str, int] | None) -> bool:
    """Check if a bbox has non-zero area."""
    if not bbox:
        return False
    return (bbox.get("x1", 0) > bbox.get("x0", 0) and
            bbox.get("y1", 0) > bbox.get("y0", 0))


# ── Gemini Response Collection ────────────────────────────────────────────────

def collect_response(response) -> tuple[str, list[bytes], list[dict]]:
    """
    Collect text, images, and trace from a Gemini response.

    Returns:
        (text, images, trace) where:
        - text: joined non-thinking text parts
        - images: list of image bytes
        - trace: list of typed content dicts for debugging
    """
    text_parts: list[str] = []
    images: list[bytes] = []
    trace: list[dict] = []

    candidates = getattr(response, "candidates", []) or []
    if not candidates:
        return "", images, trace

    parts = getattr(getattr(candidates[0], "content", None), "parts", []) or []
    for part in parts:
        if getattr(part, "thought", None):
            trace.append({"type": "thought", "content": getattr(part, "text", "")})
            continue
        if (t := getattr(part, "text", None)) is not None:
            text_parts.append(t)
            trace.append({"type": "text", "content": t})
        if (code := getattr(part, "executable_code", None)) is not None:
            trace.append({"type": "code", "content": getattr(code, "code", "")})
        if (cr := getattr(part, "code_execution_result", None)) is not None:
            trace.append({"type": "code_result", "content": getattr(cr, "output", "") or ""})
        try:
            img = part.as_image()
            if img and img.image_bytes:
                images.append(bytes(img.image_bytes))
                trace.append({"type": "image", "index": len(images) - 1})
        except Exception:
            pass

    return "\n".join(text_parts), images, trace


def collect_text_only(response) -> str:
    """Collect only non-thinking text from a Gemini response."""
    text_parts = []
    candidates = getattr(response, "candidates", []) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", []) or []
        for part in parts:
            if getattr(part, "thought", None):
                continue
            if (t := getattr(part, "text", None)) is not None:
                text_parts.append(t)
    return "\n".join(text_parts).strip()


# ── Image Helpers ─────────────────────────────────────────────────────────────

def crop_region(image_path: Path, bbox: dict[str, int], output_path: Path, padding: int = 20):
    """Crop a region from a plan image using normalized bbox coordinates."""
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size
    S = BBOX_SCALE

    x0 = max(0, int((bbox["x0"] / S) * w) - padding)
    y0 = max(0, int((bbox["y0"] / S) * h) - padding)
    x1 = min(w, int((bbox["x1"] / S) * w) + padding)
    y1 = min(h, int((bbox["y1"] / S) * h) + padding)

    if x1 <= x0:
        x1 = min(w, x0 + 1)
    if y1 <= y0:
        y1 = min(h, y0 + 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.crop((x0, y0, x1, y1)).save(str(output_path))


def resize_for_gemini(png_path: Path, max_bytes: int | None = None) -> Path:
    """Resize an image if it exceeds Gemini's upload limit. Returns path to use."""
    from PIL import Image
    from .config import MAX_GEMINI_BYTES

    limit = max_bytes or MAX_GEMINI_BYTES
    if png_path.stat().st_size <= limit:
        return png_path

    resized = png_path.with_name("page_pass1.png")
    img = Image.open(png_path)
    w, h = img.size
    img.resize((w // 2, h // 2), Image.LANCZOS).save(resized, "PNG")

    if resized.stat().st_size > limit:
        img2 = Image.open(resized)
        w2, h2 = img2.size
        img2.resize((w2 // 2, h2 // 2), Image.LANCZOS).save(resized, "PNG")

    return resized


# ── File Helpers ──────────────────────────────────────────────────────────────

def load_json(path: Path, default: Any = None) -> Any:
    """Safely load a JSON file, returning default on failure."""
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any, indent: int = 2):
    """Save data as JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return s.strip("-") or "default"


def slugify_underscore(text: str) -> str:
    """Convert text to underscore-separated slug (for workspace IDs)."""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "workspace"
