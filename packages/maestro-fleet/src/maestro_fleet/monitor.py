"""Fleet-native read-only TUI monitor used by `maestro-fleet up --tui`."""

from __future__ import annotations

import json
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Deque
from urllib.error import URLError
from urllib.request import Request, urlopen

from maestro.fleet_constants import (
    DEFAULT_COMMANDER_MODEL,
    DEFAULT_PROJECT_MODEL,
    canonicalize_model,
    default_model_from_agents,
    format_model_display,
)

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel

from .openclaw_runtime import (
    openclaw_state_root,
    prepend_openclaw_profile_args,
    sanitized_subprocess_env,
)
from .runtime import (
    is_fleet_server_process,
    listener_pids,
    read_process_command,
    resolve_network_urls,
)
from .state import load_install_state, load_openclaw_config, resolve_commander_agent


CYAN = "cyan"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"
GREEN = "green"
YELLOW = "yellow"
RED = "red"
ORANGE = "#ff9f1c"

ACTIVITY_SLEEP_SEC = 0.5
MONITOR_REFRESH_PER_SECOND = 2

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
    "telegram",
    "device approval",
    "auth",
)
GATEWAY_IGNORE_KEYWORDS = ("debug", "trace")
TOKEN_PATTERNS = (
    re.compile(r"(?i)(token\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r'(?i)("token"\s*:\s*")([^"]+)(")'),
)

console = Console(force_terminal=True if platform.system() == "Windows" else None)


class LogBuffer:
    """Thread-safe ring buffer for log lines."""

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


def _maestro_server_listener_pids(port: int) -> list[int]:
    matched: list[int] = []
    for pid in listener_pids(int(port)):
        if is_fleet_server_process(
            pid,
            port=int(port),
            read_command_fn=read_process_command,
        ):
            matched.append(int(pid))
    return matched


def _start_text_process(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "env": env if env is not None else sanitized_subprocess_env(),
    }
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        if creationflags:
            popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **popen_kwargs)


def _pid_running(pid: int) -> bool:
    try:
        target = int(pid)
    except Exception:
        return False
    if target <= 0:
        return False
    try:
        os.kill(target, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _shutdown_pid(pid: int, *, timeout_sec: float):
    try:
        target = int(pid)
    except Exception:
        return
    if target <= 0 or not _pid_running(target):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(target), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_sec)),
            check=False,
        )
        return
    try:
        os.kill(target, signal.SIGTERM)
    except (PermissionError, ProcessLookupError, OSError):
        return
    deadline = time.time() + float(timeout_sec)
    while time.time() < deadline:
        if not _pid_running(target):
            return
        time.sleep(0.1)
    try:
        os.kill(target, signal.SIGKILL)
    except (PermissionError, ProcessLookupError, OSError):
        return


def _install_shutdown_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def _raise_interrupt(_signum, _frame):
        raise KeyboardInterrupt

    for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, _raise_interrupt)
        except Exception:
            continue
    return previous


def _restore_shutdown_signal_handlers(previous: dict[int, Any]):
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except Exception:
            continue


@dataclass
class ProjectRow:
    slug: str
    owner: str
    attention: int
    blockers: int
    loop_state: str
    last_updated: str
    is_stale: bool


