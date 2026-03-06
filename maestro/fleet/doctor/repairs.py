"""Doctor repair helpers and gateway mutation logic."""

from __future__ import annotations

import json
import os
import platform
import secrets
from pathlib import Path
from typing import Any, Callable

from .checks import DoctorCheck


def sync_gateway_auth_tokens(
    config: dict[str, Any],
    config_path: Path,
    profile: str,
    fix: bool,
    *,
    fleet_profile: str,
    fleet_gateway_port: Callable[[], int],
    is_placeholder: Callable[[str | None], bool],
    save_json: Callable[[Path, Any], None],
) -> DoctorCheck:
    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        gateway = {}
        config["gateway"] = gateway

    auth = gateway.get("auth")
    if not isinstance(auth, dict):
        auth = {}
        gateway["auth"] = auth

    remote = gateway.get("remote")
    if not isinstance(remote, dict):
        remote = {}
        gateway["remote"] = remote

    raw_auth = auth.get("token")
    auth_token = str(raw_auth).strip() if isinstance(raw_auth, str) else ""
    raw_remote = remote.get("token")
    remote_token = str(raw_remote).strip() if isinstance(raw_remote, str) else ""
    expected_remote_url = f"ws://127.0.0.1:{fleet_gateway_port()}" if profile == fleet_profile else ""
    current_remote_url = str(remote.get("url", "")).strip() if isinstance(remote.get("url"), str) else ""
    bad_remote_url = bool(expected_remote_url and current_remote_url != expected_remote_url)

    bad_auth = (not auth_token) or is_placeholder(auth_token)
    bad_remote = (not remote_token) or is_placeholder(remote_token)
    mismatch = bool(auth_token and remote_token and auth_token != remote_token)

    if not (bad_auth or bad_remote or mismatch or bad_remote_url):
        return DoctorCheck(
            name="gateway_auth_tokens",
            ok=True,
            detail=(
                "gateway.auth.token and gateway.remote.token are aligned"
                if not expected_remote_url else "gateway tokens aligned; fleet remote URL configured"
            ),
        )

    if not fix:
        return DoctorCheck(
            name="gateway_auth_tokens",
            ok=False,
            detail=(
                "Gateway auth token missing/invalid, mismatched, or remote URL not configured. "
                "Run maestro doctor --fix."
            ),
        )

    token = ""
    if auth_token and not is_placeholder(auth_token):
        token = auth_token
    elif remote_token and not is_placeholder(remote_token):
        token = remote_token
    else:
        token = secrets.token_urlsafe(32)

    auth["token"] = token
    remote["token"] = token
    if profile == fleet_profile:
        remote["url"] = expected_remote_url
    save_json(config_path, config)
    return DoctorCheck(
        name="gateway_auth_tokens",
        ok=True,
        detail="Normalized gateway auth token and synced remote token",
        fixed=True,
    )


def sync_telegram_bindings(
    config: dict[str, Any],
    config_path: Path,
    fix: bool,
    *,
    ensure_telegram_account_bindings: Callable[[dict[str, Any]], list[Any]],
    save_json: Callable[[Path, Any], None],
) -> DoctorCheck:
    changes = ensure_telegram_account_bindings(config)
    if not changes:
        return DoctorCheck(
            name="telegram_bindings",
            ok=True,
            detail="Telegram account routing bindings are aligned",
        )

    if not fix:
        return DoctorCheck(
            name="telegram_bindings",
            ok=False,
            detail=(
                f"{len(changes)} Telegram account binding(s) missing. "
                "Run maestro doctor --fix."
            ),
        )

    save_json(config_path, config)
    return DoctorCheck(
        name="telegram_bindings",
        ok=True,
        detail=f"Added {len(changes)} Telegram account routing binding(s)",
        fixed=True,
    )


