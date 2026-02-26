# Solo Install Validation Matrix

## Goal

Run end-to-end validation for customer install UX and Pro billing unlock across fresh and existing OpenClaw states.

## Scope

Validate all production one-liners:

- Install: `curl -fsSL https://maestro-billing-service-production.up.railway.app/install | bash`
- Free: `curl -fsSL https://maestro-billing-service-production.up.railway.app/free | bash`
- Pro: `curl -fsSL https://maestro-billing-service-production.up.railway.app/pro | bash`

## Expected Installer Journey (All Commands)

Both commands must keep the user in one terminal and show all 4 stages:

1. `===== Step 1/4: Setup =====`
2. `===== Step 2/4: Auth =====`
3. `===== Step 3/4: Purchase =====`
4. `===== Step 4/4: Up =====`

Expected stage behavior:

- Free flow:
  - Auth shows account status panel.
  - Purchase shows preview panel (`--preview`) and upgrade command.
  - Up starts Free runtime.
- Pro flow:
  - Auth ensures sign-in (`auth login`) if not already authenticated.
  - Purchase opens Stripe checkout unless entitlement is already active.
  - Up starts Pro runtime.

## Scenario Matrix

### S1: Fresh machine, no OpenClaw state

- Preconditions:
  - No `~/.openclaw*`
  - No `~/.maestro*`
- Commands:
  - Run `/free`, then `/pro`.
- Expected:
  - Prerequisite install path works.
  - Setup collects OAuth, Gemini, Telegram token, Telegram pairing.
  - `~/.openclaw-maestro-solo/openclaw.json` is created.
  - Shared `~/.openclaw` is not created/modified by Maestro flow.

### S2: Existing shared OpenClaw (`~/.openclaw`) with user data

- Preconditions:
  - User already has OpenClaw agent/history in `~/.openclaw`.
  - `~/.openclaw/openclaw.json` checksum captured before run.
- Commands:
  - Run `/install` and `/pro`.
- Expected:
  - Installer runs under profile `maestro-solo`.
  - New state created in `~/.openclaw-maestro-solo`.
  - Shared `~/.openclaw/openclaw.json` checksum unchanged.

### S3: Existing Maestro isolated profile already configured

- Preconditions:
  - `~/.openclaw-maestro-solo/openclaw.json` exists with valid Gemini + Telegram.
- Commands:
  - Run `/install`.
- Expected:
  - Setup replay path used (`setup --quick --replay`).
  - Required secrets reused (no re-entry).
  - 4-stage journey still shown.

### S4: Existing setup, replay intentionally disabled

- Preconditions:
  - Existing `~/.openclaw-maestro-solo` setup.
- Commands:
  - `MAESTRO_SETUP_REPLAY=0 curl -fsSL .../install | bash`
- Expected:
  - Full quick setup executes (not replay).
  - Pairing step is required unless previously paired and accepted by OpenClaw runtime.

### S5: Shared profile unsafe opt-in (negative safety test)

- Commands:
  - `MAESTRO_OPENCLAW_PROFILE=shared MAESTRO_INSTALL_AUTO=1 bash scripts/install-maestro-macos.sh`
- Expected:
  - Fails closed without `MAESTRO_ALLOW_SHARED_OPENCLAW=1`.

### S6: Production launcher drift check

- Commands:
  - `bash scripts/verify-prod-installers.sh --billing-url https://maestro-billing-service-production.up.railway.app --expect-version <release>`
- Expected:
  - `/install`, `/free`, `/pro` all point at expected release tag/commit and correct install intent.

## Existing-Machine Replay Validation

Run either production command on a machine that already completed setup.

Pass criteria:

1. Setup stage runs replay (`setup --quick --replay`) and shows green checks.
2. Existing user inputs (OAuth/Gemini/Telegram) are not re-entered.
3. If replay fails, installer falls back to `doctor --fix --no-restart`.

## Fresh-Machine Validation

On a clean machine (or fresh user profile), run `/free` first.

Pass criteria:

1. Prerequisites auto-install prompts appear when missing (brew/python/node/openclaw).
2. Setup quick flow collects required values (OpenAI OAuth, Gemini key, Telegram pairing).
3. Auth and Purchase stages are still shown for Free flow.
4. Runtime starts and serves Free route at `http://localhost:3000/`.

Then run `/pro` on the same machine.

Pass criteria:

1. Setup stage replays checks instead of forcing full re-entry.
2. Auth stage either confirms signed-in or starts Google login.
3. Purchase stage opens Stripe checkout.
4. After payment + webhook, local license activates and runtime resolves Pro route `/workspace`.

## Manual Billing Flow Validation (CLI)

Use these commands to validate billing and lifecycle behavior directly:

```bash
maestro-solo auth login --billing-url https://maestro-billing-service-production.up.railway.app
maestro-solo purchase --email you@example.com --plan solo_monthly --mode live --billing-url https://maestro-billing-service-production.up.railway.app
maestro-solo status --remote-verify
maestro-solo entitlements status
maestro-solo unsubscribe --billing-url https://maestro-billing-service-production.up.railway.app
```

## Final Pass Checklist

1. One-liner install works with no repo checkout and no editable installs.
2. Installer always renders all 4 stages in one terminal session.
3. Free flow never opens checkout automatically.
4. Pro flow can complete checkout and receive license via webhook path.
5. `maestro-solo status` shows expected tier and entitlement source.
6. `maestro-solo unsubscribe` opens Stripe Customer Portal.
7. Workspace behavior matches tier gating (`/` for Free, `/workspace` for Pro).
8. Shared `~/.openclaw` checksum is unchanged unless explicit unsafe opt-in was used.
