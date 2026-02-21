#!/usr/bin/env python3
"""
Maestro Runtime TUI — mission control for the Maestro server.

Starts all services, monitors the network, and displays live system status.

Usage:
    maestro start [--port 3000] [--store knowledge_store]
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel

# ── Theme ────────────────────────────────────────────────────────

CYAN = "cyan"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"
GREEN = "green"
YELLOW = "yellow"
RED = "red"

console = Console(force_terminal=True if platform.system() == "Windows" else None)


# ── Activity Log ─────────────────────────────────────────────────

class ActivityLog:
    """Thread-safe scrolling activity log."""

    def __init__(self, max_entries: int = 100):
        self._entries: list[dict[str, str]] = []
        self._max = max_entries
        self._lock = threading.Lock()

    def add(self, source: str, message: str, style: str = "white"):
        with self._lock:
            self._entries.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "source": source,
                "message": message,
                "style": style,
            })
            if len(self._entries) > self._max:
                self._entries = self._entries[-self._max:]

    def recent(self, count: int = 15) -> list[dict[str, str]]:
        with self._lock:
            return list(self._entries[-count:])


# ── Service State ────────────────────────────────────────────────

class ServiceState:
    """Tracks the state of all monitored services."""

    def __init__(self):
        self.tailscale_ip: Optional[str] = None
        self.tailscale_connected: bool = False
        self.tailscale_network: str = ""

        self.gateway_running: bool = False
        self.gateway_version: str = ""
        self.gateway_pid: Optional[int] = None
        self.gateway_uptime_start: Optional[float] = None

        self.web_server_running: bool = False
        self.web_port: int = 3000
        self.ws_client_count: int = 0

        self.company_agent_online: bool = False
        self.telegram_connected: bool = False
        self.telegram_bot: str = ""

        self.api_key_valid: bool = False
        self.api_provider: str = ""

        self.projects: list[dict[str, Any]] = []

        self.cpu_percent: float = 0.0
        self.ram_mb: float = 0.0
        self.ram_total_mb: float = 0.0
        self.disk_store_mb: float = 0.0

        self.tokens_today: int = 0
        self.cost_today: float = 0.0
        self.cost_month: float = 0.0

        self.start_time: float = time.time()
        self.degraded_reasons: list[str] = []

    def gateway_uptime(self) -> str:
        if not self.gateway_uptime_start:
            return "—"
        elapsed = int(time.time() - self.gateway_uptime_start)
        hours, remainder = divmod(elapsed, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def server_uptime(self) -> str:
        elapsed = int(time.time() - self.start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"


# ── System Checks ────────────────────────────────────────────────

def run_cmd(cmd: str, timeout: int = 10) -> tuple[bool, str]:
    """Run a shell command, return (success, stdout)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception:
        return False, ""


def check_tailscale(state: ServiceState, log: ActivityLog) -> bool:
    ok, output = run_cmd("tailscale status")
    if not ok:
        state.tailscale_connected = False
        # Try to start it
        log.add("System", "Tailscale not connected, attempting start...", YELLOW)
        run_cmd("tailscale up")
        time.sleep(2)
        ok, output = run_cmd("tailscale status")
        if not ok:
            state.tailscale_connected = False
            return False

    state.tailscale_connected = True
    ip_ok, ip_out = run_cmd("tailscale ip -4")
    if ip_ok:
        state.tailscale_ip = ip_out.strip()
    return True


def check_gateway(state: ServiceState, log: ActivityLog) -> bool:
    ok, output = run_cmd("openclaw status")
    if ok and "running" in output.lower():
        state.gateway_running = True
        ver_ok, ver_out = run_cmd("openclaw --version")
        if ver_ok:
            state.gateway_version = ver_out.strip()
        if not state.gateway_uptime_start:
            state.gateway_uptime_start = time.time()
        return True

    # Try to start it
    log.add("System", "OpenClaw gateway not running, starting...", YELLOW)
    start_ok, _ = run_cmd("openclaw gateway start")
    time.sleep(3)

    ok, output = run_cmd("openclaw status")
    if ok and "running" in output.lower():
        state.gateway_running = True
        state.gateway_uptime_start = time.time()
        ver_ok, ver_out = run_cmd("openclaw --version")
        if ver_ok:
            state.gateway_version = ver_out.strip()
        return True

    state.gateway_running = False
    return False


