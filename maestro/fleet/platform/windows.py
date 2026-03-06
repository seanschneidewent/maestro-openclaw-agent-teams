"""Windows-specific Fleet runtime helpers."""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path
from typing import Callable


def fleet_server_task_name(*, profile: str) -> str:
    import re

    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(profile or "")).strip("-.") or "maestro-fleet"
    return f"Maestro Fleet Server ({safe})"


def ps_single_quote(value: str) -> str:
    return str(value or "").replace("'", "''")


def run_windows_powershell(script: str, *, timeout: int = 45) -> tuple[bool, str]:
    encoded = base64.b64encode(str(script or "").encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    output = "\n".join(part for part in [stdout, stderr] if part).strip()
    return result.returncode == 0, output


def write_windows_server_task_script(
    *,
    script_path: Path,
    log_path: Path,
    port: int,
    store_root: Path,
    host: str,
    profile: str,
    now_iso: Callable[[], str],
) -> None:
    python_exe = Path(sys.executable).resolve()
    script_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        f"$env:MAESTRO_OPENCLAW_PROFILE = '{ps_single_quote(profile)}'",
        "$env:PYTHONUTF8 = '1'",
        "$env:PYTHONIOENCODING = 'utf-8'",
        f"$logPath = '{ps_single_quote(str(log_path))}'",
        f"$storeRoot = '{ps_single_quote(str(store_root))}'",
        f"$hostName = '{ps_single_quote(str(host))}'",
        f"$pythonExe = '{ps_single_quote(str(python_exe))}'",
        (
            "Add-Content -Path $logPath -Value "
            f"\"`n[{now_iso()}] starting scheduled Fleet server on port {int(port)}\""
        ),
        (
            "& $pythonExe '-m' 'maestro.cli' 'serve' '--port' "
            f"'{int(port)}' '--store' $storeRoot '--host' $hostName *>> $logPath"
        ),
    ]
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_windows_server_task(
    *,
    task_name: str,
    script_path: Path,
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
) -> tuple[bool, str]:
    action = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{script_path}"'
    create_ok, create_out = run_cmd(
        ["schtasks", "/Create", "/TN", task_name, "/TR", action, "/SC", "ONCE", "/ST", "00:00", "/F"],
        45,
    )
    query_ok, query_out = run_cmd(["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"], 30)
    detail = "\n".join(part for part in [create_out, query_out] if part).strip()
    return create_ok and query_ok, detail


def start_windows_server_task_runner(
    *,
    task_name: str,
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
) -> tuple[bool, str]:
    start_ok, start_out = run_cmd(["schtasks", "/Run", "/TN", task_name], 30)
    query_ok, query_out = run_cmd(["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"], 30)
    detail = "\n".join(part for part in [start_out, query_out] if part).strip()
    return start_ok and query_ok, detail

