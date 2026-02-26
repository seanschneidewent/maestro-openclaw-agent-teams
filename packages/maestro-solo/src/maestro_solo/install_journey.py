"""Installer journey orchestration for setup/auth/purchase/up."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.prompt import Confirm, Prompt

from .entitlements import normalize_tier, resolve_effective_entitlement
from .install_flow import (
    install_auto_approve_enabled,
    is_truthy,
    resolve_install_runtime,
    resolve_journey_selection,
)
from .openclaw_runtime import (
    DEFAULT_MAESTRO_OPENCLAW_PROFILE,
    openclaw_config_path,
)
from .solo_license import load_local_license


TOTAL_STEPS = 4


@dataclass
class InstallJourneyOptions:
    flow: str
    intent: str
    channel: str
    solo_home: str
    billing_url: str
    plan_id: str
    purchase_email: str
    force_pro_purchase: bool
    replay_setup: bool
    openclaw_profile: str


def _log(message: str):
    print(f"[maestro-install] {message}")


def _warn(message: str):
    print(f"[maestro-install] WARN: {message}", file=sys.stderr)


def _step(number: int, title: str):
    print(f"\n[maestro-install] ===== Step {number}/{TOTAL_STEPS}: {title} =====")


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _has_existing_setup(solo_home: str) -> bool:
    install_state = Path(solo_home).expanduser().resolve() / "install.json"
    openclaw_config = openclaw_config_path()

    state = _load_json(install_state) if install_state.exists() else {}
    if not bool(state.get("setup_completed")):
        return False

    config = _load_json(openclaw_config) if openclaw_config.exists() else {}
    env = config.get("env") if isinstance(config.get("env"), dict) else {}
    agents = config.get("agents") if isinstance(config.get("agents"), dict) else {}
    agent_list = agents.get("list") if isinstance(agents.get("list"), list) else []

    gemini = env.get("GEMINI_API_KEY")
    has_gemini = isinstance(gemini, str) and bool(gemini.strip())
    has_personal_agent = any(
        isinstance(item, dict) and str(item.get("id", "")).strip() == "maestro-solo-personal"
        for item in agent_list
    )
    return has_gemini and has_personal_agent


def _local_email_fallback() -> str:
    local = load_local_license()
    email = str(local.get("email", "")).strip()
    return email if "@" in email else ""


def _resolve_purchase_email(*, provided: str, required: bool) -> str:
    candidate = str(provided or "").strip()
    if "@" in candidate:
        return candidate

    fallback = _local_email_fallback()
    if "@" in fallback:
        if required:
            entered = Prompt.ask("Enter your billing email", default=fallback).strip()
            if "@" in entered:
                return entered
        return fallback

    if not required:
        return "you@example.com"

    while True:
        entered = Prompt.ask("Enter your billing email").strip()
        if "@" in entered:
            return entered
        _warn("Please enter a valid email address.")


def _run_cli_stream(args: list[str], *, options: InstallJourneyOptions) -> int:
    env = os.environ.copy()
    env["MAESTRO_INSTALL_CHANNEL"] = options.channel
    env["MAESTRO_SOLO_HOME"] = options.solo_home
    if options.openclaw_profile:
        env["MAESTRO_OPENCLAW_PROFILE"] = options.openclaw_profile
    cmd = [sys.executable, "-m", "maestro_solo.cli", *args]
    result = subprocess.run(cmd, env=env, check=False)
    return int(result.returncode)


def _billing_args(options: InstallJourneyOptions) -> list[str]:
    if options.billing_url:
        return ["--billing-url", options.billing_url]
    return []


def _pro_entitlement_active() -> tuple[bool, str, str]:
    state = resolve_effective_entitlement()
    tier = normalize_tier(str(state.get("tier", "core")))
    source = str(state.get("source", "")).strip()
    expires_at = str(state.get("expires_at", "")).strip()
    stale = bool(state.get("stale"))
    return (tier == "pro" and not stale), source, expires_at


def _run_setup_phase(options: InstallJourneyOptions) -> bool:
    if options.replay_setup and _has_existing_setup(options.solo_home):
        _log("Existing Maestro setup detected. Replaying guided setup checks.")
        if _run_cli_stream(["setup", "--quick", "--replay"], options=options) == 0:
            _log("Setup replay passed.")
            return True
        _warn("Setup replay failed. Falling back to preflight checks.")
        if _run_cli_stream(["doctor", "--fix", "--no-restart"], options=options) == 0:
            _log("Preflight checks passed.")
            return True
        _warn("Setup replay and preflight checks both failed.")
        return False

    _log("Starting quick setup...")
    if _run_cli_stream(["setup", "--quick"], options=options) == 0:
        _log("Quick setup passed.")
        return True
    _warn("Quick setup failed.")
    return False


def _resolve_pro_activation_choice(options: InstallJourneyOptions) -> bool:
    if options.flow == "pro":
        return True
    if options.flow == "free":
        return False
    if options.intent == "free":
        _log("Install intent: core-first (Pro can be enabled later).")
        return False

    default_yes = options.intent == "pro"
    if install_auto_approve_enabled():
        if default_yes:
            _log("Auto-approve mode: activating Pro now.")
        else:
            _log("Auto-approve mode: continuing in core mode for now.")
        return bool(default_yes)

    prompt = "Enable Pro now before first launch? (you can skip and upgrade later)"
    try:
        wants_pro = Confirm.ask(prompt, default=default_yes)
    except Exception:
        wants_pro = default_yes
    if wants_pro:
        _log("Install choice: activate Pro now.")
    else:
        _log("Install choice: continue in core mode for now.")
    return bool(wants_pro)


def _run_auth_phase(options: InstallJourneyOptions, *, wants_pro_now: bool) -> bool:
    args = _billing_args(options)

    if not wants_pro_now:
        _log("Core flow: showing billing auth status.")
        _run_cli_stream(["auth", "status", *args], options=options)
        _log("Optional later: maestro-solo auth login")
        return True

    _log("Checking billing auth status...")
    _run_cli_stream(["auth", "status", *args], options=options)
    _log("Ensuring billing auth session is active...")
    rc = _run_cli_stream(["auth", "login", *args], options=options)
    if rc != 0:
        _warn("Authentication failed.")
        return False
    return True


def _run_purchase_phase(options: InstallJourneyOptions, *, wants_pro_now: bool) -> bool:
    args = _billing_args(options)

    _log("Checking entitlement status before purchase...")
    _run_cli_stream(["entitlements", "status"], options=options)

    if not wants_pro_now:
        _log("Core flow: no payment required.")
        preview_email = _resolve_purchase_email(provided=options.purchase_email, required=False)
        _run_cli_stream(
            [
                "purchase",
                "--email",
                preview_email,
                "--plan",
                options.plan_id,
                "--mode",
                "live",
                "--preview",
                "--no-open",
                "--non-interactive",
                *args,
            ],
            options=options,
        )
        _log(f"Upgrade anytime: maestro-solo purchase --email you@example.com --plan {options.plan_id} --mode live")
        return True

    active, source, expires_at = _pro_entitlement_active()
    if active and not options.force_pro_purchase:
        if expires_at:
            _log(f"Active Pro entitlement detected (source={source} expires_at={expires_at}). Skipping purchase.")
        else:
            _log(f"Active Pro entitlement detected (source={source}). Skipping purchase.")
        preview_email = _resolve_purchase_email(provided=options.purchase_email, required=False)
        _run_cli_stream(
            [
                "purchase",
                "--email",
                preview_email,
                "--plan",
                options.plan_id,
                "--mode",
                "live",
                "--preview",
                "--no-open",
                "--non-interactive",
                *args,
            ],
            options=options,
        )
        _log("Purchase stage complete: active Pro entitlement already exists.")
        return True

    email = _resolve_purchase_email(provided=options.purchase_email, required=True)
    _log(f"Starting secure checkout for {email}")
    rc = _run_cli_stream(
        [
            "purchase",
            "--email",
            email,
            "--plan",
            options.plan_id,
            "--mode",
            "live",
            *args,
        ],
        options=options,
    )
    if rc != 0:
        _warn("Pro purchase failed.")
        return False
    return True


def _run_up_phase(options: InstallJourneyOptions, *, wants_pro_now: bool) -> int:
    if wants_pro_now:
        active, _, _ = _pro_entitlement_active()
        if active:
            _log("Pro already active. Starting Maestro Pro runtime...")
        else:
            _log("Starting Maestro runtime while Pro entitlement is pending.")
    else:
        _log("Starting Maestro runtime in core mode...")

    return _run_cli_stream(["up", "--tui"], options=options)


def run_install_journey(options: InstallJourneyOptions) -> int:
    os.environ["MAESTRO_INSTALL_CHANNEL"] = options.channel
    os.environ["MAESTRO_SOLO_HOME"] = options.solo_home
    if options.openclaw_profile:
        os.environ["MAESTRO_OPENCLAW_PROFILE"] = options.openclaw_profile

    _step(1, "Setup")
    if not _run_setup_phase(options):
        return 1

    wants_pro_now = _resolve_pro_activation_choice(options)

    _step(2, "Auth")
    if not _run_auth_phase(options, wants_pro_now=wants_pro_now):
        return 1

    _step(3, "Purchase")
    if not _run_purchase_phase(options, wants_pro_now=wants_pro_now):
        return 1

    _step(4, "Up")
    return _run_up_phase(options, wants_pro_now=wants_pro_now)


def options_from_env_and_args(args) -> InstallJourneyOptions:
    selection = resolve_journey_selection(
        raw_flow=str(getattr(args, "flow", "free") or "free"),
        raw_intent=str(getattr(args, "intent", "") or os.environ.get("MAESTRO_INSTALL_INTENT", "")),
        raw_channel=str(getattr(args, "channel", "auto") or "auto"),
    )
    runtime = resolve_install_runtime(openclaw_profile_default=DEFAULT_MAESTRO_OPENCLAW_PROFILE)
    replay_setup = not is_truthy(str(getattr(args, "no_replay_setup", False)).strip())

    return InstallJourneyOptions(
        flow=selection.flow,
        intent=selection.intent,
        channel=selection.channel,
        solo_home=str(runtime.solo_home),
        billing_url=str(getattr(args, "billing_url", "") or "").strip().rstrip("/"),
        plan_id=str(getattr(args, "plan", "solo_monthly") or "solo_monthly").strip(),
        purchase_email=str(getattr(args, "email", "") or "").strip(),
        force_pro_purchase=bool(getattr(args, "force_pro_purchase", False)),
        replay_setup=replay_setup,
        openclaw_profile=runtime.openclaw_profile,
    )