class MonitorState:
    """Live metrics rendered by the Fleet monitor."""

    def __init__(
        self,
        *,
        store_path: Path,
        web_port: int,
        company_name: str,
        primary_url: str,
        local_url: str,
        tailnet_url: str | None,
        commander_agent_id: str,
        commander_workspace: str,
        commander_model: str,
        project_model: str,
    ):
        self.start_time = time.time()
        self.store_path = store_path
        self.web_port = int(web_port)
        self.company_name = company_name
        self.primary_url = primary_url
        self.local_url = local_url
        self.tailnet_url = tailnet_url
        self.commander_agent_id = commander_agent_id
        self.commander_workspace = commander_workspace
        self.commander_model = commander_model
        self.project_model = project_model

        self.system_cpu_percent: float = 0.0
        self.system_ram_mb: float = 0.0
        self.system_ram_total_mb: float = 0.0
        self.process_cpu_percent: float = 0.0
        self.process_ram_mb: float = 0.0
        self.store_disk_mb: float = 0.0

        self.gateway_running: bool = False
        self.server_running: bool = True
        self.server_exit_code: int | None = None

        self.total_tokens: int = 0
        self.active_sessions: int = 0

        self.project_count: int = 0
        self.elevated_count: int = 0
        self.stale_count: int = 0
        self.directive_count: int = 0
        self.orchestrator_status: str = "Unknown"
        self.current_action: str = "Awaiting telemetry."
        self.project_rows: list[ProjectRow] = []
        self.last_state_error: str = ""
        self._last_activity_signature: tuple[int, int, int, int, str] = (0, 0, 0, 0, "")

    def uptime(self) -> str:
        elapsed = int(time.time() - self.start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        return f"{minutes}m {seconds}s"


def _truncate(text: str, width: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= width:
        return clean
    if width <= 1:
        return clean[:width]
    return clean[: width - 1] + "…"


def _attention_color(score: int) -> str:
    if score >= 70:
        return RED
    if score >= 45:
        return YELLOW
    return GREEN


def _fleet_status_color(status: str) -> str:
    clean = str(status or "").strip().lower()
    if clean in {"elevated", "degraded", "warning"}:
        return YELLOW
    if clean in {"offline", "error", "down"}:
        return RED
    return GREEN


def _safe_run(args: list[str], timeout: int = 6) -> tuple[bool, str]:
    profiled_args = prepend_openclaw_profile_args(args, default_profile="maestro-fleet")
    try:
        result = subprocess.run(
            profiled_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=sanitized_subprocess_env(),
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _load_openclaw_config() -> dict[str, Any]:
    return load_openclaw_config()


def _resolve_commander_agent() -> tuple[str, str]:
    return resolve_commander_agent()


def _resolve_fleet_models() -> tuple[str, str]:
    config = _load_openclaw_config()
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    commander_model = DEFAULT_COMMANDER_MODEL
    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("id", "")).strip() == "maestro-company":
            commander_model = canonicalize_model(agent.get("model"), fallback=DEFAULT_COMMANDER_MODEL)
            break
    project_model = default_model_from_agents(agent_list, fallback=DEFAULT_PROJECT_MODEL)
    return commander_model, project_model


def _load_token_stats(agent_id: str) -> tuple[int, int]:
    clean_agent_id = str(agent_id or "").strip() or "maestro-company"
    sessions_path = (
        openclaw_state_root(default_profile="maestro-fleet", enforce_profile=True)
        / "agents"
        / clean_agent_id
        / "sessions"
        / "sessions.json"
    )
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


def _format_short_timestamp(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "-"
    if "T" in text:
        tail = text.split("T", 1)[1]
        return tail.replace("Z", "")[:8] or text[:16]
    return text[:16]


def _fetch_json(url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - controlled localhost URL
            raw = response.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, ValueError):
        return None
    except Exception:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _extract_project_rows(projects: list[dict[str, Any]], limit: int = 8) -> list[ProjectRow]:
    rows: list[ProjectRow] = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        status_report = item.get("status_report") if isinstance(item.get("status_report"), dict) else {}
        metrics = status_report.get("metrics") if isinstance(status_report.get("metrics"), dict) else {}
        critical_path = item.get("critical_path") if isinstance(item.get("critical_path"), dict) else {}
        heartbeat = item.get("heartbeat") if isinstance(item.get("heartbeat"), dict) else {}

        slug = str(item.get("slug", "")).strip() or "-"
        owner = str(item.get("assignee", "")).strip() or str(item.get("superintendent", "")).strip() or "-"
        attention = int(item.get("attention_score", 0) or metrics.get("attention_score", 0) or 0)
        blockers = int(critical_path.get("blocker_count", 0) or metrics.get("blocker_count", 0) or 0)
        loop_state = (
            str(status_report.get("loop_state", "")).strip()
            or str(item.get("agent_status", "")).strip()
            or "idle"
        )
        last_updated = _format_short_timestamp(str(item.get("last_updated", "")).strip())
        is_stale = bool(status_report.get("stale")) or (
            bool(heartbeat.get("available")) and not bool(heartbeat.get("is_fresh"))
        )

        rows.append(
            ProjectRow(
                slug=slug,
                owner=owner,
                attention=attention,
                blockers=blockers,
                loop_state=loop_state,
                last_updated=last_updated,
                is_stale=is_stale,
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _update_command_center_state(state: MonitorState, activity_logs: LogBuffer):
    payload = _fetch_json(f"http://127.0.0.1:{state.web_port}/api/command-center/state", timeout=1.3)
    if not payload:
        state.last_state_error = "command-center state unavailable"
        return

    commander = payload.get("commander") if isinstance(payload.get("commander"), dict) else {}
    commander_model = canonicalize_model(commander.get("model"), fallback=state.commander_model or DEFAULT_COMMANDER_MODEL)
    if commander_model:
        state.commander_model = commander_model

    projects_raw = payload.get("projects")
    projects = [item for item in projects_raw if isinstance(item, dict)] if isinstance(projects_raw, list) else []
    directives = payload.get("directives")
    directives_count = len(directives) if isinstance(directives, list) else 0
    orchestrator = payload.get("orchestrator") if isinstance(payload.get("orchestrator"), dict) else {}
    current_action = str(orchestrator.get("currentAction", "")).strip() or "Awaiting telemetry."
    orchestrator_status = str(orchestrator.get("status", "")).strip() or "Unknown"

    rows = _extract_project_rows(projects, limit=8)
    elevated_count = sum(1 for row in rows if row.attention >= 60)
    stale_count = sum(1 for row in rows if row.is_stale)

    state.project_rows = rows
    state.project_count = len(projects)
    state.elevated_count = elevated_count
    state.stale_count = stale_count
    state.directive_count = directives_count
    state.current_action = current_action
    state.orchestrator_status = orchestrator_status
    state.last_state_error = ""

    signature = (
        state.project_count,
        state.elevated_count,
        state.stale_count,
        state.directive_count,
        state.current_action,
    )
    if signature != state._last_activity_signature:
        state._last_activity_signature = signature
        activity_logs.add(
            (
                f"Fleet status -> projects={state.project_count}, elevated={state.elevated_count}, "
                f"stale={state.stale_count}, directives={state.directive_count}"
            )
        )
        activity_logs.add(f"Commander action -> {state.current_action}")


def _gateway_running() -> bool:
    ok, out = _safe_run(["openclaw", "gateway", "status", "--json"], timeout=6)
    if not ok:
        return False
    raw = str(out or "")
    idx = raw.find("{")
    if idx < 0:
        return False
    try:
        payload = json.loads(raw[idx:])
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    service = payload.get("service", {}) if isinstance(payload.get("service"), dict) else {}
    runtime = service.get("runtime", {}) if isinstance(service.get("runtime"), dict) else {}
    status = str(runtime.get("status", "")).strip().lower()
    return status in {"running", "started", "active"}


def _update_metrics(state: MonitorState, process: subprocess.Popen[str] | None, activity_logs: LogBuffer):
    previous_gateway = state.gateway_running
    previous_tailnet = state.tailnet_url

    try:
        import psutil  # type: ignore

        state.system_cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        state.system_ram_mb = mem.used / (1024 * 1024)
        state.system_ram_total_mb = mem.total / (1024 * 1024)

        if process is not None and process.poll() is None:
            proc = psutil.Process(process.pid)
            state.process_cpu_percent = proc.cpu_percent(interval=None)
            state.process_ram_mb = proc.memory_info().rss / (1024 * 1024)
    except Exception:
        pass

    if state.store_path.exists():
        total_size = sum(path.stat().st_size for path in state.store_path.rglob("*") if path.is_file())
        state.store_disk_mb = total_size / (1024 * 1024)

    state.total_tokens, state.active_sessions = _load_token_stats(state.commander_agent_id)

    state.gateway_running = _gateway_running()

    network = resolve_network_urls(web_port=state.web_port, route_path="/command-center")
    state.primary_url = str(network.get("recommended_url") or state.primary_url)
    state.local_url = str(network.get("localhost_url") or state.local_url)
    state.tailnet_url = str(network.get("tailnet_url")) if network.get("tailnet_url") else None

    _update_command_center_state(state, activity_logs)

    if previous_gateway != state.gateway_running:
        if state.gateway_running:
            activity_logs.add("OpenClaw gateway is running.")
        else:
            activity_logs.add("OpenClaw gateway is not running.")
    if previous_tailnet != state.tailnet_url:
        if state.tailnet_url:
            activity_logs.add(f"Tailnet URL available: {state.tailnet_url}")
        else:
            activity_logs.add("Tailnet URL unavailable; local URL is active.")


def _stream_logs(process: subprocess.Popen[str], logs: LogBuffer, stop_event: threading.Event):
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


def _redact_sensitive(text: str) -> str:
    clean = text
    for pattern in TOKEN_PATTERNS:
        if pattern.groups == 3:
            clean = pattern.sub(r"\1[redacted]\3", clean)
        else:
            clean = pattern.sub(r"\1[redacted]", clean)
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


def _append_gateway_event(gateway_logs: LogBuffer, message: str, *, level_hint: str = ""):
    clean = _redact_sensitive(message)
    severity_label, color = _gateway_severity(level_hint, clean)
    gateway_logs.add(f"[{color}]{severity_label}[/{color}] {clean}")


def _stream_gateway_logs(
    gateway_process: subprocess.Popen[str],
    gateway_logs: LogBuffer,
    stop_event: threading.Event,
):
    stream = gateway_process.stdout
    if stream is None:
        return
    try:
        for raw_line in iter(stream.readline, ""):
            if stop_event.is_set():
                break
            level_hint, message = _extract_gateway_message(raw_line)
            if not message:
                continue
            if not _is_relevant_gateway_event(level_hint, message):
                continue
            _append_gateway_event(gateway_logs, message, level_hint=level_hint)
            if gateway_process.poll() is not None:
                break
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _start_gateway_log_stream(stop_event: threading.Event, gateway_logs: LogBuffer) -> subprocess.Popen[str] | None:
    cmd = prepend_openclaw_profile_args(
        ["openclaw", "logs", "--follow", "--plain", "--local-time", "--limit", "40"],
        default_profile="maestro-fleet",
    )
    try:
        process = _start_text_process(cmd)
    except Exception as exc:
        _append_gateway_event(
            gateway_logs,
            f"OpenClaw event stream unavailable ({exc}). Use `openclaw logs --follow` directly.",
            level_hint="warn",
        )
        return None

    _append_gateway_event(gateway_logs, f"Streaming from: {' '.join(cmd)}")
    thread = threading.Thread(
        target=_stream_gateway_logs,
        args=(process, gateway_logs, stop_event),
        daemon=True,
    )
    thread.start()
    return process


def _shutdown_process(process: subprocess.Popen[str] | None, *, timeout_sec: float):
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            process.terminate()
    try:
        process.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                process.kill()
        try:
            process.wait(timeout=1.0)
        except Exception:
            pass


def _render_header(state: MonitorState) -> Panel:
    server_dot = f"[{GREEN}]●[/]" if state.server_running else f"[{RED}]●[/]"
    gateway_dot = f"[{GREEN}]●[/]" if state.gateway_running else f"[{YELLOW}]●[/]"
    fleet_color = _fleet_status_color(state.orchestrator_status)
    company = escape(_truncate(state.company_name, 28)) or "Company"
    status = escape(state.orchestrator_status)
    return Panel(
        (
            f"  {server_dot} Server  "
            f"{gateway_dot} Gateway  "
            f"[{BRIGHT_CYAN}]Company:[/] {company}  "
            f"[{BRIGHT_CYAN}]Fleet:[/] [{fleet_color}]{status}[/]  "
            f"[{BRIGHT_CYAN}]Up {state.uptime()}[/]  "
            f"[{DIM}]({datetime.now().strftime('%H:%M:%S')})[/]"
        ),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]MAESTRO FLEET SETUP TUI[/]",
    )


def _render_compute(state: MonitorState) -> Panel:
    workspace = escape(_truncate(state.commander_workspace or "-", 52))
    lines = [
        f"  [{BRIGHT_CYAN}]Host CPU[/]         {state.system_cpu_percent:.0f}%",
        f"  [{BRIGHT_CYAN}]Host RAM[/]         {state.system_ram_mb:.0f}MB / {state.system_ram_total_mb:.0f}MB",
        f"  [{BRIGHT_CYAN}]Server CPU[/]       {state.process_cpu_percent:.0f}%",
        f"  [{BRIGHT_CYAN}]Server RAM[/]       {state.process_ram_mb:.0f}MB",
        f"  [{BRIGHT_CYAN}]Store Disk[/]       {state.store_disk_mb:.1f}MB",
        f"  [{BRIGHT_CYAN}]Store Path[/]       {escape(str(state.store_path))}",
        f"  [{BRIGHT_CYAN}]Commander Agent[/]  {escape(state.commander_agent_id)}",
        f"  [{BRIGHT_CYAN}]Commander Model[/]  {escape(_truncate(format_model_display(state.commander_model), 52))}",
        f"  [{BRIGHT_CYAN}]Project Model[/]    {escape(_truncate(format_model_display(state.project_model), 52))}",
        f"  [{BRIGHT_CYAN}]Workspace[/]        {workspace}",
    ]
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]COMPUTE[/]")


def _render_fleet_status(state: MonitorState) -> Panel:
    access_url = state.tailnet_url or state.local_url
    elevated_color = RED if state.elevated_count > 0 else GREEN
    stale_color = YELLOW if state.stale_count > 0 else GREEN
    directives_color = YELLOW if state.directive_count > 0 else GREEN
    action = escape(_truncate(state.current_action, 72))
    lines = [
        f"  [{BRIGHT_CYAN}]Company[/]          {escape(state.company_name)}",
        f"  [{BRIGHT_CYAN}]Command Center[/]   {escape(access_url)}",
        f"  [{BRIGHT_CYAN}]Local URL[/]        {escape(state.local_url)}",
        f"  [{BRIGHT_CYAN}]Projects[/]         {state.project_count}",
        f"  [{BRIGHT_CYAN}]Elevated[/]         [{elevated_color}]{state.elevated_count}[/]",
        f"  [{BRIGHT_CYAN}]Stale Heartbeats[/] [{stale_color}]{state.stale_count}[/]",
        f"  [{BRIGHT_CYAN}]Directives[/]       [{directives_color}]{state.directive_count}[/]",
        f"  [{BRIGHT_CYAN}]Commander Action[/]",
        f"  [{DIM}]{action}[/]",
    ]
    if state.tailnet_url and state.tailnet_url != state.local_url:
        lines.append(f"  [{BRIGHT_CYAN}]Tailnet URL[/]      {escape(state.tailnet_url)}")
    if state.last_state_error:
        lines.extend(
            [
                "",
                f"  [{YELLOW}]State warning:[/] {escape(state.last_state_error)}",
            ]
        )
    lines.extend(
        [
            "",
            f"  [{DIM}]Ctrl+C to stop monitor + server[/]",
        ]
    )
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]FLEET STATUS[/]")


def _render_projects(state: MonitorState) -> Panel:
    if not state.project_rows:
        lines = [f"[{DIM}]Waiting for project telemetry...[/]"]
        return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]PROJECT STATUS[/]")

    lines = [
        f"[{DIM}]slug                attn  blk  loop        owner            updated[/]",
    ]
    for row in state.project_rows:
        slug = escape(_truncate(row.slug, 18)).ljust(18)
        owner = escape(_truncate(row.owner, 15)).ljust(15)
        loop_state = escape(_truncate(row.loop_state, 10)).ljust(10)
        attn_color = _attention_color(row.attention)
        blocker_color = RED if row.blockers > 0 else GREEN
        stale_mark = f"[{YELLOW}]*[/]" if row.is_stale else " "
        lines.append(
            f"{slug}  [{attn_color}]{row.attention:>3}[/]  "
            f"[{blocker_color}]{row.blockers:>3}[/]  {loop_state}  {owner}  {escape(row.last_updated)}{stale_mark}"
        )
    lines.append(f"[{DIM}]* stale heartbeat[/]")
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]PROJECT STATUS[/]")


