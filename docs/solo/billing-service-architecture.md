# Billing Service Architecture

## Goal

Keep purchase and licensing behavior stable while making billing code easier to reason about and change safely.

## Module Layout

- API orchestration and domain logic:
  - `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-solo/src/maestro_solo/billing_service.py`
- Persistence (DB-first with JSON fallback):
  - `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-solo/src/maestro_solo/billing_storage.py`
- Stripe API integrations:
  - `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-solo/src/maestro_solo/billing_stripe.py`
- HTML page renderers (upgrade/success/cancel/dev checkout):
  - `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-solo/src/maestro_solo/billing_views.py`
- Shared DB state adapter:
  - `/Users/seanschneidewent/maestro-openclaw-agent-teams/packages/maestro-solo/src/maestro_solo/state_store.py`

## Why this split

1. Stripe network concerns are isolated from workflow rules.
2. Storage concerns are isolated from request handlers.
3. HTML changes no longer require touching purchase/webhook logic.
4. Tests can monkeypatch billing wrappers without changing public behavior.

## Runtime Flow

1. `POST /v1/solo/purchases` creates purchase state, optionally creates Stripe checkout.
2. Stripe webhook events update state and provision license through license service.
3. `POST /v1/solo/portal-sessions` creates Stripe customer portal sessions for self-serve cancellation/management.
4. Success/cancel pages render from `billing_views`.

## Persistence Rules

- If `MAESTRO_DATABASE_URL` is set:
  - Billing and license services store JSON state in table `maestro_service_state`.
- If unset:
  - Services fall back to local JSON files under `~/.maestro-solo`.
