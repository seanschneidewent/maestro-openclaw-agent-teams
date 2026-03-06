# Fleet Refactor Plan

This is the execution plan for making Maestro Fleet easier to navigate, safer to change, and faster to search.

The plan is intentionally incremental. No large rewrite. No behavior-first churn.

## Objective

Refactor the Fleet codebase so that:

1. product intent is obvious from the module layout
2. install/runtime/platform logic are separated
3. commander/project-maestro lifecycle logic is searchable by name
4. platform quirks are isolated from product logic
5. future coding sessions can start from stable, narrow ownership boundaries

## Current High-Risk Files

| File | Lines | Why it should be split first |
| --- | ---: | --- |
| `maestro/fleet_deploy.py` | 1619 | still mixes deploy flow, gateway lifecycle, server supervision, Windows tasking, commissioning |
| `maestro/server.py` | 1586 | still mixes API endpoints with workspace routes and some command-center wrappers |
| `maestro/control_plane_core.py` | 684 | now mostly compatibility wrappers plus remaining control-plane helpers |
| `maestro/cli.py` | 1040 | parser definitions and Fleet command dispatch live together |
| `maestro/doctor.py` | 541 | now mostly orchestration, but still worth reducing further into a report-only adapter |

## Phase Order

### Phase 0: Guardrails

Goal:

- capture the current working behavior before moving code

Work:

1. treat the existing Fleet matrix as the behavior contract
2. keep targeted tests green while extracting modules
3. do not change external CLI behavior during extraction phases

Required test slice:

```bash
pytest tests/test_fleet_deploy.py tests/test_cli.py packages/maestro-fleet/tests/test_fleet_cli_parser.py -q
```

### Phase 1: Extract Runtime Spine

Goal:

- remove gateway/server/platform behavior from `fleet_deploy.py`

Create:

- `maestro/fleet/runtime/gateway.py`
- `maestro/fleet/runtime/server.py`
- `maestro/fleet/runtime/health.py`
- `maestro/fleet/platform/macos.py`
- `maestro/fleet/platform/windows.py`
- `maestro/fleet/shared/subprocesses.py`

Move first from `maestro/fleet_deploy.py`:

#### `runtime/gateway.py`

- `_gateway_service_running`
- `_gateway_cli_ready`
- `_gateway_listener_pids`
- `_evict_gateway_listener_pids`
- `_gateway_status_snapshot`
- `_repair_gateway_device_token_mismatch`
- `_ensure_gateway_running_for_pairing`

#### `runtime/server.py`

- `_read_process_command`
- `_listener_pids`
- `_is_fleet_server_process`
- `_managed_listener_pids`
- `_save_detached_server_state`
- `_port_listening`
- `_resolve_deploy_port`
- `_start_detached_server`
- `_verify_command_center_http`

#### `platform/windows.py`

- `_fleet_server_task_name`
- `_ps_single_quote`
- `_run_windows_powershell`
- `_write_windows_server_task_script`
- `_ensure_windows_server_task`
- `_start_windows_server_task_runner`
- `_start_windows_task_server`

#### `shared/subprocesses.py`

- `_run_cmd`
- `_run_cmd_raw`
- `_parse_json_from_output`

Result:

- `run_deploy()` becomes orchestration only
- gateway/server logic becomes reusable by doctor/runtime code

Status:

- done for shared subprocess helpers
- done for gateway runtime helpers
- done for server supervision helpers
- done for Windows platform helpers

### Phase 2: Extract Doctor Checks and Repairs

Goal:

- make inspection and repair searchable and separately testable

Create:

- `maestro/fleet/doctor/checks.py`
- `maestro/fleet/doctor/repairs.py`
- `maestro/fleet/doctor/report.py`

Move from `maestro/doctor.py`:

#### `doctor/checks.py`

- `_sync_workspace_tools_md`
- `_sync_workspace_agents_md`
- `_sync_workspace_env_role`
- `_sync_launchagent_env`
- `_gateway_running`
- `_repair_cli_device_pairing` should be split into `inspect_cli_device_pairing` + `repair_cli_device_pairing`

#### `doctor/repairs.py`

- `_sync_gateway_auth_tokens`
- `_sync_telegram_bindings`
- `_enforce_commander_telegram_policy`
- `_sync_gateway_launchagent_token`
- `_restart_gateway`

#### `doctor/report.py`

- `DoctorCheck`
- `build_doctor_report`
- `run_doctor`

Result:

- the word `repair` means mutation
- the word `inspect` or `check` means read-only validation

Status:

- done for `checks.py`
- done for `repairs.py`
- `doctor.py` remains the orchestrator/report surface for compatibility
- `report.py` is intentionally deferred because the wrapper module is now small and stable

### Phase 3: Extract Project and Registry Lifecycle

Goal:

- make project maestro lifecycle obvious and stop spreading it across `control_plane_core.py` and `purchase.py`

Create:

- `maestro/fleet/projects/registry.py`
- `maestro/fleet/projects/lifecycle.py`
- `maestro/fleet/projects/ingest_commands.py`
- `maestro/fleet/projects/licensing.py`

Move from `maestro/control_plane_core.py`:

#### `projects/registry.py`

- `fleet_registry_path`
- `_default_registry`
- `load_fleet_registry`
- `save_fleet_registry`
- `sync_fleet_registry`
- `_find_registry_project`
- `resolve_node_identity`

#### `projects/ingest_commands.py`

- `build_ingest_preflight`
- `build_ingest_command`
- `build_index_command`

#### `projects/lifecycle.py`

