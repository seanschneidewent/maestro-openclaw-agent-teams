"""Commander chat helpers for command-center conversation surfaces.

Reads OpenClaw agent session artifacts and exposes normalized conversation
messages for command-center UI consumption.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import load_json


DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_MESSAGE_CHARS = 4000


@dataclass(frozen=True)
class SessionRef:
    agent_id: str
    session_key: str
    session_id: str
    sessions_dir: Path
    sessions_path: Path
    jsonl_path: Path


def _session_store_path(agent_id: str, home_dir: Path | None = None) -> tuple[Path, Path]:
    home = (home_dir or Path.home()).expanduser().resolve()
    sessions_dir = home / ".openclaw" / "agents" / agent_id / "sessions"
    sessions_path = sessions_dir / "sessions.json"
    return sessions_dir, sessions_path


def _best_session_key(payload: dict[str, Any], agent_id: str) -> str | None:
    if not isinstance(payload, dict) or not payload:
        return None

    expected_key = f"agent:{agent_id}:main"
    expected = payload.get(expected_key)
    if isinstance(expected, dict) and str(expected.get("sessionId", "")).strip():
        return expected_key

    # Fallback to most recently updated session with a sessionId.
    best_key = None
    best_updated = -1
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        session_id = str(value.get("sessionId", "")).strip()
        if not session_id:
            continue
        updated = value.get("updatedAt")
        stamp = int(updated) if isinstance(updated, (int, float)) else 0
        if stamp >= best_updated:
            best_updated = stamp
            best_key = key
    return best_key


def resolve_agent_session(agent_id: str, home_dir: Path | None = None) -> SessionRef | None:
    clean_agent = str(agent_id).strip()
    if not clean_agent:
        return None

    sessions_dir, sessions_path = _session_store_path(clean_agent, home_dir=home_dir)
    if not sessions_path.exists():
        return None

    payload = load_json(sessions_path, default={})
    if not isinstance(payload, dict):
        return None

    session_key = _best_session_key(payload, clean_agent)
    if not session_key:
        return None

    record = payload.get(session_key)
    if not isinstance(record, dict):
        return None

    session_id = str(record.get("sessionId", "")).strip()
    if not session_id:
        return None

    jsonl_path = sessions_dir / f"{session_id}.jsonl"
    return SessionRef(
        agent_id=clean_agent,
        session_key=session_key,
        session_id=session_id,
        sessions_dir=sessions_dir,
        sessions_path=sessions_path,
        jsonl_path=jsonl_path,
    )


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks).strip()


def _normalize_message(raw: dict[str, Any], *, agent_id: str, project_slug: str | None) -> dict[str, Any] | None:
    if raw.get("type") != "message":
        return None
    message = raw.get("message")
    if not isinstance(message, dict):
        return None

    role = str(message.get("role", "")).strip().lower()
    if role not in ("user", "assistant"):
        return None

    text = _extract_text(message.get("content"))
    if not text:
        return None

    out = {
        "id": str(raw.get("id", "")).strip(),
        "timestamp": str(raw.get("timestamp", "")).strip(),
        "role": role,
        "text": text,
        "agent_id": agent_id,
        "project_slug": project_slug or "",
    }
    if role == "assistant":
        model = message.get("model")
        usage = message.get("usage")
        if isinstance(model, str) and model.strip():
            out["model"] = model.strip()
        if isinstance(usage, dict):
            out["usage"] = usage
    return out


def _bounded_limit(limit: int | None) -> int:
    if not isinstance(limit, int):
        return DEFAULT_LIMIT
    if limit < 1:
        return 1
    if limit > MAX_LIMIT:
        return MAX_LIMIT
    return limit


def _load_messages(session: SessionRef, *, project_slug: str | None = None) -> list[dict[str, Any]]:
    if not session.jsonl_path.exists():
        return []
    try:
        lines = session.jsonl_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    messages: list[dict[str, Any]] = []
    for line in lines:
        try:
            raw = json.loads(line)
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_message(
            raw,
            agent_id=session.agent_id,
            project_slug=project_slug,
        )
        if normalized:
            messages.append(normalized)
    return messages


def read_agent_conversation(
    agent_id: str,
    *,
    limit: int = DEFAULT_LIMIT,
    before: str | None = None,
    project_slug: str | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    session = resolve_agent_session(agent_id, home_dir=home_dir)
    if not session:
        return {
            "ok": True,
            "agent_id": agent_id,
            "project_slug": project_slug or "",
            "session_id": "",
            "messages": [],
            "has_more": False,
            "source": "openclaw_sessions",
        }

    messages = _load_messages(session, project_slug=project_slug)
    clean_before = str(before or "").strip()
    if clean_before:
        before_idx = next((i for i, msg in enumerate(messages) if msg.get("id") == clean_before), None)
        if before_idx is not None:
            messages = messages[:before_idx]

    bounded = _bounded_limit(limit)
    has_more = len(messages) > bounded
    if len(messages) > bounded:
        messages = messages[-bounded:]

    return {
        "ok": True,
        "agent_id": session.agent_id,
        "project_slug": project_slug or "",
        "session_id": session.session_id,
        "messages": messages,
        "has_more": has_more,
        "source": "openclaw_sessions",
    }


def _snippet(text: str, max_chars: int = 180) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def build_conversation_preview(
    agent_id: str,
    *,
    project_slug: str | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    payload = read_agent_conversation(
        agent_id,
        limit=50,
        before=None,
        project_slug=project_slug,
        home_dir=home_dir,
    )
    messages = payload.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return {
            "last_message_at": "",
            "last_user_at": "",
            "last_assistant_at": "",
            "last_user_text": "",
            "last_assistant_text": "",
            "message_count": 0,
        }

    last_message = messages[-1]
    last_user = next((msg for msg in reversed(messages) if isinstance(msg, dict) and msg.get("role") == "user"), None)
    last_assistant = next((msg for msg in reversed(messages) if isinstance(msg, dict) and msg.get("role") == "assistant"), None)

    return {
        "last_message_at": str(last_message.get("timestamp", "")).strip(),
        "last_user_at": str((last_user or {}).get("timestamp", "")).strip(),
        "last_assistant_at": str((last_assistant or {}).get("timestamp", "")).strip(),
        "last_user_text": _snippet(str((last_user or {}).get("text", "")).strip()),
        "last_assistant_text": _snippet(str((last_assistant or {}).get("text", "")).strip()),
        "message_count": len(messages),
    }


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def send_agent_message(
    agent_id: str,
    message: str,
    *,
    project_slug: str | None = None,
    session_id: str | None = None,
    timeout: int = 120,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    clean_agent = str(agent_id).strip()
    text = str(message or "").strip()
    if not clean_agent:
        return {"ok": False, "error": "Missing agent_id", "status_code": 400}
    if not text:
        return {"ok": False, "error": "Message is required", "status_code": 400}
    if len(text) > MAX_MESSAGE_CHARS:
        return {
            "ok": False,
            "error": f"Message too long (max {MAX_MESSAGE_CHARS} characters)",
            "status_code": 400,
        }

    target_session = str(session_id or f"agent:{clean_agent}:main").strip()
    cmd = [
        "openclaw",
        "agent",
        "--agent",
        clean_agent,
        "--message",
        text,
        "--session-id",
        target_session,
        "--json",
        "--timeout",
        str(max(10, int(timeout))),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(15, int(timeout) + 5),
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "openclaw CLI not found on PATH",
            "status_code": 503,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "Agent send timed out",
            "status_code": 504,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Agent send failed: {exc}",
            "status_code": 500,
        }

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    response_payload = _safe_json_loads(stdout) if stdout else None
    if result.returncode != 0:
        return {
            "ok": False,
            "error": stderr or stdout or f"openclaw agent failed (exit {result.returncode})",
            "status_code": 503,
        }

    conversation = read_agent_conversation(
        clean_agent,
        limit=50,
        before=None,
        project_slug=project_slug,
        home_dir=home_dir,
    )
    return {
        "ok": True,
        "agent_id": clean_agent,
        "project_slug": project_slug or "",
        "session_id": target_session,
        "source": "openclaw_agent_invoke",
        "result": response_payload if response_payload is not None else {"stdout": stdout, "stderr": stderr},
        "conversation": conversation,
    }

