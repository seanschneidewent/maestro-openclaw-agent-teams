"""Maestro doctor: validate and repair common runtime misconfigurations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .control_plane import ensure_telegram_account_bindings, resolve_network_urls, sync_fleet_registry
from .fleet.doctor import checks as doctor_checks
from .fleet.doctor import repairs as doctor_repairs
from .fleet.doctor.checks import DoctorCheck
from .fleet.shared import subprocesses as fleet_subprocesses
from .openclaw_profile import (
    DEFAULT_FLEET_OPENCLAW_PROFILE,
    openclaw_config_path,
    openclaw_state_root,
    prepend_openclaw_profile_args,
)
from .profile import PROFILE_FLEET, PROFILE_SOLO, resolve_profile
from .utils import load_json, save_json
from .install_state import resolve_fleet_store_root, save_install_state
from .workspace_templates import (
    provider_env_key_for_model,
    render_company_agents_md,
    render_personal_agents_md,
    render_personal_tools_md,
    render_tools_md,
)


PROVIDER_ENV_KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")
_ENV_TRUE = {"1", "true", "yes", "on"}
DEFAULT_FLEET_GATEWAY_PORT = 18789


def _safe_print(message: str) -> None:
    text = str(message)
    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe)

def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    markers = ("<PASTE_", "PASTE_", "YOUR_KEY_HERE", "CHANGEME")
    text = value.strip()
    return any(marker in text for marker in markers)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _ENV_TRUE


def _fleet_gateway_port() -> int:
    return DEFAULT_FLEET_GATEWAY_PORT


def _default_openclaw_profile_for_runtime(home_dir: Path) -> str:
    profile = resolve_profile(home_dir=home_dir)
    return DEFAULT_FLEET_OPENCLAW_PROFILE if profile == PROFILE_FLEET else ""


def _load_openclaw_config(home_dir: Path, *, profile: str | None = None) -> tuple[dict[str, Any], Path]:
    resolved_profile = profile if isinstance(profile, str) and profile else resolve_profile(home_dir=home_dir)
    default_profile = DEFAULT_FLEET_OPENCLAW_PROFILE if resolved_profile == PROFILE_FLEET else ""
    config_path = openclaw_config_path(home_dir=home_dir, default_profile=default_profile)
    payload = load_json(config_path)
    if not isinstance(payload, dict):
        payload = {}
    return payload, config_path


def _resolve_company_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    company = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("id") == "maestro-company"),
        None,
    )
    if isinstance(company, dict):
        return company
    default_agent = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("default")),
        None,
    )
    return default_agent if isinstance(default_agent, dict) else {}


def _resolve_personal_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents", {}) if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
    personal = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("id") == "maestro-personal"),
        None,
    )
    if isinstance(personal, dict):
        return personal
    default_agent = next(
        (a for a in agent_list if isinstance(a, dict) and a.get("default")),
        None,
    )
    return default_agent if isinstance(default_agent, dict) else {}


def _infer_store_root(store_override: str | None, workspace_root: Path | None) -> Path:
    _ = workspace_root
    return resolve_fleet_store_root(store_override=store_override)


def _launchagent_path(home_dir: Path, *, profile: str) -> Path:
    label = "ai.openclaw.maestro-fleet.plist" if profile == PROFILE_FLEET else "ai.openclaw.gateway.plist"
    return home_dir / "Library" / "LaunchAgents" / label


def _sync_launchagent_env(
    home_dir: Path,
    config_env: dict[str, Any],
    profile: str,
    fix: bool,
) -> DoctorCheck:
    return doctor_checks.sync_launchagent_env(
        home_dir,
        config_env,
        profile,
        fix,
        launchagent_path=lambda path: _launchagent_path(path, profile=profile),
        provider_env_keys=PROVIDER_ENV_KEYS,
        is_placeholder=_is_placeholder,
    )


def _sync_workspace_tools_md(
    workspace_root: Path | None,
    company_name: str,
    active_provider_env_key: str | None,
    profile: str,
    fix: bool,
) -> DoctorCheck:
    return doctor_checks.sync_workspace_tools_md(
        workspace_root,
        company_name,
        active_provider_env_key,
        profile,
        fix,
        fleet_profile=PROFILE_FLEET,
        render_tools_md=render_tools_md,
        render_personal_tools_md=render_personal_tools_md,
    )


def _sync_workspace_agents_md(
    workspace_root: Path | None,
    profile: str,
    fix: bool,
) -> DoctorCheck:
    return doctor_checks.sync_workspace_agents_md(
        workspace_root,
        profile,
        fix,
        fleet_profile=PROFILE_FLEET,
        render_company_agents_md=render_company_agents_md,
        render_personal_agents_md=render_personal_agents_md,
    )


def _sync_workspace_env_role(
    workspace_root: Path | None,
    expected_role: str,
    fix: bool,
) -> DoctorCheck:
    return doctor_checks.sync_workspace_env_role(workspace_root, expected_role, fix)


def _read_workspace_env_value(
    workspace_root: Path | None,
    key: str,
) -> str:
    return doctor_checks.read_workspace_env_value(workspace_root, key)


def _tail_text(path: Path, max_bytes: int = 180_000) -> str:
    return doctor_checks.tail_text(path, max_bytes)


def _rotate_stale_sessions(
    home_dir: Path,
    fix: bool,
    *,
    profile: str,
) -> DoctorCheck:
    return doctor_checks.rotate_stale_sessions(
        home_dir,
        fix,
        profile=profile,
        fleet_profile=PROFILE_FLEET,
        default_openclaw_profile=DEFAULT_FLEET_OPENCLAW_PROFILE,
        openclaw_state_root=openclaw_state_root,
        load_json=load_json,
        save_json=save_json,
        tail_text_func=_tail_text,
    )


def _run_cmd(args: list[str], timeout: int = 25) -> tuple[bool, str]:
    default_profile = _default_openclaw_profile_for_runtime(Path.home().resolve())
    return fleet_subprocesses.run_profiled_cmd(
        args,
        timeout=timeout,
        prepend_profile_args=lambda cmd: prepend_openclaw_profile_args(cmd, default_profile=default_profile),
    )


def _sync_gateway_auth_tokens(
    config: dict[str, Any],
    config_path: Path,
    profile: str,
    fix: bool,
) -> DoctorCheck:
    return doctor_repairs.sync_gateway_auth_tokens(
        config,
        config_path,
        profile,
        fix,
        fleet_profile=PROFILE_FLEET,
        fleet_gateway_port=_fleet_gateway_port,
        is_placeholder=_is_placeholder,
        save_json=save_json,
    )


def _sync_telegram_bindings(
    config: dict[str, Any],
    config_path: Path,
    fix: bool,
) -> DoctorCheck:
    return doctor_repairs.sync_telegram_bindings(
        config,
        config_path,
        fix,
        ensure_telegram_account_bindings=ensure_telegram_account_bindings,
        save_json=save_json,
    )


def _enforce_commander_telegram_policy(
    config: dict[str, Any],
    config_path: Path,
    *,
    profile: str,
    fix: bool,
) -> DoctorCheck:
    return doctor_repairs.enforce_commander_telegram_policy(
        config,
        config_path,
        profile=profile,
        fleet_profile=PROFILE_FLEET,
        fix=fix,
        save_json=save_json,
    )


def _sync_gateway_launchagent_token(
    *,
    fix: bool,
    token_check: DoctorCheck,
    profile: str,
) -> DoctorCheck:
    return doctor_repairs.sync_gateway_launchagent_token(
        fix=fix,
        token_check=token_check,
        profile=profile,
        fleet_profile=PROFILE_FLEET,
        fleet_gateway_port=_fleet_gateway_port,
        run_cmd=lambda args, timeout: _run_cmd(args, timeout=timeout),
        gateway_running=_gateway_running,
    )


def _repair_cli_device_pairing(fix: bool) -> DoctorCheck:
    return doctor_repairs.repair_cli_device_pairing(
        fix,
        run_cmd=lambda args, timeout: _run_cmd(args, timeout=timeout),
    )


def _restart_gateway(home_dir: Path, fix: bool, *, profile: str) -> DoctorCheck:
    return doctor_repairs.restart_gateway(
        home_dir,
        fix,
        profile=profile,
        fleet_profile=PROFILE_FLEET,
        fleet_gateway_port=_fleet_gateway_port,
        run_cmd=lambda args, timeout: _run_cmd(args, timeout=timeout),
        gateway_running=_gateway_running,
        launchagent_path=lambda path: _launchagent_path(path, profile=profile),
    )


def _gateway_running() -> bool:
    return doctor_checks.gateway_running(run_cmd=lambda args, timeout: _run_cmd(args, timeout=timeout))


def build_doctor_report(
    fix: bool = False,
    store_override: str | None = None,
    restart_gateway: bool = True,
    field_access_required: bool | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    home = (home_dir or Path.home()).resolve()
    profile = resolve_profile(home_dir=home)
    config, config_path = _load_openclaw_config(home, profile=profile)
    checks: list[DoctorCheck] = []
    store_root = _infer_store_root(store_override, None)
    route_path = "/command-center" if profile == PROFILE_FLEET else "/workspace"
    network = resolve_network_urls(web_port=3000, route_path=route_path)
    require_field_access = (
        _env_flag("MAESTRO_FIELD_ACCESS_REQUIRED", default=False)
        if field_access_required is None
        else bool(field_access_required)
    )

    if not config_path.exists():
        checks.append(DoctorCheck(name="openclaw_config", ok=False, detail=f"Missing {config_path}"))
        return {
            "ok": False,
            "fix_mode": fix,
            "store_root": str(store_root),
            "recommended_url": network["recommended_url"],
            "field_access_required": require_field_access,
            "checks": [asdict(c) for c in checks],
        }

    checks.append(DoctorCheck(name="openclaw_config", ok=True, detail=f"Config loaded: {config_path}"))

    primary = _resolve_company_agent(config) if profile == PROFILE_FLEET else _resolve_personal_agent(config)
    workspace_raw = str(primary.get("workspace", "")).strip()
    workspace = Path(workspace_raw).expanduser().resolve() if workspace_raw else None
    workspace_auth_method = _read_workspace_env_value(workspace, "MAESTRO_MODEL_AUTH_METHOD").lower()
    model = str(primary.get("model", "")).strip()
    provider_env_key = provider_env_key_for_model(model) if model else None
    company_name = str(primary.get("name", "Company")).strip().replace("Maestro (", "").replace(")", "")
    expected_role = "company" if profile == PROFILE_FLEET else "project"

    if not primary:
        expected_agent = "maestro-company" if profile == PROFILE_FLEET else "maestro-personal"
        checks.append(DoctorCheck(name="primary_agent", ok=False, detail=f"{expected_agent} agent missing"))
    else:
        checks.append(DoctorCheck(name="primary_agent", ok=True, detail=f"{primary.get('id')} model={model or 'unknown'}"))

    config_env = config.get("env", {}) if isinstance(config.get("env"), dict) else {}
    if provider_env_key:
        raw_key = config_env.get(provider_env_key)
        key_value = str(raw_key).strip() if isinstance(raw_key, str) else ""
        if key_value and not _is_placeholder(key_value):
            checks.append(DoctorCheck(name="provider_key", ok=True, detail=f"{provider_env_key} present"))
        elif workspace_auth_method == "openclaw_oauth":
            checks.append(DoctorCheck(
                name="provider_key",
                ok=True,
                detail="OpenClaw OAuth configured; provider API key not required",
                warning=True,
            ))
        else:
            checks.append(DoctorCheck(name="provider_key", ok=False, detail=f"{provider_env_key} missing/placeholder"))
    else:
        checks.append(DoctorCheck(name="provider_key", ok=False, detail="Could not map model to provider key", warning=True))

    store_root = _infer_store_root(store_override, workspace)
    checks.append(DoctorCheck(
        name="store_root",
        ok=store_root.exists(),
        detail=f"{store_root}",
        warning=not store_root.exists(),
    ))
    if profile == PROFILE_FLEET:
        fleet_store_is_single_project = (store_root / "project.json").exists()
        checks.append(DoctorCheck(
            name="fleet_store_layout",
            ok=not fleet_store_is_single_project,
            detail=(
                "Fleet store root uses multi-project layout"
                if not fleet_store_is_single_project
                else (
                    "Fleet store root is a single-project store; point the commander workspace "
                    "MAESTRO_STORE at the parent directory that contains project folders"
                )
            ),
        ))

    registry = sync_fleet_registry(store_root)
    registry_projects = registry.get("projects", []) if isinstance(registry.get("projects"), list) else []
    active_registry_projects = [
        item for item in registry_projects
        if isinstance(item, dict) and str(item.get("status", "active")).strip().lower() != "archived"
    ]
    checks.append(DoctorCheck(
        name="registry_projects",
        ok=True,
        detail=f"{len(active_registry_projects)} active project maestro(s) registered",
        warning=True,
    ))
    slug_counts: dict[str, int] = {}
    for item in active_registry_projects:
        slug = str(item.get("project_slug", "")).strip()
        if not slug:
            continue
        slug_counts[slug] = slug_counts.get(slug, 0) + 1
    duplicate_slugs = sorted(slug for slug, count in slug_counts.items() if count > 1)
    checks.append(DoctorCheck(
        name="registry_unique_project_slugs",
        ok=not duplicate_slugs,
        detail=(
            "All active registry project slugs are unique"
            if not duplicate_slugs
            else "Duplicate registry project slugs: " + ", ".join(duplicate_slugs)
        ),
    ))

    checks.append(_sync_workspace_tools_md(
        workspace,
        company_name=company_name,
        active_provider_env_key=provider_env_key,
        profile=profile,
        fix=fix,
    ))
    checks.append(_sync_workspace_agents_md(workspace, profile=profile, fix=fix))
    checks.append(_sync_workspace_env_role(workspace, expected_role=expected_role, fix=fix))
    checks.append(_sync_launchagent_env(home, config_env=config_env, profile=profile, fix=fix))
    checks.append(_rotate_stale_sessions(home, fix=fix, profile=profile))
    checks.append(_sync_telegram_bindings(config, config_path=config_path, fix=fix))
    checks.append(
        _enforce_commander_telegram_policy(
            config,
            config_path=config_path,
            profile=profile,
            fix=fix,
        )
    )
    gateway_token_check = _sync_gateway_auth_tokens(
        config,
        config_path=config_path,
        profile=profile,
        fix=fix,
    )
    checks.append(gateway_token_check)
    checks.append(
        _sync_gateway_launchagent_token(
            fix=fix,
            token_check=gateway_token_check,
            profile=profile,
        )
    )

    if restart_gateway and fix:
        checks.append(_restart_gateway(home, fix=fix, profile=profile))
        time.sleep(1.0)

    checks.append(_repair_cli_device_pairing(fix=fix))

    gateway_ok = _gateway_running()
    checks.append(DoctorCheck(
        name="gateway_running",
        ok=gateway_ok,
        detail="openclaw gateway service running" if gateway_ok else "openclaw gateway service not running",
        warning=not gateway_ok,
    ))

    if profile == PROFILE_FLEET:
        checks.append(DoctorCheck(name="command_center_url", ok=True, detail=network["recommended_url"]))
    else:
        local_workspace = str(network.get("localhost_url", "http://localhost:3000/workspace"))
        tailnet_workspace = str(network.get("tailnet_url") or "")
        preferred = tailnet_workspace or local_workspace
        checks.append(DoctorCheck(name="workspace_url", ok=True, detail=preferred))
        if tailnet_workspace:
            checks.append(DoctorCheck(
                name="tailscale_workspace_access",
                ok=True,
                detail=f"Field access ready: {tailnet_workspace}",
            ))
        else:
            detail = (
                "No Tailscale IPv4 detected. Field access unavailable; "
                "connect this machine to Tailscale (`tailscale up`)."
            )
            checks.append(DoctorCheck(
                name="tailscale_workspace_access",
                ok=not require_field_access,
                detail=detail,
                warning=not require_field_access,
            ))

    if fix:
        save_install_state(
            {
                "version": 2,
                "profile": profile,
                "fleet_enabled": profile == PROFILE_FLEET,
                "workspace_root": str(workspace) if workspace else "",
                "store_root": str(store_root),
                "fleet_store_root": str(store_root),
                "company_name": company_name or "Company",
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            home_dir=home,
        )

    ok = all(c.ok or c.warning for c in checks)
    return {
        "ok": ok,
        "fix_mode": fix,
        "profile": profile,
        "store_root": str(store_root),
        "recommended_url": network["recommended_url"],
        "field_access_required": require_field_access,
        "checks": [asdict(c) for c in checks],
    }


def run_doctor(
    fix: bool = False,
    store_override: str | None = None,
    restart_gateway: bool = True,
    json_output: bool = False,
    field_access_required: bool | None = None,
    home_dir: Path | None = None,
) -> int:
    report = build_doctor_report(
        fix=fix,
        store_override=store_override,
        restart_gateway=restart_gateway,
        field_access_required=field_access_required,
        home_dir=home_dir,
    )
    if json_output:
        _safe_print(json.dumps(report, indent=2))
    else:
        _safe_print("Maestro doctor summary")
        _safe_print(f"- Profile: {report.get('profile', 'solo')}")
        _safe_print(f"- Fix mode: {'on' if report.get('fix_mode') else 'off'}")
        _safe_print(f"- Store root: {report.get('store_root', '')}")
        _safe_print(f"- Recommended URL: {report.get('recommended_url', '')}")
        if report.get("profile") == PROFILE_SOLO:
            _safe_print(f"- Field access required: {'yes' if report.get('field_access_required') else 'no'}")
        for check in report.get("checks", []):
            if not isinstance(check, dict):
                continue
            marker = "[OK]" if check.get("ok") else "[WARN]" if check.get("warning") else "[FAIL]"
            suffix = " (fixed)" if check.get("fixed") else ""
            _safe_print(f"- {marker} {check.get('name', 'unknown')}: {check.get('detail', '')}{suffix}")

    return 0 if bool(report.get("ok")) else 1