def _render_activity(activity_logs: LogBuffer) -> Panel:
    lines = activity_logs.recent(12)
    if not lines:
        lines = [f"[{DIM}]Waiting for Fleet activity...[/]"]
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]FLEET ACTIVITY[/]")


def _render_server_logs(logs: LogBuffer) -> Panel:
    lines = logs.recent(10)
    if not lines:
        lines = [f"[{DIM}]Waiting for server logs...[/]"]
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]SERVER LOGS[/]")


def _render_gateway_logs(gateway_logs: LogBuffer) -> Panel:
    lines = gateway_logs.recent(10)
    if not lines:
        lines = [f"[{DIM}]Waiting for OpenClaw gateway events...[/]"]
    return Panel("\n".join(lines), border_style=ORANGE, title=f"[bold {BRIGHT_CYAN}]GATEWAY EVENTS[/]")


def _build_layout(
    state: MonitorState,
    logs: LogBuffer,
    activity_logs: LogBuffer,
    gateway_logs: LogBuffer,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="top", size=12),
        Layout(name="middle", size=12),
        Layout(name="bottom"),
    )
    layout["top"].split_row(
        Layout(name="compute"),
        Layout(name="fleet"),
    )
    layout["middle"].split_row(
        Layout(name="projects"),
        Layout(name="activity"),
    )
    layout["bottom"].split_row(
        Layout(name="server_logs"),
        Layout(name="gateway_logs"),
    )

    layout["header"].update(_render_header(state))
    layout["compute"].update(_render_compute(state))
    layout["fleet"].update(_render_fleet_status(state))
    layout["projects"].update(_render_projects(state))
    layout["activity"].update(_render_activity(activity_logs))
    layout["server_logs"].update(_render_server_logs(logs))
    layout["gateway_logs"].update(_render_gateway_logs(gateway_logs))
    return layout