def enforce_commander_telegram_policy(
    config: dict[str, Any],
    config_path: Path,
    *,
    profile: str,
    fleet_profile: str,
    fix: bool,
    save_json: Callable[[Path, Any], None],
) -> DoctorCheck:
    if profile != fleet_profile:
        return DoctorCheck(
            name="commander_telegram_policy",
            ok=True,
            detail="Not applicable outside Fleet profile",
        )
    channels = config.get("channels")
    if not isinstance(channels, dict):
        channels = {}
        config["channels"] = channels
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        telegram = {}
        channels["telegram"] = telegram
    accounts = telegram.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        telegram["accounts"] = accounts
    commander = accounts.get("maestro-company")
    if not isinstance(commander, dict):
        return DoctorCheck(
            name="commander_telegram_policy",
            ok=False,
            detail="Commander Telegram account missing",
            warning=True,
        )
    dm_policy = str(commander.get("dmPolicy", "")).strip().lower()
    group_policy = str(commander.get("groupPolicy", "")).strip().lower()
    stream_mode = str(commander.get("streamMode", "")).strip().lower()
    ok = dm_policy == "pairing" and group_policy == "allowlist" and stream_mode == "partial"
    if ok:
        return DoctorCheck(
            name="commander_telegram_policy",
            ok=True,
            detail="Commander Telegram policy locked (dm=pairing, groups=allowlist)",
        )
    if not fix:
        return DoctorCheck(
            name="commander_telegram_policy",
            ok=False,
            detail="Commander Telegram policy not strict; run maestro doctor --fix",
            warning=True,
        )
    commander["dmPolicy"] = "pairing"
    commander["groupPolicy"] = "allowlist"
    commander["streamMode"] = "partial"
    save_json(config_path, config)
    return DoctorCheck(
        name="commander_telegram_policy",
        ok=True,
        detail="Enforced strict Commander Telegram policy (dm=pairing, groups=allowlist)",
        fixed=True,
    )


def sync_gateway_launchagent_token(
    *,
    fix: bool,
    token_check: DoctorCheck,
    profile: str,
    fleet_profile: str,
    fleet_gateway_port: Callable[[], int],
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
    gateway_running: Callable[[], bool],
) -> DoctorCheck:
    if not token_check.fixed:
        return DoctorCheck(
            name="gateway_launchagent_sync",
            ok=True,
            detail="Gateway LaunchAgent token sync not needed",
        )

    if not fix:
        return DoctorCheck(
            name="gateway_launchagent_sync",
            ok=False,
            detail="Gateway token changed but LaunchAgent sync skipped (fix mode off)",
            warning=True,
        )

    if profile == fleet_profile:
        port = fleet_gateway_port()
        install_ok, install_out = run_cmd(
            ["openclaw", "gateway", "install", "--force", "--port", str(port)],
            60,
        )
        start_ok, start_out = run_cmd(["openclaw", "gateway", "start"], 35)
        if (install_ok or start_ok) and gateway_running():
            return DoctorCheck(
                name="gateway_launchagent_sync",
                ok=True,
                detail=f"Fleet mode: refreshed profiled gateway service on port {port}",
                fixed=True,
            )
        return DoctorCheck(
            name="gateway_launchagent_sync",
            ok=False,
            detail=(
                f"Fleet mode gateway refresh failed: install={install_out or install_ok}, "
                f"start={start_out or start_ok}"
            ),
            warning=True,
        )

    ok, out = run_cmd(["openclaw", "gateway", "install", "--force"], 60)
    if ok:
        return DoctorCheck(
            name="gateway_launchagent_sync",
            ok=True,
            detail="Reinstalled OpenClaw LaunchAgent to sync gateway token",
            fixed=True,
        )
    return DoctorCheck(
        name="gateway_launchagent_sync",
        ok=False,
        detail=f"Failed to sync LaunchAgent token: {out}",
        warning=True,
    )


