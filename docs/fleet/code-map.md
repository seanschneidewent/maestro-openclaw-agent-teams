# Fleet Code Map

Use this map to quickly find where Fleet behavior is implemented.

## Entry Points

1. `scripts/install-maestro-fleet.sh`
2. `packages/maestro-fleet/src/maestro_fleet/cli.py`
3. `maestro/cli.py`
4. `maestro/fleet_deploy.py`

## Refactor Guides

1. `docs/fleet/architecture.md`
2. `docs/fleet/refactor-plan.md`

## Deploy Step Ownership

The `run_deploy(...)` function in `maestro/fleet_deploy.py` uses searchable markers:

1. `FLEET_STEP_1_PREREQS`
2. `FLEET_STEP_2_MODELS`
3. `FLEET_STEP_3_COMPANY_PROFILE`
4. `FLEET_STEP_4_PROVIDER_KEYS`
5. `FLEET_STEP_5_COMMANDER_TELEGRAM`
6. `FLEET_STEP_6_INITIAL_PROJECT`
7. `FLEET_STEP_7_DOCTOR_RUNTIME`
8. `FLEET_STEP_8_COMMISSIONING`

## Shared Constants

- `maestro/fleet_constants.py`
  - Fleet profile and port defaults
  - Deploy step titles
  - Provider key/model labels

## OpenClaw Safety + Routing

1. `maestro/openclaw_guard.py`  
   - override protection / fail-closed checks
2. `maestro/openclaw_profile.py`  
   - profile-aware config/workspace pathing
3. `maestro/fleet_deploy.py`  
   - gateway repair and pairing readiness

## Project Provisioning

1. `maestro/purchase.py` (project provisioning path reused by Fleet)
2. `docs/fleet/project-create.md`

## Project Registry + Ingest

1. `maestro/fleet/projects/registry.py`
   - registry file pathing, normalization, project discovery sync, node identity resolution
2. `maestro/fleet/projects/ingest_commands.py`
   - ingest preflight, ingest/index command builders, project control payload assembly
3. `maestro/fleet/projects/lifecycle.py`
   - project creation, store onboarding/move, project-agent registration
4. `maestro/fleet/projects/awareness.py`
   - service status, onboarding status, purchase alias, awareness-state assembly
5. `maestro/control_plane_core.py`
   - compatibility wrappers and remaining control-plane helpers

## Runtime + Health

1. `maestro/doctor.py`
   - thin doctor orchestrator and compatibility wrappers
2. `maestro/fleet/doctor/checks.py`
   - workspace drift checks, launchagent sync, gateway status check, session hygiene
3. `maestro/fleet/doctor/repairs.py`
   - gateway token repair, Telegram repair, device pairing repair, gateway restart
4. `maestro/fleet_deploy.py` (`_run_doctor_for_deploy`, detached server bring-up, commissioning report)
5. `packages/maestro-fleet/src/maestro_fleet/monitor.py`

## Command Center

1. `maestro/server.py`
   - FastAPI routes and compatibility wrappers
2. `maestro/fleet/command_center/state.py`
   - command-center refresh logic, awareness application, node index maintenance
3. `maestro/fleet/command_center/routing.py`
   - node/project detail resolution, conversation routing, send orchestration
4. `maestro/server_command_center_state.py`
   - lower-level node identity and conversation helpers reused by server wrappers
5. `maestro/server_command_center.py`
   - command-center router factory

## Current Hotspots

- `maestro/fleet_deploy.py` — deploy + gateway + server + Windows tasking
- `maestro/server.py` — still owns HTTP surface and workspace routes, but no longer carries most command-center internals
- `maestro/cli.py` — parser + Fleet command dispatch

## Recently Extracted

- `maestro/fleet/shared/subprocesses.py` — shared profiled subprocess execution
- `maestro/fleet/runtime/gateway.py` — gateway readiness, status, device-token repair
- `maestro/fleet/runtime/server.py` — server listener ownership and detached runtime state
- `maestro/fleet/platform/windows.py` — Windows Scheduled Task Fleet server supervision
- `maestro/fleet/doctor/checks.py` — doctor read-side checks
- `maestro/fleet/doctor/repairs.py` — doctor mutation-side repairs
- `maestro/fleet/command_center/state.py` — command-center state assembly and node indexing
- `maestro/fleet/command_center/routing.py` — command-center node/project routing
- `maestro/fleet/projects/registry.py` — project registry ownership and node identity normalization
- `maestro/fleet/projects/ingest_commands.py` — project ingest/index command ownership
- `maestro/fleet/projects/lifecycle.py` — project lifecycle and project-agent registration
- `maestro/fleet/projects/awareness.py` — runtime awareness and onboarding status assembly

## Tests To Run For Fleet Changes

```bash
pytest tests/test_fleet_deploy.py tests/test_doctor.py tests/test_cli.py packages/maestro-fleet/tests/test_fleet_cli_parser.py -q
```

## Operator-Facing Docs

1. `docs/fleet/operator-flow.md`
2. `docs/fleet/deploy-playbook.md`
3. `docs/fleet/supported-topologies.md`
4. `docs/fleet/release-launcher.md`