def check_company_agent(state: ServiceState, log: ActivityLog) -> bool:
    """Check if Company Maestro agent is configured."""
    config_file = Path.home() / ".openclaw" / "openclaw.json"
    if not config_file.exists():
        state.company_agent_online = False
        return False

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        agents = config.get("agents", {}).get("list", [])
        for agent in agents:
            if agent.get("default", False) or agent.get("id") == "maestro":
                state.company_agent_online = True
                return True
    except Exception:
        pass

    state.company_agent_online = False
    return False


def check_telegram(state: ServiceState, log: ActivityLog) -> bool:
    """Check if Telegram bot is configured."""
    config_file = Path.home() / ".openclaw" / "openclaw.json"
    if not config_file.exists():
        return False

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        tg = config.get("channels", {}).get("telegram", {})
        if tg.get("enabled") and tg.get("botToken"):
            state.telegram_connected = True
            # Try to get bot username
            accounts = tg.get("accounts", {})
            for acc_data in accounts.values():
                if acc_data.get("botToken"):
                    state.telegram_bot = "@bot"  # We don't store username in config
                    break
            return True
    except Exception:
        pass

    state.telegram_connected = False
    return False


def check_api_key(state: ServiceState, log: ActivityLog) -> bool:
    """Check if AI provider API key is set."""
    config_file = Path.home() / ".openclaw" / "openclaw.json"
    if not config_file.exists():
        return False

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        env = config.get("env", {})
        for key_name, provider in [
            ("GEMINI_API_KEY", "Gemini"),
            ("ANTHROPIC_API_KEY", "Anthropic"),
            ("OPENAI_API_KEY", "OpenAI"),
        ]:
            if env.get(key_name):
                state.api_key_valid = True
                state.api_provider = provider
                return True
    except Exception:
        pass

    state.api_key_valid = False
    return False


def check_config(state: ServiceState, log: ActivityLog) -> tuple[bool, int, int]:
    """Check Maestro config, return (ok, total_projects, active_projects)."""
    config_file = Path.home() / ".openclaw" / "openclaw.json"
    if not config_file.exists():
        return False, 0, 0

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        agents = config.get("agents", {}).get("list", [])
        # Count project agents (non-company agents)
        project_agents = [a for a in agents if a.get("id", "").startswith("maestro-") or
                          (a.get("id") != "maestro" and a.get("id") != "maestro-company")]
        return True, len(project_agents), len(project_agents)
    except Exception:
        return False, 0, 0


def load_projects_from_store(store_path: Path) -> list[dict[str, Any]]:
    """Load project info from knowledge store."""
    projects = []
    if not store_path.exists():
        return projects

    for project_dir in sorted(store_path.iterdir()):
        if not project_dir.is_dir():
            continue
        project_json = project_dir / "project.json"
        pages_dir = project_dir / "pages"

        name = project_dir.name
        page_count = 0
        pointer_count = 0

        if project_json.exists():
            try:
                pdata = json.loads(project_json.read_text(encoding="utf-8"))
                name = pdata.get("name", name)
            except Exception:
                pass

        if pages_dir.exists():
            for pg in pages_dir.iterdir():
                if pg.is_dir():
                    page_count += 1
                    ptrs_dir = pg / "pointers"
                    if ptrs_dir.exists():
                        pointer_count += sum(1 for p in ptrs_dir.iterdir() if p.is_dir())

        projects.append({
            "name": name,
            "slug": project_dir.name,
            "pages": page_count,
            "pointers": pointer_count,
            "status": "active" if page_count > 0 else "pending",
        })

    return projects


