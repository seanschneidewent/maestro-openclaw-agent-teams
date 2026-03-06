# Fleet Architecture

This document defines the intended code and runtime shape of Maestro Fleet.

The goal is not "many clever modules." The goal is a codebase where product intent is obvious at a glance:

- one gateway
- one Fleet server / Command Center
- one commander as orchestration layer
- project maestros created only on demand
- optional specialty agents under commander control

## Runtime Model

### Core Services

1. `OpenClaw gateway`
   - local transport and routing
   - Telegram account bindings
   - pairing and device auth

2. `Fleet server`
   - Command Center UI/API
   - awareness and state assembly
   - fleet control endpoints

3. `Commander`
   - top-level orchestrator
   - fleet awareness
   - project maestro provisioning
   - cross-agent dispatch

4. `Project maestros`
   - one per project, only when explicitly provisioned
   - scoped to their own workspace + project store
   - report back through commander

### Communication Rules

1. Human <-> Commander
2. Commander <-> Project Maestro
3. Commander <-> Specialty Agent
4. Project Maestro <-> Its own workspace/tools/state

Project maestros are not intended to operate as a peer mesh.

## Refactor Principle

Code should be organized by product responsibility, not by historical command flow.

Bad shape:

- one file mixes bootstrap, runtime, repair, platform quirks, and reporting

Good shape:

- install/bootstrap code lives together
- runtime supervision lives together
- gateway lifecycle lives together
- project maestro lifecycle lives together
- command-center state assembly lives together
- platform-specific code is isolated

## Current Hotspots

These files currently carry too many mixed responsibilities:

| File | Lines | Problem |
| --- | ---: | --- |
| `maestro/fleet_deploy.py` | 2104 | deploy orchestration, gateway recovery, server supervision, Windows tasking, commissioning, config mutation |
| `maestro/server.py` | 1841 | API handlers mixed with command-center state assembly and node routing |
| `maestro/control_plane_core.py` | 1506 | registry, awareness, Telegram binding health, ingest command generation, project lifecycle |
| `maestro/doctor.py` | 1120 | checks, repairs, config mutation, gateway restart behavior, platform fallback |
| `maestro/cli.py` | 1040 | parser construction mixed with command dispatch and Fleet command ownership |
| `maestro/purchase.py` | 810 | project provisioning logic reused by Fleet but not cleanly named as Fleet lifecycle code |

## Target Module Tree

The target tree should make search and ownership obvious.

```text
maestro/
  fleet/
    install/
      deploy.py
      prereqs.py
      company_profile.py
      commissioning.py
    runtime/
      gateway.py
      server.py
      health.py
      process.py
    platform/
      macos.py
      windows.py
      linux.py
    projects/
      lifecycle.py
      registry.py
      ingest_commands.py
      licensing.py
    telegram/
      bindings.py
      pairing.py
      policy.py
    command_center/
      state.py
      routing.py
      actions.py
    doctor/
      checks.py
      repairs.py
      report.py
    shared/
      config.py
      subprocesses.py
      models.py
```

## Ownership Rules

### `fleet/install`

Owns:

- deploy orchestration
- prereq checks
- company/commander bootstrap
- commissioning summary

Does not own:

- low-level gateway lifecycle
- low-level server lifecycle
- platform-specific service control

### `fleet/runtime`

Owns:

- gateway readiness
- server start/stop/reuse
- detached/supervised runtime behavior
- readiness and health probes

### `fleet/platform`

Owns:

- LaunchAgent behavior on macOS
- Scheduled Task behavior on Windows
- service manager integration on Linux

Nothing outside `fleet/platform` should contain platform-specific `launchctl`, `schtasks`, or `systemctl` flow.

### `fleet/projects`

Owns:

- project maestro creation/update/archive
- registry lifecycle
- project store moves
- ingest/index command generation

### `fleet/telegram`

Owns:

- account bindings
- bot assignment and rebinding
- pairing approval paths
- commander Telegram policy

### `fleet/command_center`

Owns:

- state assembly
- node state merge
- command-center action routing
- conversation relay payload shaping

### `fleet/doctor`

Owns:

- inspection checks
- repair routines
- health report formatting

It should not duplicate runtime lifecycle code. It should call runtime services.

## Naming Rules

Use consistent verb families so search stays cheap:

- `inspect_*`
- `repair_*`
- `restart_*`
- `verify_*`
- `create_*`
- `update_*`
- `load_*`
- `save_*`
- `build_*`

Examples:

- `inspect_gateway_status`
- `repair_gateway_auth`
- `restart_gateway_service`
- `verify_command_center_ready`
- `create_project_node`
- `update_project_telegram_binding`

## Desired End State

A new coding session should let us answer these questions in under a minute:

1. Where does install logic live?
2. Where does runtime supervision live?
3. Where does gateway auth recovery live?
4. Where does command-center state come from?
5. Where does project-maestro lifecycle live?
6. Where does Telegram binding live?
7. Where is Windows-specific behavior isolated?

If those answers are not obvious from file names alone, the refactor is incomplete.
