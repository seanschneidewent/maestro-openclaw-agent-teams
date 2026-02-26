"""Shared install-flow normalization and runtime path resolution helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .install_state import DEFAULT_WORKSPACE_DIR, solo_home
from .openclaw_runtime import (
    DEFAULT_MAESTRO_OPENCLAW_PROFILE,
    openclaw_state_root,
    resolve_openclaw_profile,
)


VALID_INSTALL_FLOWS = {"free", "pro", "install"}
VALID_INSTALL_INTENTS = {"free", "pro"}
VALID_INSTALL_CHANNELS = {"core", "pro"}


@dataclass(frozen=True)
class InstallJourneySelection:
    flow: str
    intent: str
    channel: str


@dataclass(frozen=True)
class InstallRuntime:
    solo_home: Path
    openclaw_profile: str
    openclaw_root: Path
    workspace_root: Path
    store_root: Path


def is_truthy(value: str | bool | int | None) -> bool:
    clean = str(value or "").strip().lower()
    return clean in {"1", "true", "yes", "on"}


def install_auto_approve_enabled() -> bool:
    return is_truthy(os.environ.get("MAESTRO_INSTALL_AUTO", ""))


def normalize_install_flow(raw_flow: str) -> str:
    flow = str(raw_flow or "free").strip().lower()
    if flow in VALID_INSTALL_FLOWS:
        return flow
    return "free"


def normalize_install_intent(raw_intent: str) -> str:
    intent = str(raw_intent or "").strip().lower()
    if intent == "core":
        intent = "free"
    if intent in VALID_INSTALL_INTENTS:
        return intent
    return ""


def resolve_install_channel(*, raw_channel: str, flow: str, intent: str) -> str:
    channel = str(raw_channel or "auto").strip().lower()
    if channel == "auto":
        if flow == "pro":
            return "pro"
        if flow == "install" and intent == "pro":
            return "pro"
        return "core"
    if channel in VALID_INSTALL_CHANNELS:
        return channel
    return "core"


def resolve_journey_selection(*, raw_flow: str, raw_intent: str, raw_channel: str) -> InstallJourneySelection:
    flow = normalize_install_flow(raw_flow)
    intent = normalize_install_intent(raw_intent)
    channel = resolve_install_channel(raw_channel=raw_channel, flow=flow, intent=intent)
    return InstallJourneySelection(flow=flow, intent=intent, channel=channel)


def resolve_install_runtime(
    *,
    workspace_dir: str = DEFAULT_WORKSPACE_DIR,
    store_subdir: str = "knowledge_store",
    solo_home_override: str | Path | None = None,
    openclaw_profile_default: str = DEFAULT_MAESTRO_OPENCLAW_PROFILE,
) -> InstallRuntime:
    resolved_solo_home = solo_home(home_dir=Path(solo_home_override).expanduser().resolve()) if solo_home_override else solo_home()
    profile = resolve_openclaw_profile(default=openclaw_profile_default)
    openclaw_root = openclaw_state_root(profile=profile).resolve()
    workspace_root = (openclaw_root / str(workspace_dir).strip()).resolve()
    store_root = (workspace_root / str(store_subdir).strip()).resolve()
    return InstallRuntime(
        solo_home=resolved_solo_home,
        openclaw_profile=profile,
        openclaw_root=openclaw_root,
        workspace_root=workspace_root,
        store_root=store_root,
    )
