"""Read-only TUI monitor used by `maestro-solo up --tui`."""

from __future__ import annotations

import json
import os
import platform
import plistlib
import re
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel

from maestro_engine.network import resolve_network_urls
from .openclaw_runtime import openclaw_config_path, openclaw_state_root, prepend_openclaw_profile_args


CYAN = "cyan"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"
GREEN = "green"
YELLOW = "yellow"
RED = "red"
ORANGE = "#ff9f1c"
LOBSTER = "#ff6b35"
DEFAULT_GATEWAY_PORT = 18789
SESSION_META_REFRESH_SEC = 2.0
ACTIVITY_WAIT_SLEEP_SEC = 0.7
ACTIVITY_IDLE_SLEEP_SEC = 0.5
MONITOR_LOOP_SLEEP_SEC = 0.5

GATEWAY_SIGNAL_KEYWORDS = (
    "gateway",
    "openclaw",
    "running",
    "stopped",
    "start",
    "restart",
    "health",
    "ready",
    "tailnet",
    "tailscale",
    "connected",
    "disconnected",
    "pair",
    "pairing",
    "onboarding",
    "onboard",
    "telegram",
    "device approval",
    "auth",
)
GATEWAY_IGNORE_KEYWORDS = (
    "debug",
    "trace",
)
TOKEN_PATTERNS = (
    re.compile(r"(?i)(token\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r'(?i)("token"\s*:\s*")([^"]+)(")'),
)

console = Console(force_terminal=True if platform.system() == "Windows" else None)


class LogBuffer:
    """Thread-safe ring buffer for server log lines."""

    def __init__(self, max_lines: int = 250):
        self._lines: Deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def add(self, line: str, *, with_timestamp: bool = True):
        text = line.rstrip("\n")
        if not text:
            return
        with self._lock:
            if with_timestamp:
                self._lines.append(f"{datetime.now().strftime('%H:%M:%S')}  {text}")
            else:
                self._lines.append(text)

    def recent(self, count: int = 24) -> list[str]:
        with self._lock:
            return list(self._lines)[-count:]


class MonitorState:
    """Live metrics rendered by the monitor TUI."""

    def __init__(
        self,
        *,
        store_path: Path,
        web_port: int,
        primary_url: str,
        local_url: str,
        tailnet_url: str | None,
        gateway_port: int,
        agent_id: str,
        workspace_path: str,
    ):
        self.start_time = time.time()
        self.store_path = store_path
        self.web_port = int(web_port)
        self.primary_url = primary_url
        self.local_url = local_url
        self.tailnet_url = tailnet_url
        self.gateway_port = int(gateway_port)
        self.agent_id = agent_id
        self.workspace_path = workspace_path

        self.system_cpu_percent: float = 0.0
        self.system_ram_mb: float = 0.0
        self.system_ram_total_mb: float = 0.0
        self.process_cpu_percent: float = 0.0
        self.process_ram_mb: float = 0.0
        self.store_disk_mb: float = 0.0

        self.gateway_running: bool = False
        self.server_running: bool = True
        self.server_exit_code: int | None = None
        self.gateway_check_interval_sec: float = 5.0
        self.last_gateway_check_at: float = 0.0

        self.total_tokens: int = 0
        self.active_sessions: int = 0

    def uptime(self) -> str:
        elapsed = int(time.time() - self.start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        return f"{minutes}m {seconds}s"


def _safe_run(args: list[str], timeout: int = 6) -> tuple[bool, str]:
    cmd = prepend_openclaw_profile_args(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _redact_sensitive(text: str) -> str:
    clean = text
    for pattern in TOKEN_PATTERNS:
        clean = pattern.sub(r"\1[redacted]\3" if pattern.groups == 3 else r"\1[redacted]", clean)
    return clean


def _extract_gateway_message(raw_line: str) -> tuple[str, str]:
    line = raw_line.strip()
    if not line:
        return "", ""
    level_hint = ""
    if line.startswith("{") and line.endswith("}"):
        try:
            payload = json.loads(line)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            raw_level = payload.get("level") or payload.get("severity")
            if raw_level is not None:
                level_hint = str(raw_level).strip().lower()
            message = payload.get("message") or payload.get("msg") or payload.get("event")
            if isinstance(message, str) and message.strip():
                return level_hint, message.strip()
            if "_meta" in payload:
                return "", ""
    return level_hint, line


def _gateway_severity(level_hint: str, message: str) -> tuple[str, str]:
    lowered = message.lower()
    level = (level_hint or "").strip().lower()
    if level in {"error", "fatal", "panic"}:
        return "ERROR", RED
    if level in {"warn", "warning"}:
        return "WARN", YELLOW
    if any(token in lowered for token in ("error", "failed", "failure", "panic", "exception", "traceback")):
        return "ERROR", RED
    if any(token in lowered for token in ("warn", "degraded", "unavailable", "not running", "retry", "timeout")):
        return "WARN", YELLOW
    return "INFO", ORANGE


def _is_relevant_gateway_event(level_hint: str, message: str) -> bool:
    lowered = message.lower()
    level = (level_hint or "").strip().lower()
    if level in {"error", "fatal", "panic", "warn", "warning"}:
        return True
    if any(token in lowered for token in ("error", "failed", "failure", "panic", "exception", "traceback", "warn", "warning")):
        return True
    if any(token in lowered for token in GATEWAY_IGNORE_KEYWORDS):
        return False
    return any(token in lowered for token in GATEWAY_SIGNAL_KEYWORDS)


def _format_gateway_event(message: str, *, level_hint: str = "") -> str:
    severity, color = _gateway_severity(level_hint, message)
    safe_message = escape(_redact_sensitive(message))
    return f"[{color}]{datetime.now().strftime('%H:%M:%S')}  {severity:<5}  {safe_message}[/]"


def _append_gateway_event(logs: LogBuffer, message: str, *, level_hint: str = ""):
    logs.add(_format_gateway_event(message, level_hint=level_hint), with_timestamp=False)


def _parse_iso_timestamp(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now().strftime("%H:%M:%S")
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%H:%M:%S")
    except Exception:
        return datetime.now().strftime("%H:%M:%S")


def _format_activity_event(
    *,
    label: str,
    message: str,
    color: str,
    timestamp: str | None = None,
) -> str:
    safe = escape(message.strip())
    ts = _parse_iso_timestamp(timestamp)
    return f"[{color}]{ts}  {label:<7}  {safe}[/]"


def _append_activity_event(
    logs: LogBuffer,
    *,
    label: str,
    message: str,
    color: str,
    timestamp: str | None = None,
):
    logs.add(
        _format_activity_event(label=label, message=message, color=color, timestamp=timestamp),
        with_timestamp=False,
    )


def _active_session_metadata(agent_id: str) -> dict[str, Any]:
    sessions_path = openclaw_state_root() / "agents" / str(agent_id).strip() / "sessions" / "sessions.json"
    if not sessions_path.exists():
        return {}
    try:
        payload = json.loads(sessions_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict) or not payload:
        return {}

    prefix = f"agent:{str(agent_id).strip()}:"
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        if str(key).startswith(prefix):
            candidates.append((str(key), value))
    if not candidates:
        for key, value in payload.items():
            if isinstance(value, dict):
                candidates.append((str(key), value))
    if not candidates:
        return {}

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[str, int]:
        _, value = item
        updated = str(value.get("updatedAt", "")).strip()
        tok = value.get("totalTokens")
        tok_int = int(tok) if isinstance(tok, (int, float)) else 0
        return updated, tok_int

    _, selected = max(candidates, key=_sort_key)
    session_file = str(selected.get("sessionFile", "")).strip()
    return {
        "session_id": str(selected.get("sessionId", "")).strip(),
        "session_file": session_file,
        "model": str(selected.get("model", "")).strip(),
        "total_tokens": int(selected.get("totalTokens", 0)) if isinstance(selected.get("totalTokens"), (int, float)) else 0,
    }


def _activity_events_from_session_line(
    line: str,
    *,
    known_tool_calls: dict[str, str],
) -> list[dict[str, str]]:
    text = line.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    if str(payload.get("type", "")) != "message":
        return []

    timestamp = str(payload.get("timestamp", "")).strip() or None
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    role = str(message.get("role", "")).strip()
    content = message.get("content")
    items = [item for item in content if isinstance(item, dict)] if isinstance(content, list) else []
    events: list[dict[str, str]] = []

    if role == "assistant":
        if any(str(item.get("type", "")) == "thinking" for item in items):
            events.append({
                "label": "THINK",
                "message": "Maestro thinking",
                "color": DIM,
                "timestamp": timestamp or "",
            })

        for item in items:
            if str(item.get("type", "")) != "toolCall":
                continue
            tool_name = str(item.get("name", "")).strip() or "tool"
            call_id = str(item.get("id", "")).strip()
            if call_id:
                known_tool_calls[call_id] = tool_name
            events.append({
                "label": "TOOL",
                "message": f"Tool call: {tool_name}",
                "color": BRIGHT_CYAN,
                "timestamp": timestamp or "",
            })

        has_text = any(
            str(item.get("type", "")) == "text" and str(item.get("text", "")).strip()
            for item in items
        )
        if has_text:
            usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
            out_tok = usage.get("output") if isinstance(usage.get("output"), (int, float)) else usage.get("outputTokens")
            if isinstance(out_tok, (int, float)):
                response_line = f"Maestro responded ({int(out_tok):,} output tokens)"
            else:
                response_line = "Maestro responded"
            events.append({
                "label": "RESP",
                "message": response_line,
                "color": GREEN,
                "timestamp": timestamp or "",
            })
        return events

    if role == "toolResult":
        tool_call_id = str(message.get("toolCallId", "")).strip()
        tool_name = str(message.get("toolName", "")).strip() or known_tool_calls.get(tool_call_id, "tool")
        is_error = bool(message.get("isError"))
        details = message.get("details") if isinstance(message.get("details"), dict) else {}
        duration_hint = ""
        for key in ("durationMs", "elapsedMs", "duration_ms", "elapsed_ms"):
            value = details.get(key)
            if isinstance(value, (int, float)):
                duration_hint = f" ({int(value)}ms)"
                break

        if is_error:
            summary = f"Tool failed: {tool_name}{duration_hint}"
            events.append({
                "label": "ERROR",
                "message": summary,
                "color": RED,
                "timestamp": timestamp or "",
            })
            return events

        events.append({
            "label": "DONE",
            "message": f"Tool done: {tool_name}{duration_hint}",
            "color": ORANGE,
            "timestamp": timestamp or "",
        })
        return events

    if role == "user":
        events.append({
            "label": "USER",
            "message": "User request received",
            "color": BRIGHT_CYAN,
            "timestamp": timestamp or "",
        })
    return events


def _load_openclaw_config() -> dict[str, Any]:
    config_path = openclaw_config_path()
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_gateway_port() -> int:
    env_value = str(os.environ.get("OPENCLAW_GATEWAY_PORT", "")).strip()
    if env_value.isdigit():
        return int(env_value)

    plist_path = Path.home() / "Library" / "LaunchAgents" / "ai.openclaw.gateway.plist"
    if plist_path.exists():
        try:
            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)
            if isinstance(payload, dict):
                program_args = payload.get("ProgramArguments")
                if isinstance(program_args, list):
                    for idx, item in enumerate(program_args):
                        if str(item) == "--port" and idx + 1 < len(program_args):
                            port_candidate = str(program_args[idx + 1]).strip()
                            if port_candidate.isdigit():
                                return int(port_candidate)
                env_block = payload.get("EnvironmentVariables")
                if isinstance(env_block, dict):
                    value = str(env_block.get("OPENCLAW_GATEWAY_PORT", "")).strip()
                    if value.isdigit():
                        return int(value)
        except Exception:
            pass

    return DEFAULT_GATEWAY_PORT


def _probe_gateway_port(port: int, timeout: float = 0.35) -> bool:
    target_port = int(port)
    for host in ("127.0.0.1", "localhost"):
        try:
            with socket.create_connection((host, target_port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _resolve_primary_agent() -> tuple[str, str]:
    config = _load_openclaw_config()
    agents_raw = config.get("agents", {}).get("list")
    agents = [item for item in agents_raw if isinstance(item, dict)] if isinstance(agents_raw, list) else []

    selected: dict[str, Any] | None = None
    for preferred_id in ("maestro-solo-personal", "maestro-personal"):
        for item in agents:
            if str(item.get("id", "")).strip() == preferred_id:
                selected = item
                break
        if selected is not None:
            break

    if selected is None:
        for item in agents:
            if bool(item.get("default")):
                selected = item
                break

    if selected is None and agents:
        selected = agents[0]

    if selected is None:
        return "maestro-solo-personal", ""

    agent_id = str(selected.get("id", "")).strip() or "maestro-solo-personal"
    workspace_path = str(selected.get("workspace", "")).strip()
    return agent_id, workspace_path


def _load_token_stats(agent_id: str) -> tuple[int, int]:
    clean_agent_id = str(agent_id or "").strip() or "maestro-solo-personal"

    sessions_path = openclaw_state_root() / "agents" / clean_agent_id / "sessions" / "sessions.json"
    if not sessions_path.exists():
        return 0, 0
    try:
        payload = json.loads(sessions_path.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0
    if not isinstance(payload, dict):
        return 0, 0

    total_tokens = 0
    active_sessions = 0
    for value in payload.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("sessionId", "")).strip():
            active_sessions += 1
        tok = value.get("totalTokens")
        if isinstance(tok, (int, float)):
            total_tokens += int(tok)
    return total_tokens, active_sessions


def _update_metrics(state: MonitorState, process: subprocess.Popen):
    try:
        import psutil  # type: ignore

        state.system_cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        state.system_ram_mb = mem.used / (1024 * 1024)
        state.system_ram_total_mb = mem.total / (1024 * 1024)

        if process.poll() is None:
            proc = psutil.Process(process.pid)
            state.process_cpu_percent = proc.cpu_percent(interval=None)
            state.process_ram_mb = proc.memory_info().rss / (1024 * 1024)
    except Exception:
        pass

    if state.store_path.exists():
        total_size = sum(path.stat().st_size for path in state.store_path.rglob("*") if path.is_file())
        state.store_disk_mb = total_size / (1024 * 1024)

    state.total_tokens, state.active_sessions = _load_token_stats(state.agent_id)

    now = time.time()
    if (now - state.last_gateway_check_at) >= state.gateway_check_interval_sec:
        state.gateway_running = _probe_gateway_port(state.gateway_port)
        state.last_gateway_check_at = now

    network = resolve_network_urls(web_port=state.web_port, route_path="/workspace")
    state.primary_url = str(network.get("recommended_url") or state.primary_url)
    state.local_url = str(network.get("localhost_url") or state.local_url)
    state.tailnet_url = str(network.get("tailnet_url")) if network.get("tailnet_url") else None


def _stream_logs(process: subprocess.Popen, logs: LogBuffer, stop_event: threading.Event):
    stream = process.stdout
    if stream is None:
        return
    try:
        for line in iter(stream.readline, ""):
            if stop_event.is_set():
                break
            logs.add(line)
            if process.poll() is not None:
                break
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _stream_gateway_logs(process: subprocess.Popen, logs: LogBuffer, stop_event: threading.Event):
    stream = process.stdout
    if stream is None:
        return
    try:
        for line in iter(stream.readline, ""):
            if stop_event.is_set():
                break
            level_hint, message = _extract_gateway_message(line)
            if not message:
                continue
            if _is_relevant_gateway_event(level_hint, message):
                _append_gateway_event(logs, message, level_hint=level_hint)
            if process.poll() is not None:
                break
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _stream_maestro_activity(agent_id: str, logs: LogBuffer, stop_event: threading.Event):
    current_session_file: Path | None = None
    current_session_id = ""
    current_model = ""
    offset = 0
    known_tool_calls: dict[str, str] = {}
    last_meta_check_at = 0.0
    missing_announced = False

    while not stop_event.is_set():
        now = time.time()
        if (now - last_meta_check_at) >= SESSION_META_REFRESH_SEC:
            meta = _active_session_metadata(agent_id)
            session_file_raw = str(meta.get("session_file", "")).strip()
            candidate = Path(session_file_raw).expanduser() if session_file_raw else None
            if candidate != current_session_file:
                current_session_file = candidate
                current_session_id = str(meta.get("session_id", "")).strip()
                current_model = str(meta.get("model", "")).strip()
                known_tool_calls.clear()
                missing_announced = False

                if current_session_file and current_session_file.exists():
                    try:
                        offset = current_session_file.stat().st_size
                    except Exception:
                        offset = 0
                    short_session = f"{current_session_id[:8]}..." if current_session_id else "unknown"
                    model_text = current_model or "unknown-model"
                    _append_activity_event(
                        logs,
                        label="SESSION",
                        message=f"Attached session {short_session} ({model_text})",
                        color=ORANGE,
                    )
                else:
                    offset = 0
            last_meta_check_at = now

        if not current_session_file or not current_session_file.exists():
            if not missing_announced:
                _append_activity_event(
                    logs,
                    label="WAIT",
                    message="Waiting for active Maestro session activity...",
                    color=DIM,
                )
                missing_announced = True
            time.sleep(ACTIVITY_WAIT_SLEEP_SEC)
            continue

        try:
            file_size = current_session_file.stat().st_size
        except Exception:
            time.sleep(ACTIVITY_WAIT_SLEEP_SEC)
            continue

        if file_size < offset:
            offset = 0

        if file_size == offset:
            time.sleep(ACTIVITY_IDLE_SLEEP_SEC)
            continue

        try:
            with current_session_file.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(offset)
                for raw_line in handle:
                    events = _activity_events_from_session_line(raw_line, known_tool_calls=known_tool_calls)
                    for event in events:
                        _append_activity_event(
                            logs,
                            label=event.get("label", "ACT"),
                            message=event.get("message", ""),
                            color=event.get("color", BRIGHT_CYAN),
                            timestamp=event.get("timestamp"),
                        )
                offset = handle.tell()
        except Exception:
            time.sleep(ACTIVITY_WAIT_SLEEP_SEC)


def _start_text_process(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _start_daemon_thread(target: Callable[..., None], *args: Any) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


def _check_server_exit(
    process: subprocess.Popen,
    state: MonitorState,
    logs: LogBuffer,
    activity_logs: LogBuffer,
) -> bool:
    exit_code = process.poll()
    if exit_code is None:
        return False
    state.server_running = False
    state.server_exit_code = exit_code
    logs.add(f"Server exited with code {exit_code}")
    _append_activity_event(
        activity_logs,
        label="ERROR",
        message=f"Maestro server exited with code {exit_code}",
        color=RED,
    )
    return True


def _apply_gateway_status_transition(gateway_logs: LogBuffer, gateway_running: bool):
    if gateway_running:
        _append_gateway_event(gateway_logs, "Gateway service is running.")
        return
    _append_gateway_event(
        gateway_logs,
        "Gateway service is not running; try `openclaw gateway restart`.",
        level_hint="warn",
    )


def _apply_tailnet_transition(gateway_logs: LogBuffer, tailnet_url: str | None):
    if tailnet_url:
        _append_gateway_event(gateway_logs, f"Tailnet workspace reachable at {tailnet_url}")
        return
    _append_gateway_event(
        gateway_logs,
        "Tailnet URL unavailable; using local workspace URL.",
        level_hint="warn",
    )


def _update_runtime_state(state: MonitorState, process: subprocess.Popen, gateway_logs: LogBuffer):
    previous_gateway_running = state.gateway_running
    previous_tailnet = state.tailnet_url
    _update_metrics(state, process)

    if previous_gateway_running != state.gateway_running:
        _apply_gateway_status_transition(gateway_logs, state.gateway_running)
    if previous_tailnet != state.tailnet_url:
        _apply_tailnet_transition(gateway_logs, state.tailnet_url)


def _start_gateway_log_stream(stop_event: threading.Event, gateway_logs: LogBuffer) -> subprocess.Popen | None:
    gateway_cmd = prepend_openclaw_profile_args(
        ["openclaw", "logs", "--follow", "--plain", "--local-time", "--limit", "40"]
    )
    try:
        gateway_process = _start_text_process(gateway_cmd)
    except Exception as exc:
        _append_gateway_event(
            gateway_logs,
            f"OpenClaw event stream unavailable ({exc}). Use `openclaw logs --follow` directly.",
            level_hint="warn",
        )
        return None

    _append_gateway_event(gateway_logs, f"Streaming from: {' '.join(gateway_cmd)}")
    _start_daemon_thread(_stream_gateway_logs, gateway_process, gateway_logs, stop_event)
    return gateway_process


def _shutdown_process(process: subprocess.Popen | None, *, timeout_sec: float):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        process.kill()


def _render_header(state: MonitorState) -> Panel:
    server_dot = f"[{GREEN}]●[/]" if state.server_running else f"[{RED}]●[/]"
    gateway_dot = f"[{GREEN}]●[/]" if state.gateway_running else f"[{YELLOW}]●[/]"
    return Panel(
        (
            f"  {server_dot} Server  "
            f"{gateway_dot} Gateway  "
            f"[{BRIGHT_CYAN}]Up {state.uptime()}[/]  "
            f"[{DIM}]({datetime.now().strftime('%H:%M:%S')})[/]"
        ),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]MAESTRO SOLO 🦞 TUI MONITOR[/]",
    )


def _render_compute(state: MonitorState) -> Panel:
    lines = [
        f"  [{BRIGHT_CYAN}]Host CPU[/]      {state.system_cpu_percent:.0f}%",
        f"  [{BRIGHT_CYAN}]Host RAM[/]      {state.system_ram_mb:.0f}MB / {state.system_ram_total_mb:.0f}MB",
        f"  [{BRIGHT_CYAN}]Server CPU[/]    {state.process_cpu_percent:.0f}%",
        f"  [{BRIGHT_CYAN}]Server RAM[/]    {state.process_ram_mb:.0f}MB",
        f"  [{BRIGHT_CYAN}]Store Disk[/]    {state.store_disk_mb:.1f}MB",
        f"  [{BRIGHT_CYAN}]Store Path[/]    {state.store_path}",
    ]
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]COMPUTE[/]")


def _render_tokens(state: MonitorState) -> Panel:
    access_url = state.tailnet_url or state.local_url
    lines = [
        f"  [{BRIGHT_CYAN}]Total Tokens[/]      {state.total_tokens:,}",
        f"  [{BRIGHT_CYAN}]Active Sessions[/]   {state.active_sessions}",
        "",
        f"  [{BRIGHT_CYAN}]Connected Workspace[/]",
        f"  [{DIM}]{state.workspace_path or 'Not found in OpenClaw config'}[/]",
        "",
        f"  [{BRIGHT_CYAN}]Access URL[/]",
        f"  [{DIM}]{access_url}[/]",
    ]
    if state.tailnet_url and state.tailnet_url != state.local_url:
        lines.extend([
            f"  [{BRIGHT_CYAN}]Local Fallback[/]",
            f"  [{DIM}]{state.local_url}[/]",
        ])
    lines.extend([
        "",
        f"  [{DIM}]Ctrl+C to stop monitor + server[/]",
    ])
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]TOKENS[/]")


def _render_logs(logs: LogBuffer) -> Panel:
    lines = logs.recent(8)
    if not lines:
        lines = [f"[{DIM}]Waiting for server logs...[/]"]
    return Panel(
        "\n".join(lines),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]MAESTRO SERVER LOGS[/]",
    )


def _render_activity(logs: LogBuffer) -> Panel:
    lines = logs.recent(14)
    if not lines:
        lines = [f"[{DIM}]Waiting for Maestro activity...[/]"]
    return Panel(
        "\n".join(lines),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]MAESTRO ACTIVITY[/]",
    )


def _render_gateway_events(logs: LogBuffer) -> Panel:
    lines = logs.recent(12)
    if not lines:
        lines = [f"[{DIM}]Waiting for OpenClaw gateway events...[/]"]
    return Panel(
        "\n".join(lines),
        border_style=ORANGE,
        title=f"[bold {LOBSTER}]OPENCLAW GATEWAY 🦞[/]",
    )


def _build_layout(
    state: MonitorState,
    logs: LogBuffer,
    gateway_logs: LogBuffer,
    activity_logs: LogBuffer,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="top", size=10),
        Layout(name="log_stack"),
    )
    layout["top"].split_row(
        Layout(name="compute"),
        Layout(name="tokens"),
    )
    layout["log_stack"].split_column(
        Layout(name="maestro_stack"),
        Layout(name="gateway_logs"),
    )
    layout["maestro_stack"].split_column(
        Layout(name="activity"),
        Layout(name="logs"),
    )
    layout["header"].update(_render_header(state))
    layout["compute"].update(_render_compute(state))
    layout["tokens"].update(_render_tokens(state))
    layout["activity"].update(_render_activity(activity_logs))
    layout["logs"].update(_render_logs(logs))
    layout["gateway_logs"].update(_render_gateway_events(gateway_logs))
    return layout


