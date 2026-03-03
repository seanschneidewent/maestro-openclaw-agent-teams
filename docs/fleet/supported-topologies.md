# Fleet Supported Topologies

This document defines what Maestro Fleet supports in production.

## Supported

1. Fresh machine dedicated to Fleet (no existing OpenClaw workload for the same OS user).
2. Shared machine with a separate OS user account dedicated to Fleet.
3. Customer server/VM where Fleet is the only OpenClaw workload for that OS user.

## Unsupported

1. Same OS user running both:
   - personal/shared OpenClaw gateway, and
   - Maestro Fleet gateway.
2. Expecting Fleet deploy to coexist with an already-active shared OpenClaw service in the same user session.

## Why

OpenClaw CLI and gateway control paths can cross-target local loopback defaults when two services are active in one user profile. That can cause:
- wrong gateway target selection,
- token mismatch churn,
- Telegram routing confusion,
- unstable pairing outcomes.

Fleet blocks this topology by design during deploy to prevent cross-routing and surprise spend.

## Operator Guidance

If deploy reports an unsupported topology:

1. Move Fleet deployment to a fresh machine, or
2. Create a dedicated OS user for Fleet and deploy there.

Temporary same-user testing is possible only by stopping shared OpenClaw first, but remains unsupported for production.
