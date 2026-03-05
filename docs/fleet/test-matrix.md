# Fleet Test Matrix (Capability + Resilience)

Purpose: validate Fleet behavior from install through operations with explicit pass/fail evidence.

## Scope

- Product surface: Fleet deploy/install, runtime, command center, commander, project maestros, specialized agents, ingest pipeline, cross-agent messaging.
- Layer model:
  - Layer A: capability (happy-path behavior)
  - Layer B: resilience (failure, restart, idempotency)

## Environment Baseline

- Production installer command (preferred alias): `curl -fsSL https://get.maestro.run/fleet | bash`
- Production installer command (current billing host): `curl -fsSL https://maestro-billing-service-production.up.railway.app/fleet | bash`
- Product deploy command: `maestro-fleet deploy`

## Layer A: Capability Matrix

| ID | Capability | Pass Criteria | Evidence |
|---|---|---|---|
| A1 | Install baseline (commander-only) | Fresh deploy yields command center + `maestro-company` only; no project maestro auto-created | OpenClaw config `agents.list`, command center state, fleet registry |
| A2 | Runtime health | Gateway running, Fleet server up, command center reachable and consistent with API | `maestro-fleet status`, `maestro-fleet doctor --json`, `/api/command-center/state` |
| A3 | Commander awareness | Commander reports role, active agents, workspaces, and allowed operations correctly | Chat transcripts + state snapshots |
| A4 | On-demand project maestro provisioning | Commander provisions project maestro only when requested | Provision command logs + new agent/workspace records |
| A5 | Workspace isolation | Each project maestro reads/writes only its own workspace/store | Cross-access attempts + negative assertions |
| A6 | Ingest operations | User CLI ingest and commander-guided ingest both work | ingest logs + resulting `pass1/pass2/index` artifacts |
| A7 | Cross-agent communication | Commander ↔ project/specialized agents round-trip reliably | Messaging logs + delivery confirmation |
| A8 | Telegram binding operations | Commander can assign/swap tokens/pairing and route correctly | Account binding diffs + pairing confirmations |
| A9 | Project lifecycle persistence | Restart/reload preserves routing, workspaces, and command center visibility | Restart logs + before/after snapshots |

## Layer B: Resilience Matrix

| ID | Resilience Case | Pass Criteria | Evidence |
|---|---|---|---|
| R1 | Idempotent reinstall/redeploy | Re-run installer/deploy does not create duplicate/phantom project maestros | Re-run logs + pre/post agent counts |
| R2 | Restart recovery | Restart of gateway/server/command center restores healthy status | PID/log evidence + API health checks |
| R3 | Config drift reconciliation | Stale/mismatched registry/config is detected and repairable | Injected drift + doctor/update outputs |
| R4 | Provider key faults | Missing/invalid keys fail clearly and recover cleanly after correction | Error output + successful retry |
| R5 | Ingest interruption/resume | Interrupted ingest resumes without duplication/corruption | Interrupted run logs + resumed artifact comparison |
| R6 | Transient provider/API failures | Partial failures are visible and recoverable with deterministic retry behavior | Failure logs + retry run success |
| R7 | Concurrency/race pressure | Parallel provisioning/messaging avoids cross-routing and corruption | Concurrent command logs + state integrity checks |
| R8 | Observability completeness | Every failure path emits actionable logs with direct fix steps | Log review + fix-command validation |

## Execution Order

1. A1 → A2 → A3 (baseline before advanced behaviors)
2. A4 → A5 → A7 (agent creation and routing integrity)
3. A6 (ingest with smoke slices first, then larger batches)
4. A8 → A9 (operations + persistence)
5. R1 → R8 in increasing disruption order

## Scoring

- `PASS`: criteria met with complete evidence.
- `PARTIAL`: behavior works but with non-blocking variance or incomplete evidence.
- `FAIL`: criteria not met or reproducible defect.
- Severity for failures:
  - `P0`: blocks install/runtime safety
  - `P1`: blocks expected operator workflow
  - `P2`: degraded UX/observability but workaround exists
