# Fleet Matrix Results

Source matrix: `docs/fleet/test-matrix.md`  
Execution runbook: `docs/fleet/test-runbook.md`

## Results

| ID | Status | Date | Notes |
|---|---|---|---|
| A1 | PASS | 2026-03-05 | Commander-only baseline passed (`commander=1`, `project_maestros=0`, `cc_projects=0`). Server isolation defect fixed and validated with profile-specific PID/log paths and dedicated port `3301`. Current source now also requires explicit `--provision-initial-project`, so deploy defaults to commander-only instead of auto-creating a project maestro. Fresh Windows validation also passed in the customer-facing sense: strict mode auto-checked prereqs and failed cleanly on disconnected Tailscale, while the lab override (`MAESTRO_FLEET_REQUIRE_TAILSCALE=0`) completed with commander online and zero project nodes. |
| A2 | PASS | 2026-03-05 | Verified on old machine after coherent runtime restart: commander online is consistent with awareness (`openclaw.running=true`, `tokens_aligned=true`, `pairing_required=false`). Windows baseline also reported `state.commander.online=true`, `awareness.services.openclaw.running=true`, and no unexpected project nodes. |
| A3 | PASS | 2026-03-05 | Commander accepted command-center message (`source=command_center_ui`) and returned correct role/capability summary with active project count. Windows relay was revalidated after converting the injected live fleet context to a single-line payload, which fixed a Windows-specific truncation bug; the commander correctly reported its role, the live `matrix-win-a4` node, and that Windows install did not auto-create a project maestro. |
| A4 | PASS | 2026-03-05 | Project maestro provisioning succeeded (`matrix-a4-project`) and surfaced in command center + OpenClaw agents. Windows was also validated with an on-demand project create (`matrix-win-a4`): project slug, project store, Telegram binding, and local license activation all succeeded, and the command center reflected the new node once the server was kept alive outside the SSH teardown path. |
| A5 | PASS | 2026-03-05 | Second project maestro provisioning succeeded; workspace/store separation validated (`2 project agents`, `2 unique workspaces`, `2 command-center projects`). Windows revalidation also passed with `matrix-win-a4` + `matrix-win-a5`: both were online, both had distinct workspaces and knowledge stores, and command center/orchestrator state reported `Monitoring 2 project node(s)`. |
| A6 | PASS | 2026-03-05 | Ingest validated both ways on old machine: command-center action produced ingest command, commander provided exact ingest command, and CLI ingest completed page loop (`[1/2]` -> `[2/2]` -> `Done!`). |
| A7 | PASS | 2026-03-05 | Commander relay fixed. Command-center messages now inject live fleet context, commander correctly sees active project slugs, and it successfully dispatched status checks to `matrix-a4-project` and `matrix-a5-project-2`, both of which replied. Windows relay also passed: commander routed a live status check to `matrix-win-a4`, recovered from tool-call errors, and returned the project maestro's first-boot/onboarding state. |
| A8 | PARTIAL | 2026-03-05 | Existing-project Telegram rebinding is implemented in source via `maestro fleet project set-telegram` and validated on the old machine with a real project bot token (`@project_level_fleet_bot` for `matrix-a5-project-2`). Windows revalidation also passed for the rebinding/update path: `matrix-win-a5` was provisioned with a distinct Telegram bot token, the installable `maestro-fleet` package CLI was updated to expose `project set-telegram`, a rebuilt wheel reinstall surfaced that command on the Windows host, and `project set-telegram` executed successfully against the existing project while preserving healthy command-center/runtime state. Remaining capability gap: pairing-code flow not exercised. |
| R1 | PASS | 2026-03-05 | Idempotent redeploy confirmed on old machine: non-interactive deploy did not create duplicate project maestros (same pre/post agent set). |
| R2 | PARTIAL | 2026-03-05 | Restart recovery is improved in code and revalidated on Windows. Fleet server startup now uses a dedicated Windows Scheduled Task instead of shell-detached `maestro serve`, while detached-state checks still reconcile against the real listening PID/store/port and refuse foreign listeners. On the Windows host, the task-backed server came up on `:3300`, remained reachable from outside the SSH session (`/api/command-center/state=200`, `/api/system/awareness=200`), and removed the previous SSH teardown failure mode. Remaining gap: gateway supervision still reports inconsistent Scheduled Task runtime state even when RPC/listener health is good, so full Windows restart semantics are not fully closed yet. |
| R3 | PASS | 2026-03-05 | Duplicate project drift resolved. Runtime now deduplicates same-slug project stores, `doctor` reports unique registry slugs, command center shows `2` projects, and ingest command generation targets the canonical `project_store_path`. |
| R5 | PASS | 2026-03-05 | Interrupt/resume ingest succeeded on old machine. Partial run crossed into page `2/2`, rerun skipped completed page `1/2`, finished cleanly, and left a single canonical store (`matrix-r5-resume`) with exactly `2` page directories. |

