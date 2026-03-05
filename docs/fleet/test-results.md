# Fleet Matrix Results

Source matrix: `docs/fleet/test-matrix.md`  
Execution runbook: `docs/fleet/test-runbook.md`

## Results

| ID | Status | Date | Notes |
|---|---|---|---|
| A1 | PASS | 2026-03-05 | Commander-only baseline passed (`commander=1`, `project_maestros=0`, `cc_projects=0`). Server isolation defect fixed and validated with profile-specific PID/log paths and dedicated port `3301`. Current source now also requires explicit `--provision-initial-project`, so deploy defaults to commander-only instead of auto-creating a project maestro. |
| A2 | PASS | 2026-03-05 | Verified on old machine after coherent runtime restart: commander online is consistent with awareness (`openclaw.running=true`, `tokens_aligned=true`, `pairing_required=false`). |
| A3 | PASS | 2026-03-05 | Commander accepted command-center message (`source=command_center_ui`) and returned correct role/capability summary with active project count. Windows relay was revalidated after converting the injected live fleet context to a single-line payload, which fixed a Windows-specific truncation bug. |
| A4 | PASS | 2026-03-05 | Project maestro provisioning succeeded (`matrix-a4-project`) and surfaced in command center + OpenClaw agents. |
| A5 | PASS | 2026-03-05 | Second project maestro provisioning succeeded; workspace/store separation validated (`2 project agents`, `2 unique workspaces`, `2 command-center projects`). |
| A6 | PASS | 2026-03-05 | Ingest validated both ways on old machine: command-center action produced ingest command, commander provided exact ingest command, and CLI ingest completed page loop (`[1/2]` -> `[2/2]` -> `Done!`). |
| A7 | PASS | 2026-03-05 | Commander relay fixed. Command-center messages now inject live fleet context, commander correctly sees active project slugs, and it successfully dispatched status checks to `matrix-a4-project` and `matrix-a5-project-2`, both of which replied. |
| A8 | PARTIAL | 2026-03-05 | Existing-project Telegram rebinding is now implemented via `maestro fleet project set-telegram` and validated with a real project bot token (`@project_level_fleet_bot` for `matrix-a5-project-2`). Gateway reload helper is now hardened with restart -> start -> install+start fallback, but the old machine became saturated before a clean end-to-end rerun. Remaining gap: pairing-code flow not exercised. |
| R1 | PASS | 2026-03-05 | Idempotent redeploy confirmed on old machine: non-interactive deploy did not create duplicate project maestros (same pre/post agent set). |
| R2 | PARTIAL | 2026-03-05 | Restart recovery is improved in code and now cross-checked on Windows. New protections reconcile detached Fleet server state against the real listening PID/store/port, refuse foreign listeners, and prevent stale PID reuse. Windows also needed a gateway-health fix: awareness now treats `openclaw gateway status --json` `rpc.ok=true` plus a live listener as running, which resolved a false offline state when the Scheduled Task runtime reported `stopped` while the gateway was actually serving traffic. Remaining gap: Windows Scheduled Task supervision semantics are still inconsistent and need a dedicated follow-up. |
| R3 | PASS | 2026-03-05 | Duplicate project drift resolved. Runtime now deduplicates same-slug project stores, `doctor` reports unique registry slugs, command center shows `2` projects, and ingest command generation targets the canonical `project_store_path`. |
| R5 | PASS | 2026-03-05 | Interrupt/resume ingest succeeded on old machine. Partial run crossed into page `2/2`, rerun skipped completed page `1/2`, finished cleanly, and left a single canonical store (`matrix-r5-resume`) with exactly `2` page directories. |

## Windows Baseline

- Fresh Windows account (`OK-COMPUTER`, user `fleetlab windows`) was bootstrapped from the current production Fleet wheel set (`fleet-v0.1.31`) on 2026-03-05.
- Current production deploy behavior on a clean machine still provisions the initial project maestro during install (`cfa-love-field`). This confirms the installer/runtime behavior is not yet commander-only by default.
- Current source has now been corrected to commander-only by default: deploy ignores project args unless `--provision-initial-project` is supplied. The published `fleet-v0.1.31` wheel does not include that change yet.
- Two Windows-specific runtime defects were identified:
  - Python subprocess calls to `openclaw` fail on Windows unless the executable is resolved as `openclaw.cmd`.
  - OpenClaw status output must be decoded as UTF-8 with replacement; default Windows code-page decoding can break awareness/status collection.
- A third Windows-specific defect surfaced in command-center relay:
  - the commander live-fleet context was being injected as a multi-line message, but the Windows OpenClaw agent send path only delivered the first line into the session.
  - the relay now emits a single-line payload, and the commander correctly reports the live project count on Windows.
- A fourth Windows-specific defect surfaced in gateway health:
  - `openclaw gateway status --json` could report Scheduled Task runtime `stopped` even while `rpc.ok=true` and a gateway listener was live on `127.0.0.1:18789`.
  - awareness and deploy checks now treat a healthy RPC probe or busy listener as running, which aligns customer-facing runtime status with the actual live gateway.
- After patching the installed Windows runtime with those fixes and restarting the Fleet server:
  - `/api/system/awareness` reported `openclaw_running=true`
  - `/api/command-center/state` reported `commander_online=true` with reason `Gateway reachable and node registered.`
  - the corrected commander reply reported `Active Projects: 1` for `cfa-love-field`
- Remaining Windows degraded reason on this host is only `Tailscale not connected`.

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
