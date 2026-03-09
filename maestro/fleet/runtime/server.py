"""Compatibility wrapper for Fleet server runtime helpers.

Canonical implementation now lives in `maestro_fleet.runtime`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable


def _load_runtime_module():
    try:
        from maestro_fleet import runtime as runtime_module
        return runtime_module
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[3]
        package_src = repo_root / "packages" / "maestro-fleet" / "src"
        if package_src.exists() and str(package_src) not in sys.path:
            sys.path.insert(0, str(package_src))
        from maestro_fleet import runtime as runtime_module
        return runtime_module


_runtime = _load_runtime_module()


def read_process_command(pid: int, *, is_windows: bool) -> str:
    return _runtime.read_process_command(pid, is_windows=is_windows)


def listener_pids(port: int, *, is_windows: bool) -> list[int]:
    return _runtime.listener_pids(port, is_windows=is_windows)


def is_fleet_server_process(
    pid: int,
    *,
    port: int | None = None,
    store_root: Path | None = None,
    host: str | None = None,
    read_command: Callable[[int], str],
) -> bool:
    return _runtime.is_fleet_server_process(
        pid,
        port=port,
        store_root=store_root,
        host=host,
        read_command_fn=read_command,
    )


def managed_listener_pids(
    *,
    port: int,
    store_root: Path,
    host: str,
    listener_pids_fn: Callable[[int], list[int]],
    is_fleet_server_process_fn: Callable[[int, int | None, Path | None, str | None], bool],
) -> list[int]:
    return _runtime.managed_listener_pids(
        port=port,
        store_root=store_root,
        host=host,
        listener_pids_fn=listener_pids_fn,
        is_fleet_server_process_fn=is_fleet_server_process_fn,
    )


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
    return _runtime.save_detached_server_state(
        pid_path=pid_path,
        pid=pid,
        port=port,
        host=host,
        store_root=store_root,
        command=command,
        now_iso=now_iso,
        save_json_fn=save_json_fn,
    )


def port_listening(port: int, host: str = "127.0.0.1") -> bool:
    return _runtime.port_listening(port, host=host)


def resolve_deploy_port(
    preferred_port: int,
    *,
    port_listening_fn: Callable[[int], bool],
    managed_listener_pids_fn: Callable[[int, Path, str], list[int]],
    store_root: Path | None = None,
    host: str = "127.0.0.1",
    max_attempts: int = 20,
) -> tuple[int, bool]:
    return _runtime.resolve_deploy_port(
        preferred_port,
        port_listening_fn=port_listening_fn,
        managed_listener_pids_fn=managed_listener_pids_fn,
        store_root=store_root,
        host=host,
        max_attempts=max_attempts,
    )


def verify_command_center_http(port: int, timeout_seconds: int = 60) -> bool:
    return _runtime.verify_command_center_http(port, timeout_seconds=timeout_seconds)


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
    return _runtime.start_detached_server(
        port=port,
        store_root=store_root,
        host=host,
        state_dir=state_dir,
        now_iso=now_iso,
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
        pid_running_fn=pid_running_fn,
        terminate_process_fn=terminate_process_fn,
        managed_listener_pids_fn=managed_listener_pids_fn,
        listener_pids_fn=listener_pids_fn,
        is_fleet_server_process_fn=is_fleet_server_process_fn,
        is_windows=is_windows,
        start_windows_task_server_fn=start_windows_task_server_fn,
    )


__all__ = [
    "is_fleet_server_process",
    "listener_pids",
    "managed_listener_pids",
    "port_listening",
    "read_process_command",
    "resolve_deploy_port",
    "save_detached_server_state",
    "start_detached_server",
    "verify_command_center_http",
]