def run_up_tui(port: int, store: str, host: str):
    """Run server + Fleet setup monitor for `maestro-fleet up --tui`."""
    store_path = Path(store).resolve()
    network = resolve_network_urls(web_port=port, route_path="/command-center")
    commander_agent_id, commander_workspace = _resolve_commander_agent()
    commander_model, project_model = _resolve_fleet_models()
    install_state = load_install_state()
    company_name = str(install_state.get("company_name", "")).strip() or "Company"

    state = MonitorState(
        store_path=store_path,
        web_port=port,
        company_name=company_name,
        primary_url=str(network["recommended_url"]),
        local_url=str(network["localhost_url"]),
        tailnet_url=str(network["tailnet_url"]) if network.get("tailnet_url") else None,
        commander_agent_id=commander_agent_id,
        commander_workspace=commander_workspace,
        commander_model=commander_model,
        project_model=project_model,
    )

    logs = LogBuffer()
    activity_logs = LogBuffer()
    gateway_logs = LogBuffer()
    stop_event = threading.Event()

    cmd = [
        sys.executable,
        "-m",
        "maestro_fleet.server",
        "--port",
        str(port),
        "--store",
        str(store_path),
        "--host",
        host,
    ]
    attached_server_pids = _maestro_server_listener_pids(port)
    existing_state = None if attached_server_pids else _fetch_json(
        f"http://127.0.0.1:{int(port)}/api/command-center/state",
        timeout=0.8,
    )
    attach_only = bool(attached_server_pids) or existing_state is not None
    process: subprocess.Popen[str] | None = None
    previous_signal_handlers = _install_shutdown_signal_handlers()
    interrupted = False
    gateway_process: subprocess.Popen[str] | None = None

    try:
        if attach_only:
            if attached_server_pids:
                logs.add(
                    f"Detected existing Maestro server on port {port}; attaching monitor and will stop it on exit."
                )
            else:
                logs.add(f"Detected existing Fleet server on port {port}; attaching monitor.")
        else:
            process = _start_text_process(cmd)
            logs.add(f"Starting server: {' '.join(cmd)}")
        activity_logs.add(f"Fleet monitor attached for {company_name}.")
        activity_logs.add(f"Command Center URL: {state.primary_url}")

        if process is not None:
            log_thread = threading.Thread(
                target=_stream_logs,
                args=(process, logs, stop_event),
                daemon=True,
            )
            log_thread.start()
        gateway_process = _start_gateway_log_stream(stop_event, gateway_logs)

        with Live(
            _build_layout(state, logs, activity_logs, gateway_logs),
            console=console,
            refresh_per_second=MONITOR_REFRESH_PER_SECOND,
            screen=False,
        ) as live:
            while not stop_event.is_set():
                if process is not None:
                    exit_code = process.poll()
                    if exit_code is not None:
                        state.server_running = False
                        state.server_exit_code = exit_code
                        logs.add(f"Server exited with code {exit_code}")
                        break

                _update_metrics(state, process, activity_logs)
                live.update(_build_layout(state, logs, activity_logs, gateway_logs))
                time.sleep(ACTIVITY_SLEEP_SEC)
    except KeyboardInterrupt:
        interrupted = True
        logs.add("Received interrupt, shutting down...")
        activity_logs.add("Received interrupt; shutting down monitor and server.")
    finally:
        stop_event.set()
        _shutdown_process(process, timeout_sec=8.0)
        for pid in attached_server_pids:
            _shutdown_pid(pid, timeout_sec=8.0)
        if process is not None and process.poll() is not None:
            state.server_running = False
            state.server_exit_code = process.returncode
        _shutdown_process(gateway_process, timeout_sec=5.0)
        _restore_shutdown_signal_handlers(previous_signal_handlers)

    if interrupted:
        return
    if state.server_exit_code not in (None, 0):
        raise SystemExit(state.server_exit_code)
