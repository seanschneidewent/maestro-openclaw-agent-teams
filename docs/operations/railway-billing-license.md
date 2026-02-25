# Railway Deployment: Billing + License

## Goal

Deploy Maestro billing and license services on Railway with Stripe Checkout + webhook verification.

## Services

Create two Railway services:

1. `maestro-billing-service`
2. `maestro-license-service`

Both services should run from this repo.

## Start Commands

Billing:

```bash
bash scripts/railway-start-billing.sh
```

License:

```bash
bash scripts/railway-start-license.sh
```

The services now read Railway `PORT` automatically.

## Build Command (Both Services)

Use the same build command for billing and license:

```bash
bash scripts/railway-build-solo-services.sh
```

This installs local packages from this repo:

- `packages/maestro-engine`
- `packages/maestro-solo`

## Required Environment Variables

Set in both services:

- `MAESTRO_INTERNAL_TOKEN` (exact same value in both)

Set in billing service:

- `MAESTRO_LICENSE_URL` (public or private URL for license service)
- `MAESTRO_STRIPE_SECRET_KEY`
- `MAESTRO_STRIPE_WEBHOOK_SECRET`
- `MAESTRO_STRIPE_PRICE_ID_SOLO_MONTHLY`
- `MAESTRO_STRIPE_PRICE_ID_SOLO_YEARLY`

Optional:

- `MAESTRO_STRIPE_PRICE_ID_<MODE>_<PLAN>` overrides
- `MAESTRO_STRIPE_WEBHOOK_TOLERANCE_SECONDS` (default 300)

Set in license service:

- `MAESTRO_ENTITLEMENT_PRIVATE_KEY` (optional, enables signed entitlement tokens)
- `MAESTRO_ENTITLEMENT_PUBLIC_KEY` (optional, mainly for verification clients)

## Stripe Webhook

In Stripe dashboard, point webhook to:

`https://<your-billing-domain>/v1/stripe/webhook`

Enable events:

- `checkout.session.completed`
- `invoice.paid`
- `customer.subscription.deleted`
- `checkout.session.expired`
- `invoice.payment_failed`

Copy Stripe webhook signing secret into:

- `MAESTRO_STRIPE_WEBHOOK_SECRET` (billing service)

## Verification

1. Run:

```bash
maestro-solo purchase --email you@example.com --plan solo_monthly --mode live --billing-url https://<your-billing-domain>
```

2. Confirm purchase becomes `licensed` via polling and local `maestro-solo status`.
3. In Stripe dashboard, confirm webhook delivery `2xx` for the event.

## Fast Setup Checklist

1. Create Railway service `maestro-license-service`:
- Build command: `bash scripts/railway-build-solo-services.sh`
- Start command: `bash scripts/railway-start-license.sh`
- Set env: `MAESTRO_INTERNAL_TOKEN`

2. Create Railway service `maestro-billing-service`:
- Build command: `bash scripts/railway-build-solo-services.sh`
- Start command: `bash scripts/railway-start-billing.sh`
- Set env: `MAESTRO_INTERNAL_TOKEN`, `MAESTRO_LICENSE_URL`, Stripe vars + price IDs

3. In Stripe, create webhook endpoint:
- URL: `https://<billing-domain>/v1/stripe/webhook`
- Events: exactly the list above
- Set resulting `whsec_...` in billing env as `MAESTRO_STRIPE_WEBHOOK_SECRET`
