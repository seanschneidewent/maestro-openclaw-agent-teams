"""Installer launcher helpers for clean website one-liner endpoints."""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException


INSTALLER_SCRIPT_BASE_URL_DEFAULT = (
    "https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts"
)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _shell_single_quote(value: str) -> str:
    clean = str(value)
    return "'" + clean.replace("'", "'\"'\"'") + "'"


def _first_env_value(*keys: str) -> str:
    for key in keys:
        value = _clean_text(os.environ.get(key))
        if value:
            return value
    return ""


def _installer_script_base_url() -> str:
    return _first_env_value("MAESTRO_INSTALLER_SCRIPT_BASE_URL") or INSTALLER_SCRIPT_BASE_URL_DEFAULT


def _installer_free_script_url() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_FREE_SCRIPT_URL")
    if configured:
        return configured
    return f"{_installer_script_base_url().rstrip('/')}/install-maestro-free-macos.sh"


def _installer_pro_script_url() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_PRO_SCRIPT_URL")
    if configured:
        return configured
    return f"{_installer_script_base_url().rstrip('/')}/install-maestro-pro-macos.sh"


def _installer_install_script_url() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_INSTALL_SCRIPT_URL")
    if configured:
        return configured
    return f"{_installer_script_base_url().rstrip('/')}/install-maestro-install-macos.sh"


def _installer_fleet_script_url() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_FLEET_SCRIPT_URL")
    if configured:
        return configured
    return f"{_installer_script_base_url().rstrip('/')}/install-maestro-fleet-linux.sh"


def _installer_fleet_base_script_url() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_FLEET_BASE_SCRIPT_URL")
    if configured:
        return configured
    return f"{_installer_script_base_url().rstrip('/')}/install-maestro-fleet.sh"


def _installer_core_package_spec() -> str:
    return _first_env_value("MAESTRO_INSTALLER_CORE_PACKAGE_SPEC", "MAESTRO_CORE_PACKAGE_SPEC")


def _installer_pro_package_spec() -> str:
    return _first_env_value("MAESTRO_INSTALLER_PRO_PACKAGE_SPEC", "MAESTRO_PRO_PACKAGE_SPEC")


def _installer_fleet_package_spec() -> str:
    return _first_env_value("MAESTRO_INSTALLER_FLEET_PACKAGE_SPEC", "MAESTRO_FLEET_PACKAGE_SPEC")


def _installer_auto_approve() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_AUTO", "MAESTRO_INSTALL_AUTO")
    return configured or "1"


def _installer_openclaw_profile() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_OPENCLAW_PROFILE", "MAESTRO_OPENCLAW_PROFILE")
    return configured or "maestro-solo"


def _installer_fleet_require_tailscale() -> str:
    configured = _first_env_value(
        "MAESTRO_INSTALLER_FLEET_REQUIRE_TAILSCALE",
        "MAESTRO_FLEET_REQUIRE_TAILSCALE",
    )
    return configured or "1"


def _installer_fleet_deploy() -> str:
    configured = _first_env_value("MAESTRO_INSTALLER_FLEET_DEPLOY", "MAESTRO_FLEET_DEPLOY")
    return configured or "1"


def build_installer_script(*, flow: str, billing_base_url: str, intent: str = "") -> str:
    clean_flow = _clean_text(flow).lower()
    if clean_flow not in {"free", "pro", "install"}:
        raise HTTPException(status_code=400, detail="invalid_install_flow")

    clean_intent = _clean_text(intent).lower()
    if clean_intent == "core":
        clean_intent = "free"
    if clean_intent and clean_intent not in {"free", "pro"}:
        raise HTTPException(status_code=400, detail="invalid_install_intent")

    core_spec = _installer_core_package_spec()
    pro_spec = _installer_pro_package_spec()
    if clean_flow == "free" and not core_spec:
        raise HTTPException(status_code=503, detail="installer_not_configured:missing_core_package_spec")
    if clean_flow == "pro" and not pro_spec and not core_spec:
        raise HTTPException(status_code=503, detail="installer_not_configured:missing_pro_or_core_package_spec")
    if clean_flow == "install":
        if clean_intent == "free" and not core_spec:
            raise HTTPException(status_code=503, detail="installer_not_configured:missing_core_package_spec")
        if not core_spec and not pro_spec:
            raise HTTPException(status_code=503, detail="installer_not_configured:missing_pro_or_core_package_spec")

    script_base_url = _installer_script_base_url().rstrip("/")
    if clean_flow == "free":
        script_url = _installer_free_script_url()
    elif clean_flow == "pro":
        script_url = _installer_pro_script_url()
    else:
        script_url = _installer_install_script_url()
    env_assignments: list[tuple[str, str]] = []
    if core_spec:
        env_assignments.append(("MAESTRO_CORE_PACKAGE_SPEC", core_spec))
    if pro_spec:
        env_assignments.append(("MAESTRO_PRO_PACKAGE_SPEC", pro_spec))
    env_assignments.append(("MAESTRO_INSTALL_AUTO", _installer_auto_approve()))
    env_assignments.append(("MAESTRO_INSTALL_BASE_URL", f"{script_base_url}/install-maestro-macos.sh"))
    env_assignments.append(("MAESTRO_OPENCLAW_PROFILE", _installer_openclaw_profile()))
    env_assignments.append(("MAESTRO_INSTALL_FLOW", clean_flow))
    if clean_intent:
        env_assignments.append(("MAESTRO_INSTALL_INTENT", clean_intent))
    if billing_base_url:
        env_assignments.append(("MAESTRO_BILLING_URL", billing_base_url))

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated by Maestro installer launcher.",
    ]
    for key, value in env_assignments:
        lines.append(f"export {key}={_shell_single_quote(value)}")
    lines.append(f"curl -fsSL {_shell_single_quote(script_url)} | bash")

    return "\n".join(lines) + "\n"


def build_fleet_installer_script(*, billing_base_url: str) -> str:
    fleet_spec = _installer_fleet_package_spec()
    if not fleet_spec:
        raise HTTPException(status_code=503, detail="installer_not_configured:missing_fleet_package_spec")

    env_assignments: list[tuple[str, str]] = [
        ("MAESTRO_INSTALL_AUTO", _installer_auto_approve()),
        ("MAESTRO_FLEET_PACKAGE_SPEC", fleet_spec),
        ("MAESTRO_INSTALL_BASE_URL", _installer_fleet_base_script_url()),
        ("MAESTRO_FLEET_REQUIRE_TAILSCALE", _installer_fleet_require_tailscale()),
        ("MAESTRO_FLEET_DEPLOY", _installer_fleet_deploy()),
    ]
    if billing_base_url:
        env_assignments.append(("MAESTRO_BILLING_URL", billing_base_url))

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated by Maestro Fleet installer launcher.",
    ]
    for key, value in env_assignments:
        lines.append(f"export {key}={_shell_single_quote(value)}")
    lines.append(f"curl -fsSL {_shell_single_quote(_installer_fleet_script_url())} | bash")
    return "\n".join(lines) + "\n"