## Windows Baseline

- Fresh Windows account (`OK-COMPUTER`, user `fleetlab windows`) was bootstrapped from current source/wheels on 2026-03-05.
- Source now includes a Windows installer script and launcher endpoint path:
  - `scripts/install-maestro-fleet-windows.ps1`
  - billing service launcher endpoints for `fleet.ps1`
- Zero-touch prerequisite handling is working on Windows for the tested host:
  - Python detected automatically
  - Node/npm detected automatically
  - OpenClaw detected automatically
  - Tailscale strict-mode gate enforced exactly as intended
- Strict Windows prod-mode behavior is correct:
  - with `MAESTRO_FLEET_REQUIRE_TAILSCALE=1`, installer fails cleanly if Tailscale is installed but not connected
  - this is the intended customer-facing behavior
- Lab override behavior is also correct:
  - with `MAESTRO_FLEET_REQUIRE_TAILSCALE=0`, fresh install completed
  - command center came up
  - commander was online
  - zero project maestros existed until one was explicitly created
- Windows-specific runtime defects fixed in source this round:
  - Python subprocess calls to `openclaw` now resolve correctly on Windows via `openclaw.cmd`
  - OpenClaw status output is decoded as UTF-8 with replacement
  - command-center live fleet context is injected as a single line, fixing Windows truncation in commander relay
  - gateway health now treats `rpc.ok=true` plus a live listener as running, even when Scheduled Task runtime says `stopped`
  - detached server health checks now use Windows process/listener probes instead of Unix-only `ps`/`lsof`
  - Windows installer package specs now support `;` separators so local paths with spaces are valid
  - `maestro-fleet project create` now reports the active command-center URL instead of hardcoding port `3000`
- Windows-specific caveat has been narrowed materially:
  - Fleet server startup no longer relies on SSH-detached `maestro serve`; source now installs and runs a dedicated Scheduled Task for the server runtime on Windows
  - this removed the previous SSH/job-object failure mode for the Fleet web server on the test host
  - the remaining Windows supervision issue is now concentrated in gateway Scheduled Task state reporting, not Fleet server persistence
- Remaining degraded reason on this host is only `Tailscale not connected` when running in lab override mode.

## Evidence

- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/A1-result.md`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/A2-result.md`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/a1-deploy.log`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/a1b-deploy.log`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/a1-doctor.json`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/a2-doctor.json`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/a1-openclaw-config.json`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/a1b-command-center-state-3301.json`
- `/Users/seanschneidewent/Desktop/fleet_matrix/evidence/a2-command-center-state-3301.json`
- `/Users/fleetlab/fleet_matrix/evidence/a2-remote-patched-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/a2-remote-patched-cc-state.json`
- `/Users/fleetlab/fleet_matrix/evidence/a2-remote-patched-awareness.json`
- `/Users/fleetlab/fleet_matrix/evidence/a3-remote-summary2.json`
- `/Users/fleetlab/fleet_matrix/evidence/a4-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/a5-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/a6-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/a7-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/a7-relay-summary2.json`
- `/Users/fleetlab/fleet_matrix/evidence/a7-send-matrix-a4-project.body`
- `/Users/fleetlab/fleet_matrix/evidence/a8-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/a8-set-telegram.log`
- `/Users/fleetlab/fleet_matrix/evidence/a8-set-telegram-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/r1-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/r2-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/r2-recovery-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/r3-live-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/r3-ingest-command-a5.json`
- `/Users/fleetlab/fleet_matrix/evidence/r3-a5-ingest.log`
- `/Users/fleetlab/fleet_matrix/evidence/r3-final-summary.json`
- `/Users/fleetlab/fleet_matrix/evidence/r5-create-project-node.json`
- `/Users/fleetlab/fleet_matrix/evidence/r5-partial-ingest.log`
- `/Users/fleetlab/fleet_matrix/evidence/r5-final-ingest.log`
- `/Users/fleetlab/fleet_matrix/evidence/r5-summary.json`
- `/Users/fleetlab windows/fleet_matrix/evidence/windows-a3-fixed-send.json`
- `/Users/fleetlab windows/fleet_matrix/evidence/windows-r2-awareness.json`
- `/Users/fleetlab windows/fleet_matrix/evidence/windows-r2-state.json`
- `/Users/fleetlab windows/fleet_matrix/evidence/windows-gateway-status.json`
- `C:\Users\fleetlab windows\fleet_matrix\evidence\windows-direct-validation\summary.json`
- `C:\Users\fleetlab windows\fleet_matrix\evidence\windows-direct-validation\command-center-state.json`
- `C:\Users\fleetlab windows\fleet_matrix\evidence\windows-direct-validation\awareness.json`
- `C:\Users\fleetlab windows\fleet_matrix\evidence\windows-direct-validation\installer.log`