- `create_project_node`
- `onboard_project_store`
- `move_project_store`
- `register_project_agent`
- `_default_model_from_agents`

Also review `maestro/purchase.py`:

- extract Fleet-specific project provisioning into `projects/lifecycle.py`
- keep purchase/license-specific behavior isolated if still shared with non-Fleet flows

Status:

- done for `maestro/fleet/projects/registry.py`
- done for `maestro/fleet/projects/ingest_commands.py`
- done for `maestro/fleet/projects/lifecycle.py`
- done for `maestro/fleet/projects/awareness.py`
- `control_plane_core.py` is now primarily the compatibility/control-plane wrapper layer

### Phase 4: Extract Command Center State Assembly

Goal:

- isolate how Command Center state is built from how HTTP endpoints are exposed

Create:

- `maestro/fleet/command_center/state.py`
- `maestro/fleet/command_center/routing.py`
- `maestro/fleet/command_center/actions.py`

Move from `maestro/server.py`:

#### `command_center/state.py`

- `_apply_registry_identity`
- `_apply_registry_identity_to_command_center_state`
- `_merge_agent_nodes_into_command_center_state`
- `_apply_runtime_node_state`
- `_refresh_command_center_node_index`
- `_refresh_command_center_state`
- `_refresh_control_plane_state`
- `_refresh_all_state`
- `_ensure_command_center_state`
- `_ensure_awareness_state`
- `_ensure_fleet_registry`

#### `command_center/routing.py`

- `_resolve_agent_slug`
- `_node_exists`
- `_project_slug_for_node`
- `_snapshot_for_node`
- `_node_agent_id_for_slug`
- `_send_node_message`
- `_load_node_conversation`

#### `command_center/actions.py`

- command-center project detail/state loading helpers
- action handlers that currently sit close to endpoint code

Result:

- `server.py` becomes a thin HTTP adapter

Status:

- done for `maestro/fleet/command_center/state.py`
- done for `maestro/fleet/command_center/routing.py`
- `server.py` now keeps the HTTP surface and compatibility wrappers
- `actions.py` is deferred because command-center actions already live cleanly in `server_actions.py`

### Phase 5: Reduce CLI to Thin Adapters

Goal:

- make `maestro/cli.py` readable by command surface rather than by implementation detail

Create:

- `maestro/fleet/cli/deploy.py`
- `maestro/fleet/cli/projects.py`
- `maestro/fleet/cli/licenses.py`

Move from `maestro/cli.py`:

- Fleet parser flag builders
- `_run_fleet`
- Fleet-specific handler branches

Keep `maestro/cli.py` as the top-level parser/dispatcher only.

## Commit Sequence

Use small commits with stable tests after each step.

### Commit 1

`refactor(fleet): add architecture and refactor plan docs`

- add `docs/fleet/architecture.md`
- add `docs/fleet/refactor-plan.md`
- update index/code map

### Commit 2

`refactor(fleet): extract shared subprocess helpers`

- move `_run_cmd`, `_run_cmd_raw`, `_parse_json_from_output`
- no behavior change

### Commit 3

`refactor(fleet): extract gateway runtime helpers`

- move gateway health/repair logic out of `fleet_deploy.py`
- update imports
- keep behavior identical

### Commit 4

`refactor(fleet): extract server supervision and windows task runtime`

- move detached server/process/platform task logic
- preserve current test coverage

### Commit 5

`refactor(fleet): split doctor checks from repairs`

- separate read-only checks from mutations

### Commit 6

`refactor(fleet): isolate project registry and lifecycle modules`

- move registry/project lifecycle/ingest command builders

### Commit 7

`refactor(fleet): isolate command center state assembly`

- reduce `server.py` to endpoint wiring

### Commit 8

`refactor(fleet): thin fleet cli adapters`

- extract Fleet CLI command handlers from `maestro/cli.py`

## Risk-Managed Test Plan

### After Commit 2-4

Run:

```bash
pytest tests/test_fleet_deploy.py tests/test_cli.py packages/maestro-fleet/tests/test_fleet_cli_parser.py -q
```

### After Commit 5

Run:

```bash
pytest tests/test_doctor.py tests/test_fleet_deploy.py tests/test_cli.py -q
```

### After Commit 6

Run:

```bash
pytest tests/test_control_plane.py tests/test_purchase.py tests/test_cli.py -q
```

### After Commit 7

Run:

```bash
pytest tests/test_command_center.py tests/test_control_plane.py tests/test_fleet_deploy.py -q
```

### After Commit 8

Run:

```bash
pytest tests/test_cli.py packages/maestro-fleet/tests/test_fleet_cli_parser.py tests/test_fleet_deploy.py -q
```

### Runtime Smoke After Major Milestones

1. macOS prod one-liner smoke
2. Windows strict launcher smoke
3. commander-only baseline check
4. one project maestro create
5. command-center state check

## Searchability Rules

These rules should be enforced during refactor:

1. No platform-specific `launchctl` or `schtasks` outside `fleet/platform`
2. No gateway restart/install logic outside `fleet/runtime/gateway.py`
3. No command-center state merge logic outside `fleet/command_center/state.py`
4. No project registry mutations outside `fleet/projects/registry.py`
5. No Telegram binding mutation outside `fleet/telegram/*`
6. No user-facing commissioning summary assembly outside `fleet/install/commissioning.py`

## First Working Slice

If we start now, the best first slice is:

1. extract shared subprocess helpers
2. extract gateway runtime helpers
3. extract server/runtime supervision helpers

That gives the highest payoff because it reduces the biggest source file immediately and aligns with the runtime issues we spent the day testing.
