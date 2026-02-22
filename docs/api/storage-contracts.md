# Storage Contracts

## Fleet Registry

Path:
`<store_root>/.command_center/fleet_registry.json`

Tracks project identity, agent mapping, and display metadata.

## System Directives

Path:
`<store_root>/.command_center/system_directives.json`

Stores directive lifecycle records used by Commander alignment.

## Heartbeat Overlay

Path:
`<project_store>/.command_center/heartbeat.json`

Optional node heartbeat contract consumed by Command Center status overlay.
Fresh threshold: 120 seconds.