def run_up_tui(port: int, store: str, host: str):
    """Run server + read-only monitor TUI for `maestro-solo up --tui`."""
    store_path = Path(store).resolve()
    allow_core_workspace = str(os.environ.get("MAESTRO_ALLOW_CORE_WORKSPACE", "")).strip().lower() in {"1", "true", "yes", "on"}
    tier = str(os.environ.get("MAESTRO_TIER", "core")).strip().lower()
    workspace_enabled = tier == "pro" or allow_core_workspace
    network = resolve_network_urls(web_port=port, route_path="/workspace" if workspace_enabled else "/")
    agent_id, workspace_path = _resolve_primary_agent()
    gateway_port = _resolve_gateway_port()
    state = MonitorState(
        store_path=store_path,
        web_port=port,
        primary_url=str(network["recommended_url"]),
        local_url=str(network["localhost_url"]),
        tailnet_url=str(network["tailnet_url"]) if network.get("tailnet_url") else None,
        gateway_port=gateway_port,
        agent_id=agent_id,
        workspace_path=workspace_path,
    )
    logs = LogBuffer()
    gateway_logs = LogBuffer()
    activity_logs = LogBuffer()
    stop_event = threading.Event()

    cmd = [
        sys.executable,
        "-m",
        "maestro_solo.cli",
        "serve",
        "--port",
        str(port),
        "--store",
        str(store_path),
        "--host",
        host,
    ]
    process = _start_text_process(cmd)
    logs.add(f"Starting server: {' '.join(cmd)}")
    if workspace_enabled:
        logs.add(f"Workspace URL: {state.primary_url}")
    else:
        logs.add(f"Core runtime URL: {state.primary_url}")
    if workspace_enabled and state.workspace_path:
        logs.add(f"Connected workspace: {state.workspace_path}")
    _append_activity_event(
        activity_logs,
        label="START",
        message=(
            f"Maestro monitor attached. Workspace: {state.workspace_path or 'unknown'}"
            if workspace_enabled
            else "Maestro monitor attached. Core text-only mode is active."
        ),
        color=BRIGHT_CYAN,
    )
    _append_gateway_event(
        gateway_logs,
        f"Monitoring filtered OpenClaw runtime/health events (pairing included). Port probe: {state.gateway_port}.",
    )

    _start_daemon_thread(_stream_logs, process, logs, stop_event)
    _start_daemon_thread(_stream_maestro_activity, state.agent_id, activity_logs, stop_event)
    gateway_process = _start_gateway_log_stream(stop_event, gateway_logs)
    interrupted = False

    try:
        with Live(
            _build_layout(state, logs, gateway_logs, activity_logs),
            console=console,
            refresh_per_second=2,
            screen=False,
        ) as live:
            while not stop_event.is_set():
                if _check_server_exit(process, state, logs, activity_logs):
                    break

                _update_runtime_state(state, process, gateway_logs)
                live.update(_build_layout(state, logs, gateway_logs, activity_logs))
                time.sleep(MONITOR_LOOP_SLEEP_SEC)
    except KeyboardInterrupt:
        interrupted = True
        logs.add("Received interrupt, shutting down...")
        _append_activity_event(
            activity_logs,
            label="STOP",
            message="Received interrupt; shutting down monitor and server.",
            color=YELLOW,
        )
        _append_gateway_event(gateway_logs, "Received interrupt; shutting down monitor and server.", level_hint="warn")
    finally:
        stop_event.set()
        _shutdown_process(process, timeout_sec=8.0)
        if process.poll() is not None:
            state.server_running = False
            state.server_exit_code = process.returncode
        _shutdown_process(gateway_process, timeout_sec=5.0)

    if interrupted:
        return
    if state.server_exit_code not in (None, 0):
        raise SystemExit(state.server_exit_code)
