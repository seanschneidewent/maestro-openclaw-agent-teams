"""Read-only TUI monitor used by `maestro up --tui`."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel

from .control_plane import resolve_network_urls


CYAN = "cyan"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"
GREEN = "green"
YELLOW = "yellow"
RED = "red"

console = Console(force_terminal=True if platform.system() == "Windows" else None)


class LogBuffer:
    """Thread-safe ring buffer for server log lines."""

    def __init__(self, max_lines: int = 250):
        self._lines: Deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def add(self, line: str):
        text = line.rstrip("\n")
        if not text:
            return
        with self._lock:
            self._lines.append(f"{datetime.now().strftime('%H:%M:%S')}  {text}")

    def recent(self, count: int = 24) -> list[str]:
        with self._lock:
            return list(self._lines)[-count:]


class MonitorState:
    """Live metrics rendered by the monitor TUI."""

    def __init__(self, store_path: Path, command_center_url: str):
        self.start_time = time.time()
        self.store_path = store_path
        self.command_center_url = command_center_url

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

    def uptime(self) -> str:
        elapsed = int(time.time() - self.start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        return f"{minutes}m {seconds}s"


def _safe_run(args: list[str], timeout: int = 6) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _load_token_stats() -> tuple[int, int]:
    sessions_path = Path.home() / ".openclaw" / "agents" / "maestro-company" / "sessions" / "sessions.json"
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

    state.total_tokens, state.active_sessions = _load_token_stats()

    ok, output = _safe_run(["openclaw", "status"], timeout=6)
    state.gateway_running = ok and "running" in output.lower()


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
        title=f"[bold {BRIGHT_CYAN}]MAESTRO UP — TUI MONITOR[/]",
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
    lines = [
        f"  [{BRIGHT_CYAN}]Total Tokens[/]      {state.total_tokens:,}",
        f"  [{BRIGHT_CYAN}]Active Sessions[/]   {state.active_sessions}",
        "",
        f"  [{BRIGHT_CYAN}]Command Center[/]",
        f"  [{DIM}]{state.command_center_url}[/]",
        "",
        f"  [{DIM}]Ctrl+C to stop monitor + server[/]",
    ]
    return Panel("\n".join(lines), border_style=CYAN, title=f"[bold {BRIGHT_CYAN}]TOKENS[/]")


def _render_logs(logs: LogBuffer) -> Panel:
    lines = logs.recent(24)
    if not lines:
        lines = [f"[{DIM}]Waiting for server logs...[/]"]
    return Panel(
        "\n".join(lines),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]LOGS[/]",
    )


def _build_layout(state: MonitorState, logs: LogBuffer) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="top", size=10),
        Layout(name="logs"),
    )
    layout["top"].split_row(
        Layout(name="compute"),
        Layout(name="tokens"),
    )
    layout["header"].update(_render_header(state))
    layout["compute"].update(_render_compute(state))
    layout["tokens"].update(_render_tokens(state))
    layout["logs"].update(_render_logs(logs))
    return layout


def run_up_tui(port: int, store: str, host: str):
    """Run server + read-only monitor TUI for `maestro up --tui`."""
    store_path = Path(store).resolve()
    network = resolve_network_urls(web_port=port)
    state = MonitorState(store_path=store_path, command_center_url=network["recommended_url"])
    logs = LogBuffer()
    stop_event = threading.Event()

    cmd = [
        sys.executable,
        "-m",
        "maestro.cli",
        "serve",
        "--port",
        str(port),
        "--store",
        str(store_path),
        "--host",
        host,
    ]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    logs.add(f"Starting server: {' '.join(cmd)}")
    logs.add(f"Command Center: {state.command_center_url}")

    log_thread = threading.Thread(
        target=_stream_logs,
        args=(process, logs, stop_event),
        daemon=True,
    )
    log_thread.start()
    interrupted = False

    try:
        with Live(_build_layout(state, logs), console=console, refresh_per_second=2, screen=False) as live:
            while not stop_event.is_set():
                exit_code = process.poll()
                if exit_code is not None:
                    state.server_running = False
                    state.server_exit_code = exit_code
                    logs.add(f"Server exited with code {exit_code}")
                    break

                _update_metrics(state, process)
                live.update(_build_layout(state, logs))
                time.sleep(0.5)
    except KeyboardInterrupt:
        interrupted = True
        logs.add("Received interrupt, shutting down...")
    finally:
        stop_event.set()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.poll() is not None:
            state.server_running = False
            state.server_exit_code = process.returncode

    if interrupted:
        return
    if state.server_exit_code not in (None, 0):
        raise SystemExit(state.server_exit_code)