def repair_cli_device_pairing(
    fix: bool,
    *,
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
) -> DoctorCheck:
    pending_ok, pending_out = run_cmd(["openclaw", "devices", "list", "--json"], 20)
    if not pending_ok:
        lowered = str(pending_out or "").lower()
        if "pairing required" in lowered:
            if not fix:
                return DoctorCheck(
                    name="cli_device_pairing",
                    ok=False,
                    detail="CLI requires gateway device pairing approval (run maestro doctor --fix)",
                )
            return DoctorCheck(
                name="cli_device_pairing",
                ok=False,
                detail=(
                    "Gateway requires pairing but pending requests could not be listed. "
                    "Run openclaw devices list."
                ),
                warning=True,
            )
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=f"Could not verify device pairing: {pending_out}",
            warning=True,
        )

    try:
        payload = json.loads(pending_out)
    except Exception:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail="Could not parse pending device request payload",
            warning=True,
        )

    pending = payload.get("pending")
    pending_list = pending if isinstance(pending, list) else []
    if not pending_list:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=True,
            detail="CLI device pairing access healthy",
        )

    if not fix:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail="CLI requires gateway device pairing approval (run maestro doctor --fix)",
        )

    if len(pending_list) > 1:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=(
                f"Multiple pending device requests ({len(pending_list)}); "
                "approve manually with openclaw devices list/approve."
            ),
            warning=True,
        )

    approve_ok, approve_out = run_cmd(["openclaw", "devices", "approve", "--latest", "--json"], 20)
    if not approve_ok:
        return DoctorCheck(
            name="cli_device_pairing",
            ok=False,
            detail=f"Failed to auto-approve device pairing: {approve_out}",
            warning=True,
        )

    return DoctorCheck(
        name="cli_device_pairing",
        ok=True,
        detail="Approved pending CLI device pairing request",
        fixed=True,
    )


def restart_gateway(
    home_dir: Path,
    fix: bool,
    *,
    profile: str,
    fleet_profile: str,
    fleet_gateway_port: Callable[[], int],
    run_cmd: Callable[[list[str], int], tuple[bool, str]],
    gateway_running: Callable[[], bool],
    launchagent_path: Callable[[Path], Path],
) -> DoctorCheck:
    ok, out = run_cmd(["openclaw", "gateway", "restart"], 35)
    if ok and gateway_running():
        return DoctorCheck(
            name="gateway_restart",
            ok=True,
            detail="openclaw gateway restart completed",
            fixed=fix,
        )
    if ok:
        run_cmd(["openclaw", "gateway", "start"], 35)
        if gateway_running():
            return DoctorCheck(
                name="gateway_restart",
                ok=True,
                detail="openclaw gateway restart/start completed",
                fixed=fix,
            )

    if profile == fleet_profile:
        port = fleet_gateway_port()
        run_cmd(["openclaw", "gateway", "install", "--force", "--port", str(port)], 60)
        start_ok, start_out = run_cmd(["openclaw", "gateway", "start"], 35)
        if start_ok and gateway_running():
            return DoctorCheck(
                name="gateway_restart",
                ok=True,
                detail=f"openclaw gateway reinstalled and started on port {port}",
                fixed=fix,
            )
        return DoctorCheck(
            name="gateway_restart",
            ok=False,
            detail=f"Gateway restart/start failed in fleet mode: {start_out or out}",
            warning=True,
        )

    if platform.system().lower() == "darwin":
        plist_path = launchagent_path(home_dir)
        if plist_path.exists():
            uid = str(os.getuid())
            label = "ai.openclaw.gateway"
            run_cmd(["launchctl", "bootout", f"gui/{uid}/{label}"], 15)
            run_cmd(["pkill", "-f", "openclaw-gateway"], 8)
            run_cmd(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)], 15)
            kick_ok, kick_out = run_cmd(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"], 15)
            if kick_ok:
                return DoctorCheck(
                    name="gateway_restart",
                    ok=True,
                    detail="Gateway restarted via launchctl fallback",
                    fixed=fix,
                )
            return DoctorCheck(
                name="gateway_restart",
                ok=False,
                detail=f"Gateway restart fallback failed: {kick_out or out}",
                warning=True,
            )

    return DoctorCheck(
        name="gateway_restart",
        ok=False,
        detail=f"Gateway restart failed: {out}",
        warning=True,
    )
