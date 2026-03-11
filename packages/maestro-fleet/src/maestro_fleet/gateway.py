"""Fleet gateway lifecycle helpers."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any, Callable

from .constants import FLEET_GATEWAY_PORT, FLEET_PROFILE
from .openclaw_runtime import prepend_openclaw_profile_args
from .subprocesses import parse_json_from_output


def fleet_gateway_port() -> int:
    return FLEET_GATEWAY_PORT


def run_profiled_gateway_cmd(args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            prepend_openclaw_profile_args(args, default_profile=FLEET_PROFILE),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "openclaw CLI not found on PATH"
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output


def gateway_service_running(gateway_status: dict[str, Any]) -> bool:
    service = gateway_status.get("service", {}) if isinstance(gateway_status.get("service"), dict) else {}
    runtime = service.get("runtime", {}) if isinstance(service.get("runtime"), dict) else {}
    status_text = str(runtime.get("status", "")).strip().lower()
    if status_text in {"running", "started", "active"}:
        return True
    rpc = gateway_status.get("rpc", {}) if isinstance(gateway_status.get("rpc"), dict) else {}
    if bool(rpc.get("ok")):
        return True
    port = gateway_status.get("port", {}) if isinstance(gateway_status.get("port"), dict) else {}
    port_status = str(port.get("status", "")).strip().lower()
    listeners = port.get("listeners")
    return port_status in {"busy", "listening", "occupied"} and isinstance(listeners, list) and bool(listeners)


def gateway_cli_ready(
    gateway_status: dict[str, Any],
    *,
    service_running: Callable[[dict[str, Any]], bool] = gateway_service_running,
) -> bool:
    rpc = gateway_status.get("rpc", {}) if isinstance(gateway_status.get("rpc"), dict) else {}
    if bool(rpc.get("ok")):
        return True
    lowered = str(rpc.get("error", "")).strip().lower()
    if "token mismatch" in lowered or "unauthorized" in lowered or "pairing required" in lowered:
        return False
    return service_running(gateway_status)


def gateway_listener_pids(gateway_status: dict[str, Any]) -> list[int]:
    port = gateway_status.get("port", {}) if isinstance(gateway_status.get("port"), dict) else {}
    listeners = port.get("listeners")
    if not isinstance(listeners, list):
        return []
    pids: list[int] = []
    for item in listeners:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("pid"))
        except Exception:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def evict_gateway_listener_pids(
    gateway_status: dict[str, Any],
    *,
    terminate_pid: Callable[[int], bool],
    only_pids: set[int] | None = None,
    listener_pids: Callable[[dict[str, Any]], list[int]] = gateway_listener_pids,
) -> list[int]:
    removed: list[int] = []
    for pid in listener_pids(gateway_status):
        if only_pids is not None and pid not in only_pids:
            continue
        if terminate_pid(pid):
            removed.append(pid)
    return removed


def gateway_status_snapshot(
    *,
    run_cmd: Callable[[list[str], int], tuple[bool, str]] = run_profiled_gateway_cmd,
    parse_json: Callable[[str], dict[str, Any]] = parse_json_from_output,
    timeout: int = 12,
) -> tuple[bool, dict[str, Any], str]:
    ok, out = run_cmd(["openclaw", "gateway", "status", "--json"], timeout)
    payload = parse_json(out)
    return ok, payload, out


def restart_openclaw_gateway() -> tuple[bool, str]:
    actions: list[str] = []

    gw_ok, gw_status, gw_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(gw_status):
        return True, gw_out or "Gateway already running"

    restart_ok, restart_output = run_profiled_gateway_cmd(["openclaw", "gateway", "restart"], timeout=45)
    if restart_output:
        actions.append(restart_output)

    recheck_ok, recheck_status, recheck_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(recheck_status):
        return True, "\n".join(actions) or recheck_out or "Gateway restarted"

    start_ok, start_output = run_profiled_gateway_cmd(["openclaw", "gateway", "start"], timeout=45)
    if start_output:
        actions.append(start_output)

    recheck_ok, recheck_status, recheck_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(recheck_status):
        return True, "\n".join(actions) or recheck_out or "Gateway started"

    install_ok, install_output = run_profiled_gateway_cmd(
        ["openclaw", "gateway", "install", "--force", "--port", str(fleet_gateway_port())],
        timeout=75,
    )
    if install_output:
        actions.append(install_output)
    if not install_ok:
        return False, "\n".join(item for item in actions if item).strip() or "Failed to restart gateway"

    start2_ok, start2_output = run_profiled_gateway_cmd(["openclaw", "gateway", "start"], timeout=45)
    if start2_output:
        actions.append(start2_output)

    recheck2_ok, recheck2_status, recheck2_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(recheck2_status):
        return True, "\n".join(item for item in actions if item).strip() or recheck2_out or "Gateway reinstalled and started"
    return False, "\n".join(item for item in actions if item).strip() or recheck2_out or "Failed to restart gateway"


def restart_openclaw_gateway_report(*, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True, "detail": "Skipped gateway restart in dry-run mode"}

    actions: list[str] = []

    gw_ok, gw_status, gw_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(gw_status):
        return {"ok": True, "detail": gw_out or "Gateway already running", "gateway_status_ok": gw_ok}

    restart_ok, restart_out = run_profiled_gateway_cmd(["openclaw", "gateway", "restart"], 35)
    actions.append(f"gateway restart: {'ok' if restart_ok else 'failed'}")
    if restart_out:
        actions.append(restart_out)

    recheck_ok, recheck_status, recheck_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(recheck_status):
        return {
            "ok": True,
            "detail": "\n".join(item for item in actions if item).strip() or recheck_out or "Gateway restarted",
            "gateway_status_ok": recheck_ok,
        }

    start_ok, start_out = run_profiled_gateway_cmd(["openclaw", "gateway", "start"], 35)
    actions.append(f"gateway start: {'ok' if start_ok else 'failed'}")
    if start_out:
        actions.append(start_out)

    recheck_ok, recheck_status, recheck_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(recheck_status):
        return {
            "ok": True,
            "detail": "\n".join(item for item in actions if item).strip() or recheck_out or "Gateway started",
            "gateway_status_ok": recheck_ok,
        }

    install_ok, install_out = run_profiled_gateway_cmd(
        ["openclaw", "gateway", "install", "--force", "--port", str(FLEET_GATEWAY_PORT)],
        60,
    )
    actions.append(f"gateway install --force: {'ok' if install_ok else 'failed'}")
    if install_out:
        actions.append(install_out)

    start2_ok, start2_out = run_profiled_gateway_cmd(["openclaw", "gateway", "start"], 35)
    actions.append(f"gateway start (post-install): {'ok' if start2_ok else 'failed'}")
    if start2_out:
        actions.append(start2_out)

    recheck2_ok, recheck2_status, recheck2_out = gateway_status_snapshot(timeout=12)
    if gateway_cli_ready(recheck2_status):
        return {
            "ok": True,
            "detail": "\n".join(item for item in actions if item).strip() or recheck2_out or "Gateway reinstalled and started",
            "gateway_status_ok": recheck2_ok,
        }

    return {
        "ok": False,
        "detail": "\n".join(item for item in actions if item).strip() or recheck2_out or "Failed to restart gateway",
        "gateway_status_ok": recheck2_ok,
    }


def _terminate_pid(pid: int) -> bool:
    try:
        target = int(pid)
    except Exception:
        return False
    if target <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(target), "/F"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(target, signal.SIGTERM)
    except Exception:
        return False
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            os.kill(target, 0)
        except OSError:
            return True
        time.sleep(0.1)
    try:
        os.kill(target, signal.SIGKILL)
    except Exception:
        return False
    return True


def stop_openclaw_gateway_report() -> dict[str, Any]:
    actions: list[str] = []

    gw_ok, gw_status, gw_out = gateway_status_snapshot(timeout=12)
    if not gateway_service_running(gw_status):
        return {
            "ok": True,
            "already_stopped": True,
            "detail": gw_out or "Gateway already stopped",
            "gateway_status_ok": gw_ok,
            "actions": actions,
        }

    stop_ok, stop_out = run_profiled_gateway_cmd(["openclaw", "gateway", "stop"], 35)
    actions.append(f"gateway stop: {'ok' if stop_ok else 'failed'}")
    if stop_out:
        actions.append(stop_out)

    recheck_ok, recheck_status, recheck_out = gateway_status_snapshot(timeout=12)
    running = gateway_service_running(recheck_status)
    removed: list[int] = []
    if running:
        removed = evict_gateway_listener_pids(
            recheck_status,
            terminate_pid=_terminate_pid,
            listener_pids=gateway_listener_pids,
        )
        if removed:
            actions.append(f"evicted stale gateway listener pid(s): {', '.join(str(pid) for pid in removed)}")
        recheck2_ok, recheck2_status, recheck2_out = gateway_status_snapshot(timeout=12)
        running = gateway_service_running(recheck2_status)
        recheck_ok, recheck_out = recheck2_ok, recheck2_out

    return {
        "ok": not running,
        "already_stopped": False,
        "detail": "\n".join(item for item in actions if item).strip() or recheck_out or "Gateway stopped",
        "gateway_status_ok": recheck_ok,
        "actions": actions,
        "evicted_pids": removed,
    }


def repair_gateway_device_token_mismatch(
    *,
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
    status_snapshot: Callable[[int], tuple[bool, dict[str, Any], str]],
    listener_pids: Callable[[dict[str, Any]], list[int]],
    evict_listener_pids: Callable[[dict[str, Any], set[int] | None], list[int]],
    fleet_gateway_port: Callable[[], int],
) -> dict[str, Any]:
    def _is_token_mismatch(status_payload: dict[str, Any], raw_output: str) -> bool:
        rpc = status_payload.get("rpc", {}) if isinstance(status_payload.get("rpc"), dict) else {}
        rpc_error = str(rpc.get("error", "")).strip()
        lowered = f"{str(raw_output or '').lower()} {rpc_error.lower()}".strip()
        return "token mismatch" in lowered

    gw_ok, gw_status, gw_out = status_snapshot(12)
    mismatch = _is_token_mismatch(gw_status, gw_out)
    if not mismatch:
        return {"ok": True, "mismatch_detected": False, "repaired": False, "detail": gw_out if gw_ok else ""}

    actions: list[str] = []
    stale_pids = set(listener_pids(gw_status))
    restart_ok, restart_out = run_cmd(["openclaw", "gateway", "restart"], 35)
    if not restart_ok:
        start_ok, start_out = run_cmd(["openclaw", "gateway", "start"], 35)
        restart_ok = start_ok
        restart_out = start_out
    actions.append(f"gateway restart: {'ok' if restart_ok else 'failed'}")
    if restart_out:
        actions.append(restart_out)

    recheck_ok, recheck_status, recheck_out = status_snapshot(12)
    repaired = bool(recheck_ok) and not _is_token_mismatch(recheck_status, recheck_out)

    if not repaired:
        install_ok, install_out = run_cmd(
            ["openclaw", "gateway", "install", "--force", "--port", str(fleet_gateway_port())],
            60,
        )
        actions.append(f"gateway install --force: {'ok' if install_ok else 'failed'}")
        if install_out:
            actions.append(install_out)

        restart2_ok, restart2_out = run_cmd(["openclaw", "gateway", "restart"], 35)
        if not restart2_ok:
            start2_ok, start2_out = run_cmd(["openclaw", "gateway", "start"], 35)
            restart2_ok = start2_ok
            restart2_out = start2_out
        actions.append(f"gateway restart (post-install): {'ok' if restart2_ok else 'failed'}")
        if restart2_out:
            actions.append(restart2_out)

        recheck2_ok, recheck2_status, recheck2_out = status_snapshot(12)
        recheck_ok, recheck_out = recheck2_ok, recheck2_out
        repaired = bool(recheck2_ok) and not _is_token_mismatch(recheck2_status, recheck2_out)
        if not repaired:
            current_pids = set(listener_pids(recheck2_status))
            candidate_pids = stale_pids | current_pids
            removed = evict_listener_pids(recheck2_status, candidate_pids or None)
            if removed:
                actions.append(f"evicted stale gateway listener pid(s): {', '.join(str(pid) for pid in removed)}")
                start3_ok, start3_out = run_cmd(["openclaw", "gateway", "start"], 35)
                actions.append(f"gateway start (post-evict): {'ok' if start3_ok else 'failed'}")
                if start3_out:
                    actions.append(start3_out)
                recheck3_ok, recheck3_status, recheck3_out = status_snapshot(12)
                recheck_ok, recheck_out = recheck3_ok, recheck3_out
                repaired = bool(recheck3_ok) and not _is_token_mismatch(recheck3_status, recheck3_out)
    return {
        "ok": repaired,
        "mismatch_detected": True,
        "repaired": repaired,
        "detail": recheck_out,
        "actions": actions,
    }


def ensure_gateway_running_for_pairing(
    *,
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
    status_snapshot: Callable[[int], tuple[bool, dict[str, Any], str]],
    cli_ready: Callable[[dict[str, Any]], bool],
    evict_listener_pids: Callable[[dict[str, Any], set[int] | None], list[int]],
    fleet_gateway_port: Callable[[], int],
) -> dict[str, Any]:
    actions: list[str] = []

    gw_ok, gw_status, gw_out = status_snapshot(12)
    if cli_ready(gw_status):
        return {
            "ok": True,
            "already_running": True,
            "detail": gw_out,
            "status_ok": gw_ok,
            "gateway_status_ok": gw_ok,
            "actions": actions,
        }

    restart_ok, restart_out = run_cmd(["openclaw", "gateway", "restart"], 35)
    actions.append(f"gateway restart: {'ok' if restart_ok else 'failed'}")
    if restart_out:
        actions.append(restart_out)
    if not restart_ok:
        start_ok, start_out = run_cmd(["openclaw", "gateway", "start"], 35)
        restart_ok = start_ok
        restart_out = start_out
        actions.append(f"gateway start: {'ok' if start_ok else 'failed'}")
        if start_out:
            actions.append(start_out)

    recheck_ok, recheck_status, recheck_out = status_snapshot(12)
    running = cli_ready(recheck_status)
    if not running:
        install_ok, install_out = run_cmd(
            ["openclaw", "gateway", "install", "--force", "--port", str(fleet_gateway_port())],
            60,
        )
        actions.append(f"gateway install --force: {'ok' if install_ok else 'failed'}")
        if install_out:
            actions.append(install_out)
        start2_ok, start2_out = run_cmd(["openclaw", "gateway", "start"], 35)
        actions.append(f"gateway start (post-install): {'ok' if start2_ok else 'failed'}")
        if start2_out:
            actions.append(start2_out)
        recheck2_ok, recheck2_status, recheck2_out = status_snapshot(12)
        running = cli_ready(recheck2_status)
        recheck_ok, recheck_out = recheck2_ok, recheck2_out
        if not running:
            removed = evict_listener_pids(recheck2_status, None)
            if removed:
                actions.append(f"evicted stale gateway listener pid(s): {', '.join(str(pid) for pid in removed)}")
                start3_ok, start3_out = run_cmd(["openclaw", "gateway", "start"], 35)
                actions.append(f"gateway start (post-evict): {'ok' if start3_ok else 'failed'}")
                if start3_out:
                    actions.append(start3_out)
                recheck3_ok, recheck3_status, recheck3_out = status_snapshot(12)
                running = cli_ready(recheck3_status)
                recheck_ok, recheck_out = recheck3_ok, recheck3_out
    return {
        "ok": running,
        "already_running": False,
        "restart_attempt_ok": restart_ok,
        "restart_detail": restart_out,
        "detail": recheck_out,
        "status_ok": recheck_ok,
        "gateway_status_ok": recheck_ok,
        "actions": actions,
    }
