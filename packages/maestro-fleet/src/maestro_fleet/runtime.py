"""Fleet-native runtime and process helpers."""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx


CommandRunner = Callable[[list[str], int], tuple[bool, str]]


def _default_runner(args: list[str], timeout: int = 6) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


def _invoke_runner(runner: CommandRunner, args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        return runner(args, timeout)
    except TypeError:
        return runner(args)  # type: ignore[misc]


def _parse_tailscale_ipv4(output: str) -> str | None:
    for line in output.splitlines():
        ip = line.strip()
        if ip and "." in ip:
            return ip
    return None


def resolve_network_urls(
    web_port: int,
    route_path: str = "/workspace",
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    runner = command_runner or _default_runner

    path = str(route_path or "/").strip()
    if not path.startswith("/"):
        path = f"/{path}"

    localhost = f"http://localhost:{int(web_port)}{path}"

    tailnet_ip: str | None = None
    if shutil.which("tailscale"):
        ok, out = _invoke_runner(runner, ["tailscale", "ip", "-4"], 5)
        if ok:
            tailnet_ip = _parse_tailscale_ipv4(out)

    tailnet = f"http://{tailnet_ip}:{int(web_port)}{path}" if tailnet_ip else None
    return {
        "localhost_url": localhost,
        "tailnet_url": tailnet,
        "recommended_url": tailnet or localhost,
        "tailscale_ip": tailnet_ip,
    }


def read_process_command(pid: int, *, is_windows: bool | None = None) -> str:
    if pid <= 0:
        return ""
    target_is_windows = (os.name == "nt") if is_windows is None else bool(is_windows)
    if target_is_windows:
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        f'$p = Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}"; '
                        'if ($p) { [Console]::Out.Write($p.CommandLine) }'
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except Exception:
            return ""
        return str(result.stdout or "").strip()
    if shutil.which("ps"):
        try:
            result = subprocess.run(
                ["ps", "-p", str(int(pid)), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            return str(result.stdout or "").strip()
        except Exception:
            return ""
    return ""


def listener_pids(port: int, *, is_windows: bool | None = None) -> list[int]:
    if int(port) <= 0:
        return []
    target_is_windows = (os.name == "nt") if is_windows is None else bool(is_windows)
    if target_is_windows:
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        f"Get-NetTCPConnection -State Listen -LocalPort {int(port)} "
                        "| Select-Object -ExpandProperty OwningProcess"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except Exception:
            result = None
        out: list[int] = []
        text_output = str(result.stdout or "").splitlines() if result is not None else []
        for raw in text_output:
            text = raw.strip()
            if not text:
                continue
            try:
                out.append(int(text))
            except ValueError:
                continue
        if out:
            return sorted(set(out))
        try:
            fallback = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except Exception:
            return []
        for raw in str(fallback.stdout or "").splitlines():
            text = raw.strip()
            if not text or "LISTENING" not in text.upper():
                continue
            parts = text.split()
            if len(parts) < 5:
                continue
            local_addr = parts[1].rsplit(":", 1)
            if len(local_addr) != 2 or local_addr[1] != str(int(port)):
                continue
            try:
                out.append(int(parts[-1]))
            except ValueError:
                continue
        return sorted(set(out))
    if shutil.which("lsof"):
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except Exception:
            result = None
        out: list[int] = []
        for raw in str(result.stdout or "").splitlines() if result is not None else []:
            text = raw.strip()
            if not text:
                continue
            try:
                out.append(int(text))
            except ValueError:
                continue
        return sorted(set(out))

    return []


def is_fleet_server_process(
    pid: int,
    *,
    port: int | None = None,
    store_root: Path | None = None,
    host: str | None = None,
    read_command_fn: Callable[[int], str] | None = None,
) -> bool:
    command = (read_command_fn or read_process_command)(pid)
    if not command:
        return False
    lowered = command.lower()

    launched_via_cli = "maestro.cli" in command and " serve " in f" {lowered} "
    launched_via_fleet_server = "maestro_fleet.server" in command
    if not launched_via_cli and not launched_via_fleet_server:
        return False

    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    def _arg_value(flag: str) -> str:
        if flag in parts:
            idx = parts.index(flag)
            if idx + 1 < len(parts):
                return str(parts[idx + 1]).strip()
        prefix = f"{flag}="
        for item in parts:
            if item.startswith(prefix):
                return str(item[len(prefix):]).strip()
        return ""

    if port is not None and _arg_value("--port") != str(int(port)):
        return False
    if host and _arg_value("--host") != str(host):
        return False
    if store_root is not None:
        resolved_store = Path(store_root).resolve()
        store_arg = _arg_value("--store")
        if not store_arg:
            return False
        try:
            command_store = Path(store_arg).resolve()
        except Exception:
            return False
        if command_store != resolved_store:
            return False
    return True


def managed_listener_pids(
    *,
    port: int,
    store_root: Path,
    host: str,
    listener_pids_fn: Callable[[int], list[int]],
    is_fleet_server_process_fn: Callable[[int, int | None, Path | None, str | None], bool],
) -> list[int]:
    matched: list[int] = []
    for pid in listener_pids_fn(port):
        if is_fleet_server_process_fn(pid, port, store_root, host):
            matched.append(int(pid))
    return matched


def save_detached_server_state(
    *,
    pid_path: Path,
    pid: int,
    port: int,
    host: str,
    store_root: Path,
    command: list[str] | None,
    now_iso: Callable[[], str],
    save_json_fn: Callable[[Path, dict[str, Any]], None],
) -> None:
    save_json_fn(
        pid_path,
        {
            "pid": int(pid),
            "started_at": now_iso(),
            "port": int(port),
            "host": str(host),
            "store_root": str(store_root),
            "command": command or [],
        },
    )


def resolve_deploy_port(
    preferred_port: int,
    *,
    port_listening_fn: Callable[[int], bool],
    managed_listener_pids_fn: Callable[[int, Path, str], list[int]],
    store_root: Path | None = None,
    host: str = "127.0.0.1",
    max_attempts: int = 20,
) -> tuple[int, bool]:
    requested = int(preferred_port)
    if requested <= 0:
        requested = 3000
    if not port_listening_fn(requested):
        return requested, False
    if store_root is not None and managed_listener_pids_fn(requested, store_root, host):
        return requested, False
    for offset in range(1, int(max_attempts) + 1):
        candidate = requested + offset
        if not port_listening_fn(candidate):
            return candidate, True
    return 0, True


def verify_command_center_http(port: int, timeout_seconds: int = 60) -> bool:
    end = time.time() + float(timeout_seconds)
    while time.time() < end:
        try:
            response = httpx.get(f"http://127.0.0.1:{int(port)}/api/command-center/state", timeout=2.5)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def start_detached_server(
    *,
    port: int,
    store_root: Path,
    host: str,
    state_dir: Path,
    now_iso: Callable[[], str],
    load_json_fn: Callable[[Path, dict[str, Any]], dict[str, Any]],
    save_json_fn: Callable[[Path, dict[str, Any]], None],
    pid_running_fn: Callable[[int], bool],
    terminate_process_fn: Callable[[int], bool],
    managed_listener_pids_fn: Callable[[int, Path, str], list[int]],
    listener_pids_fn: Callable[[int], list[int]],
    is_fleet_server_process_fn: Callable[[int, int | None, Path | None, str | None], bool],
    is_windows: bool,
    start_windows_task_server_fn: Callable[[int, Path, str, Path, Path, list[str] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pid_path = state_dir / "serve.pid.json"
    log_path = state_dir / "serve.log"
    requested_port = int(port)
    resolved_store = Path(store_root).resolve()

    listeners = managed_listener_pids_fn(requested_port, resolved_store, host)
    if listeners:
        primary_pid = int(listeners[0])
        for extra_pid in listeners[1:]:
            terminate_process_fn(int(extra_pid))
        save_detached_server_state(
            pid_path=pid_path,
            pid=primary_pid,
            port=requested_port,
            host=host,
            store_root=resolved_store,
            command=None,
            now_iso=now_iso,
            save_json_fn=save_json_fn,
        )
        return {
            "ok": True,
            "already_running": True,
            "pid": primary_pid,
            "port": requested_port,
            "port_mismatch": False,
            "pid_path": str(pid_path),
            "log_path": str(log_path),
            "reconciled_existing_listener": True,
        }

    if pid_path.exists():
        payload = load_json_fn(pid_path, {"pid": 0})
        running_pid = int(payload.get("pid", 0)) if isinstance(payload, dict) else 0
        if pid_running_fn(running_pid):
            running_port = int(payload.get("port", 0)) if isinstance(payload, dict) else 0
            if is_fleet_server_process_fn(
                running_pid,
                running_port or requested_port,
                resolved_store,
                str(payload.get("host", "")).strip() or host,
            ):
                if running_port and running_port != requested_port:
                    current_port = int(running_port)
                    if managed_listener_pids_fn(current_port, resolved_store, host):
                        save_detached_server_state(
                            pid_path=pid_path,
                            pid=running_pid,
                            port=current_port,
                            host=host,
                            store_root=resolved_store,
                            command=None,
                            now_iso=now_iso,
                            save_json_fn=save_json_fn,
                        )
                        return {
                            "ok": True,
                            "already_running": True,
                            "pid": running_pid,
                            "port": current_port,
                            "port_mismatch": True,
                            "pid_path": str(pid_path),
                            "log_path": str(log_path),
                        }
                elif managed_listener_pids_fn(requested_port, resolved_store, host):
                    save_detached_server_state(
                        pid_path=pid_path,
                        pid=running_pid,
                        port=requested_port,
                        host=host,
                        store_root=resolved_store,
                        command=None,
                        now_iso=now_iso,
                        save_json_fn=save_json_fn,
                    )
                    return {
                        "ok": True,
                        "already_running": True,
                        "pid": running_pid,
                        "port": requested_port,
                        "port_mismatch": False,
                        "pid_path": str(pid_path),
                        "log_path": str(log_path),
                    }
            terminate_process_fn(running_pid)
        pid_path.unlink(missing_ok=True)

    foreign_listener_pids = listener_pids_fn(requested_port)
    if foreign_listener_pids:
        return {
            "ok": False,
            "detail": (
                f"Port {requested_port} is already in use by non-Fleet listener(s): "
                + ", ".join(str(pid) for pid in foreign_listener_pids)
            ),
            "log_path": str(log_path),
            "pid_path": str(pid_path),
        }

    cmd = [
        sys.executable,
        "-m",
        "maestro_fleet.server",
        "--port",
        str(int(port)),
        "--store",
        str(store_root),
        "--host",
        str(host),
    ]
    if is_windows:
        if start_windows_task_server_fn is None:
            return {"ok": False, "detail": "Windows task server helper missing", "log_path": str(log_path), "pid_path": str(pid_path)}
        return start_windows_task_server_fn(requested_port, resolved_store, str(host), pid_path, log_path, cmd)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{now_iso()}] starting detached Fleet server: {' '.join(cmd)}\n")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    deadline = time.time() + 8.0
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        if managed_listener_pids_fn(requested_port, resolved_store, host):
            break
        time.sleep(0.25)
    if proc.poll() is not None or not managed_listener_pids_fn(requested_port, resolved_store, host):
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            tail = "\n".join(lines[-12:]).strip()
        except Exception:
            tail = ""
        detail = f"maestro_fleet.server did not become healthy (code={proc.returncode})"
        if tail:
            detail = f"{detail}\n{tail}"
        return {"ok": False, "detail": detail, "log_path": str(log_path)}

    save_detached_server_state(
        pid_path=pid_path,
        pid=int(proc.pid),
        port=int(port),
        host=str(host),
        store_root=resolved_store,
        command=cmd,
        now_iso=now_iso,
        save_json_fn=save_json_fn,
    )
    return {
        "ok": True,
        "already_running": False,
        "pid": int(proc.pid),
        "port": int(port),
        "port_mismatch": False,
        "pid_path": str(pid_path),
        "log_path": str(log_path),
    }


def port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, int(port))) == 0


__all__ = [
    "is_fleet_server_process",
    "listener_pids",
    "managed_listener_pids",
    "port_listening",
    "read_process_command",
    "resolve_network_urls",
    "resolve_deploy_port",
    "save_detached_server_state",
    "start_detached_server",
    "verify_command_center_http",
]
