"""Network URL helpers shared across Maestro products."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Callable

CommandRunner = Callable[[list[str], int], tuple[bool, str]]


def _default_runner(args: list[str], timeout: int = 6) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode == 0, output


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

    localhost = f"http://localhost:{web_port}{path}"

    tailnet_ip: str | None = None
    if shutil.which("tailscale"):
        ok, out = runner(["tailscale", "ip", "-4"], timeout=5)
        if ok:
            tailnet_ip = _parse_tailscale_ipv4(out)

    tailnet = f"http://{tailnet_ip}:{web_port}{path}" if tailnet_ip else None
    return {
        "localhost_url": localhost,
        "tailnet_url": tailnet,
        "recommended_url": tailnet or localhost,
        "tailscale_ip": tailnet_ip,
    }
