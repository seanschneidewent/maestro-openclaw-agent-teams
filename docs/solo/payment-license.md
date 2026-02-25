# Solo Payment and License Flow

## Goal

Validate that payment provisions Pro entitlement data (license + optional signed entitlement token), then unlocks Pro capabilities.

## Local Services

Run in separate terminals:

```bash
maestro-solo-license-service --port 8082
maestro-solo-billing-service --port 8081
```

Optional environment overrides:

- `MAESTRO_LICENSE_URL` (default `http://127.0.0.1:8082`)
- `MAESTRO_BILLING_URL` (default `http://127.0.0.1:8081`)
- `MAESTRO_INTERNAL_TOKEN` (shared service-to-service token)

Stripe configuration (billing service):

- `MAESTRO_STRIPE_SECRET_KEY` (enables Stripe Checkout path)
- `MAESTRO_STRIPE_WEBHOOK_SECRET` (required for `/v1/stripe/webhook` verification)
- `MAESTRO_STRIPE_PRICE_ID_<PLAN>` (for example `MAESTRO_STRIPE_PRICE_ID_SOLO_TEST_MONTHLY`)
- Optional mode-specific override:
  `MAESTRO_STRIPE_PRICE_ID_<MODE>_<PLAN>`
  (for example `MAESTRO_STRIPE_PRICE_ID_LIVE_SOLO_MONTHLY`)

Template file:

- Repo template: `/Users/seanschneidewent/maestro-openclaw-agent-teams/.env.billing.example`
- Keep real secrets in an untracked local file (for example `.env.billing.local`) or in Railway service variables.

## Purchase Flow

```bash
maestro-solo purchase --email you@example.com --plan solo_test_monthly
```

What happens:

1. Billing purchase is created.
2. Billing creates Stripe Checkout Session when Stripe is configured; otherwise local dev checkout is used.
3. CLI opens checkout URL.
4. Stripe webhooks call billing at `/v1/stripe/webhook`.
5. Billing verifies signature and processes idempotent events:
   - `checkout.session.completed`
   - `invoice.paid`
   - `customer.subscription.deleted`
6. On paid events, billing calls license service.
7. CLI stores license under `~/.maestro-solo/license.json`.
8. If billing returns `entitlement_token`, CLI stores it under `~/.maestro-solo/entitlement.json`.

Purchase states:

- `pending -> paid -> licensed`
- `pending/paid -> failed` (license issue or payment failure)
- `pending/paid/licensed -> canceled` (checkout expired or subscription deleted)

## Validate Runtime Tier

```bash
maestro-solo status
maestro-solo entitlements status
maestro-solo status --remote-verify
```

## Start Runtime

```bash
maestro-solo up --tui
```

Core mode starts without paid license.
Use `maestro-solo up --require-pro` when you want startup to fail unless Pro entitlement is active.

## Production Deploy (Railway)

See:

- [Railway Billing + License Deploy](../operations/railway-billing-license.md)