def update_system_metrics(state: ServiceState):
    """Update CPU, RAM, disk metrics."""
    try:
        import psutil
        state.cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        state.ram_mb = mem.used / (1024 * 1024)
        state.ram_total_mb = mem.total / (1024 * 1024)
    except ImportError:
        # psutil not available — skip metrics
        pass


# ── Dashboard Panels ─────────────────────────────────────────────

def render_header(state: ServiceState) -> Panel:
    """Top status bar."""
    parts = []

    if state.tailscale_connected:
        parts.append(f"[{GREEN}]●[/] Tailscale {state.tailscale_ip}")
    else:
        parts.append(f"[{RED}]●[/] Tailscale offline")

    if state.gateway_running:
        parts.append(f"[{GREEN}]●[/] Gateway {state.gateway_uptime()}")
    else:
        parts.append(f"[{RED}]●[/] Gateway down")

    if state.tailscale_ip:
        parts.append(f"[{BRIGHT_CYAN}]:{state.web_port}[/]")

    if state.telegram_connected:
        parts.append(f"[{GREEN}]●[/] Telegram")

    status_line = "  •  ".join(parts)

    if state.degraded_reasons:
        status_icon = f"[{YELLOW}]⚠ DEGRADED[/]"
    else:
        status_icon = f"[{GREEN}]● ONLINE[/]"

    return Panel(
        f"  {status_icon}  {status_line}",
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]MAESTRO SERVER[/]",
        subtitle=f"[{DIM}]{datetime.now().strftime('%H:%M:%S')}[/]",
        subtitle_align="right",
    )


def render_agents(state: ServiceState) -> Panel:
    """Agents panel — Company Maestro + project agents."""
    lines = []

    # Company Maestro
    icon = f"[{GREEN}]●[/]" if state.company_agent_online else f"[{RED}]●[/]"
    lines.append(f"  [{BRIGHT_CYAN}]★[/] Company Maestro     {icon}")
    lines.append(f"    [{DIM}]Default agent[/]")
    lines.append("")

    # Project agents from knowledge store
    if state.projects:
        for proj in state.projects:
            if proj["status"] == "active":
                icon = f"[{GREEN}]●[/]"
                stats = f"{proj['pages']}pg • {proj['pointers']:,}ptr"
            else:
                icon = f"[{DIM}]○[/]"
                stats = "Awaiting ingest"

            # Truncate long names
            name = proj["name"]
            if len(name) > 22:
                name = name[:20] + "…"

            lines.append(f"  [{CYAN}]◆[/] {name:<22} {icon}")
            lines.append(f"    [{DIM}]{stats}[/]")
            lines.append("")
    else:
        lines.append(f"  [{DIM}]No projects yet[/]")
        lines.append(f"  [{DIM}]Chat with Company Maestro[/]")
        lines.append(f"  [{DIM}]to create your first project[/]")
        lines.append("")

    return Panel(
        "\n".join(lines),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]AGENTS[/]",
    )


def render_network(state: ServiceState) -> Panel:
    """Network panel — connected devices and services."""
    lines = []

    # Server
    lines.append(f"  [{BRIGHT_CYAN}]SERVER[/]")
    if state.tailscale_ip:
        lines.append(f"  [{DIM}]{state.tailscale_ip}:{state.web_port}[/]")
    else:
        lines.append(f"  [{DIM}]localhost:{state.web_port}[/]")
    lines.append("")

    # Web clients
    lines.append(f"  [{BRIGHT_CYAN}]BROWSER CLIENTS[/]")
    if state.ws_client_count > 0:
        lines.append(f"  {state.ws_client_count} active connection(s)")
    else:
        lines.append(f"  [{DIM}]No active connections[/]")
    lines.append("")

    # Telegram
    lines.append(f"  [{BRIGHT_CYAN}]TELEGRAM[/]")
    if state.telegram_connected:
        lines.append(f"  [{GREEN}]●[/] Bot connected")
    else:
        lines.append(f"  [{DIM}]Not configured[/]")
    lines.append("")

    # Routes
    lines.append(f"  [{BRIGHT_CYAN}]ROUTES[/]")
    lines.append(f"  [{DIM}]/command-center[/]")
    for proj in state.projects:
        lines.append(f"  [{DIM}]/project/{proj['slug']}[/]")

    return Panel(
        "\n".join(lines),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]NETWORK[/]",
    )


