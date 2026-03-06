"""Command-center project/node routing helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable

from ...server_actions import ActionError
from ... import server_command_center_state as command_center_state_ops

EnsureFn = Callable[[], None]
RegistryEntryGetterFn = Callable[[str], dict[str, Any] | None]
NodeExistsFn = Callable[[str], bool]
NodeAgentIdForSlugFn = Callable[[str], str]
ProjectSlugForNodeFn = Callable[[str], str]
SnapshotLookupFn = Callable[[str], dict[str, Any] | None]
ReadConversationFn = Callable[..., dict[str, Any]]
SendAgentMessageFn = Callable[..., dict[str, Any]]
SaveFleetRegistryFn = Callable[[Any, dict[str, Any]], None]
RefreshFn = Callable[[], None]
BroadcastCommandCenterFn = Callable[[], Awaitable[None]]


def load_command_center_project_detail(
    slug: str,
    *,
    store_path: Any,
    fleet_registry: dict[str, Any],
    ensure_fleet_registry_fn: EnsureFn,
    discover_project_dirs_fn: Callable[[Any], list[Any]],
    build_project_snapshot_fn: Callable[[Any], dict[str, Any]],
    build_project_detail_fn: Callable[[Any], dict[str, Any]],
    apply_registry_identity_fn: Callable[[dict[str, Any], dict[str, Any] | None], None],
) -> dict[str, Any]:
    return command_center_state_ops.load_command_center_project_detail(
        slug,
        store_path=store_path,
        fleet_registry=fleet_registry,
        ensure_fleet_registry=ensure_fleet_registry_fn,
        discover_project_dirs_fn=discover_project_dirs_fn,
        build_project_snapshot_fn=build_project_snapshot_fn,
        build_project_detail_fn=build_project_detail_fn,
        apply_registry_identity_fn=apply_registry_identity_fn,
    )


def registry_entry_for_slug(
    slug: str,
    *,
    fleet_registry: dict[str, Any],
    ensure_fleet_registry_fn: EnsureFn,
) -> dict[str, Any] | None:
    return command_center_state_ops.registry_entry_for_slug(
        slug,
        fleet_registry=fleet_registry,
        ensure_fleet_registry=ensure_fleet_registry_fn,
    )


def node_agent_id_for_slug(
    slug: str,
    *,
    command_center_node_index: dict[str, dict[str, Any]],
    registry_entry_for_slug_fn: RegistryEntryGetterFn,
) -> str:
    index_entry = command_center_node_index.get(str(slug).strip())
    if isinstance(index_entry, dict):
        agent_id = str(index_entry.get("agent_id", "")).strip()
        if agent_id:
            return agent_id
    return command_center_state_ops.node_agent_id_for_slug(
        slug,
        entry=registry_entry_for_slug_fn(slug),
    )


def load_command_center_node_status(
    slug: str,
    *,
    commander_node_slug: str,
    awareness_state: dict[str, Any],
    command_center_state: dict[str, Any],
    ensure_awareness_state_fn: EnsureFn,
    load_project_detail_fn: Callable[[str], dict[str, Any]],
    node_agent_id_for_slug_fn: NodeAgentIdForSlugFn,
    snapshot_lookup_fn: SnapshotLookupFn,
) -> dict[str, Any]:
    return command_center_state_ops.load_command_center_node_status(
        slug,
        commander_node_slug=commander_node_slug,
        awareness_state=awareness_state,
        command_center_state=command_center_state,
        ensure_awareness_state=ensure_awareness_state_fn,
        load_project_detail_fn=load_project_detail_fn,
        node_agent_id_for_slug_fn=node_agent_id_for_slug_fn,
        lookup_node_snapshot_fn=snapshot_lookup_fn,
    )


def load_node_conversation(
    slug: str,
    *,
    commander_node_slug: str,
    projects: dict[str, dict[str, Any]],
    command_center_node_index: dict[str, dict[str, Any]],
    node_agent_id_for_slug_fn: NodeAgentIdForSlugFn,
    read_agent_conversation_fn: ReadConversationFn,
    project_slug_for_node_fn: ProjectSlugForNodeFn,
    limit: int = 100,
    before: str | None = None,
) -> dict[str, Any]:
    return command_center_state_ops.load_node_conversation(
        slug,
        commander_node_slug=commander_node_slug,
        projects=projects,
        node_agent_id_for_slug_fn=node_agent_id_for_slug_fn,
        read_agent_conversation_fn=read_agent_conversation_fn,
        known_node_slugs=set(command_center_node_index.keys()),
        project_slug_for_node_fn=project_slug_for_node_fn,
        limit=limit,
        before=before,
    )


def send_node_message(
    slug: str,
    message: str,
    source: str,
    *,
    commander_node_slug: str,
    projects: dict[str, dict[str, Any]],
    store_path: Any,
    fleet_registry: dict[str, Any],
    registry_entry_for_slug_fn: RegistryEntryGetterFn,
    send_agent_message_fn: SendAgentMessageFn,
    save_fleet_registry_fn: SaveFleetRegistryFn,
    max_message_chars: int,
    node_exists_fn: NodeExistsFn,
    node_agent_id_for_slug_fn: NodeAgentIdForSlugFn,
    refresh_command_center_state_fn: RefreshFn,
    refresh_control_plane_state_fn: RefreshFn,
    broadcast_command_center_update_fn: BroadcastCommandCenterFn,
) -> dict[str, Any]:
    payload = command_center_state_ops.send_node_message(
        slug,
        message,
        source,
        commander_node_slug=commander_node_slug,
        projects=projects,
        store_path=store_path,
        fleet_registry=fleet_registry,
        registry_entry_for_slug_fn=registry_entry_for_slug_fn,
        send_agent_message_fn=send_agent_message_fn,
        save_fleet_registry_fn=save_fleet_registry_fn,
        max_message_chars=max_message_chars,
        node_exists_fn=node_exists_fn,
        node_agent_id_for_slug_fn=node_agent_id_for_slug_fn,
    )
    refresh_command_center_state_fn()
    refresh_control_plane_state_fn()
    try:
        asyncio.create_task(broadcast_command_center_update_fn())
    except RuntimeError:
        pass
    return payload


__all__ = [
    "ActionError",
    "load_command_center_project_detail",
    "registry_entry_for_slug",
    "node_agent_id_for_slug",
    "load_command_center_node_status",
    "load_node_conversation",
    "send_node_message",
]