def render_activity(log: ActivityLog) -> Panel:
    """Activity feed panel."""
    entries = log.recent(12)
    lines = []

    if not entries:
        lines.append(f"  [{DIM}]Waiting for activity...[/]")
    else:
        for entry in reversed(entries):
            time_str = f"[{DIM}]{entry['time']}[/]"
            source = f"[{CYAN}]{entry['source']:<18}[/]"
            msg = entry["message"]
            lines.append(f"  {time_str}  {source} {msg}")

    return Panel(
        "\n".join(lines),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]ACTIVITY[/]",
    )


def render_footer(state: ServiceState) -> Panel:
    """Bottom bar — system metrics + keyboard shortcuts."""
    parts = []

    # CPU bar
    cpu_filled = int(state.cpu_percent / 10)
    cpu_bar = "█" * cpu_filled + "░" * (10 - cpu_filled)
    parts.append(f"CPU [{CYAN}]{cpu_bar}[/] {state.cpu_percent:.0f}%")

    # RAM bar
    if state.ram_total_mb > 0:
        ram_pct = state.ram_mb / state.ram_total_mb * 100
        ram_filled = int(ram_pct / 10)
        ram_bar = "█" * ram_filled + "░" * (10 - ram_filled)
        parts.append(f"RAM [{CYAN}]{ram_bar}[/] {state.ram_mb:.0f}MB")

    # Store disk
    if state.disk_store_mb > 0:
        parts.append(f"Store {state.disk_store_mb:.1f}MB")

    # Uptime
    parts.append(f"Up {state.server_uptime()}")

    metrics = "  │  ".join(parts)

    shortcuts = f"[{DIM}]Q Quit  R Restart Gateway  C Open Command Center  ? Help[/]"

    return Panel(
        f"  {metrics}\n  {shortcuts}",
        border_style=CYAN,
    )


def build_dashboard(state: ServiceState, log: ActivityLog) -> Layout:
    """Build the full dashboard layout."""
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="activity", size=16),
        Layout(name="footer", size=4),
    )

    layout["body"].split_row(
        Layout(name="agents"),
        Layout(name="network"),
    )

    layout["header"].update(render_header(state))
    layout["agents"].update(render_agents(state))
    layout["network"].update(render_network(state))
    layout["activity"].update(render_activity(log))
    layout["footer"].update(render_footer(state))

    return layout


# ── Keyboard Input ───────────────────────────────────────────────

def keyboard_listener(state: ServiceState, log: ActivityLog, stop_event: threading.Event):
    """Listen for keyboard input in a background thread."""
    import msvcrt  # Windows
    if platform.system() != "Windows":
        # Unix key reading would go here
        return

    while not stop_event.is_set():
        try:
            if msvcrt.kbhit():
                key = msvcrt.getch().decode("utf-8", errors="ignore").lower()
                if key == "q":
                    log.add("System", "Shutting down...", YELLOW)
                    stop_event.set()
                elif key == "r":
                    log.add("System", "Restarting gateway...", YELLOW)
                    run_cmd("openclaw gateway restart")
                    state.gateway_uptime_start = time.time()
                    log.add("System", "Gateway restarted", GREEN)
                elif key == "c":
                    url = f"http://{state.tailscale_ip or 'localhost'}:{state.web_port}/command-center"
                    log.add("System", f"Opening {url}", CYAN)
                    if platform.system() == "Windows":
                        os.startfile(url)
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", url])
                    else:
                        subprocess.Popen(["xdg-open", url])
            time.sleep(0.1)
        except Exception:
            time.sleep(0.1)


def keyboard_listener_unix(state: ServiceState, log: ActivityLog, stop_event: threading.Event):
    """Unix keyboard listener using select."""
    import select
    import tty
    import termios

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        while not stop_event.is_set():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                key = sys.stdin.read(1).lower()
                if key == "q":
                    log.add("System", "Shutting down...", YELLOW)
                    stop_event.set()
                elif key == "r":
                    log.add("System", "Restarting gateway...", YELLOW)
                    run_cmd("openclaw gateway restart")
                    state.gateway_uptime_start = time.time()
                    log.add("System", "Gateway restarted", GREEN)
                elif key == "c":
                    url = f"http://{state.tailscale_ip or 'localhost'}:{state.web_port}/command-center"
                    log.add("System", f"Opening {url}", CYAN)
                    subprocess.Popen(["xdg-open" if platform.system() == "Linux" else "open", url])
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


# ── Metrics Updater ──────────────────────────────────────────────

def metrics_loop(state: ServiceState, store_path: Path, stop_event: threading.Event):
    """Background thread to update system metrics periodically."""
    while not stop_event.is_set():
        update_system_metrics(state)

        # Update store disk usage
        if store_path.exists():
            total_size = sum(
                f.stat().st_size for f in store_path.rglob("*") if f.is_file()
            )
            state.disk_store_mb = total_size / (1024 * 1024)

        # Refresh project list
        state.projects = load_projects_from_store(store_path)

        # Check gateway health
        ok, output = run_cmd("openclaw status", timeout=5)
        state.gateway_running = ok and "running" in output.lower()

        stop_event.wait(10)  # Update every 10 seconds


# ── Web Server (subprocess) ──────────────────────────────────────

def start_web_server(port: int, store: str, log: ActivityLog) -> Optional[subprocess.Popen]:
    """Start the Maestro web server as a subprocess."""
    try:
        cmd = [sys.executable, "-m", "maestro.cli", "serve", "--port", str(port), "--store", store]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.add("System", f"Web server starting on :{port}", GREEN)
        return proc
    except Exception as e:
        log.add("System", f"Failed to start web server: {e}", RED)
        return None


# ── Main Entry Point ─────────────────────────────────────────────

def _set_degraded_reasons(state: ServiceState, results: list[tuple[str, bool, str]]):
    """Map startup check failures into consistent degraded-mode reasons."""
    reason_map = {
        "Tailscale": "Tailscale offline",
        "OpenClaw gateway": "Gateway not running",
        "Company Maestro agent": "Agent not configured",
        "Telegram bot": "Telegram not configured",
        "API key": "No API key",
        "Config": "Config invalid",
    }
    reasons = []
    for label, ok, _ in results:
        if ok:
            continue
        key = label
        if label.endswith(" API key"):
            key = "API key"
        reasons.append(reason_map.get(key, f"{label} check failed"))
    state.degraded_reasons = reasons


def main(port: int = 3000, store: str = "knowledge_store"):
    """Run the Maestro runtime TUI."""
    store_path = Path(store).resolve()
    state = ServiceState()
    state.web_port = port
    log = ActivityLog()
    stop_event = threading.Event()

    # ── Phase 1: Startup checks ──────────────────────────────────
    console.print()
    log.add("System", "Maestro starting up", CYAN)

    # Run checks with live display
    results: list[tuple[str, bool, str]] = []

    checks = [
        ("Tailscale", lambda: check_tailscale(state, log)),
        ("OpenClaw gateway", lambda: check_gateway(state, log)),
        ("Company Maestro agent", lambda: check_company_agent(state, log)),
        ("Telegram bot", lambda: check_telegram(state, log)),
        ("API key", lambda: check_api_key(state, log)),
    ]

    # Show startup panel with cascading checks
    with Live(render_startup([], state), console=console, refresh_per_second=4, transient=True) as live:
        for label, check_fn in checks:
            time.sleep(0.4)
            ok = check_fn()
            if label == "API key" and ok:
                label = f"{state.api_provider} API key"
            if label == "Tailscale" and ok:
                detail = f"connected ({state.tailscale_ip})"
            elif label == "OpenClaw gateway" and ok:
                ver = f" ({state.gateway_version})" if state.gateway_version else ""
                detail = f"running{ver}"
            elif ok:
                detail = "online" if "agent" in label.lower() else "connected" if "telegram" in label.lower() else "valid"
            else:
                detail = "not found" if "key" in label.lower() else "not configured" if "telegram" in label.lower() else "failed"
            results.append((label, ok, detail))
            live.update(render_startup(results, state))

        # Config check
        time.sleep(0.4)
        config_ok, total, active = check_config(state, log)
        results.append(("Config", config_ok, f"verified ({total} projects)" if config_ok else "invalid"))
        state.projects = load_projects_from_store(store_path)
        _set_degraded_reasons(state, results)
        live.update(render_startup(results, state))

        # Hold for a moment
        time.sleep(1.5)

    # Show startup result briefly
    console.print(render_startup(results, state))

    # ── Phase 2: Start web server ────────────────────────────────
    web_proc = start_web_server(port, store, log)
    if web_proc:
        state.web_server_running = True
        time.sleep(1)

    # ── Phase 3: Live dashboard ──────────────────────────────────
    log.add("System", "Dashboard live — press Q to quit, ? for help", CYAN)

    # Start background threads
    metrics_thread = threading.Thread(
        target=metrics_loop, args=(state, store_path, stop_event), daemon=True
    )
    metrics_thread.start()

    # Start keyboard listener
    if platform.system() == "Windows":
        kb_thread = threading.Thread(
            target=keyboard_listener, args=(state, log, stop_event), daemon=True
        )
    else:
        kb_thread = threading.Thread(
            target=keyboard_listener_unix, args=(state, log, stop_event), daemon=True
        )
    kb_thread.start()

    # Live dashboard loop
    try:
        # Avoid alternate-screen rendering glitches across terminal emulators.
        with Live(build_dashboard(state, log), console=console, refresh_per_second=2, screen=False) as live:
            while not stop_event.is_set():
                live.update(build_dashboard(state, log))
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # Cleanup
        stop_event.set()
        if web_proc:
            log.add("System", "Stopping web server...", YELLOW)
            web_proc.terminate()
            try:
                web_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                web_proc.kill()
        console.print(f"\n  [{CYAN}]Maestro stopped.[/]\n")


def render_startup(results: list[tuple[str, bool, str]], state: ServiceState) -> Panel:
    """Render the startup check panel with current results."""
    lines = [f"  [{DIM}]Starting up...[/]", ""]

    total_expected = 6  # total checks
    for label, ok, detail in results:
        icon = f"[{GREEN}]✓[/]" if ok else f"[{RED}]✗[/]"
        lines.append(f"  {icon} {label} — {detail}")

    # Show in-progress dots for remaining checks
    remaining = total_expected - len(results)
    if remaining > 0:
        lines.append(f"  [{DIM}]...[/]")

    # Progress bar
    passed = sum(1 for _, ok, _ in results if ok)
    progress_total = len(results)
    if progress_total > 0:
        filled = int((progress_total / total_expected) * 30)
        bar = "━" * filled + "─" * (30 - filled)
        pct = int((progress_total / total_expected) * 100)
        lines.append("")
        lines.append(f"  [{CYAN}]{bar}[/] [{DIM}]{pct}%[/]")

    # Status after all checks complete
    if len(results) == total_expected:
        if state.degraded_reasons:
            lines.append("")
            lines.append(f"  [{YELLOW}]⚠ {len(state.degraded_reasons)} issue(s) — running in degraded mode[/]")
            for reason in state.degraded_reasons:
                lines.append(f"    [{DIM}]→ {reason}[/]")
        else:
            lines.append("")
            if state.tailscale_ip:
                lines.append(f"  Command Center: [{BRIGHT_CYAN}]http://{state.tailscale_ip}:{state.web_port}[/]")
            else:
                lines.append(f"  Command Center: [{BRIGHT_CYAN}]http://localhost:{state.web_port}[/]")
            lines.append(f"  [{GREEN}]Ready.[/]")

    return Panel(
        "\n".join(lines),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]MAESTRO[/]",
        width=60,
    )


if __name__ == "__main__":
    main()
