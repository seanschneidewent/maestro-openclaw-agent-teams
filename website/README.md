# Website Production Wiring

This app is a Vite frontend with Vercel serverless functions under `website/api/`.

Production flow:

1. Calendly handles booking.
2. Website CTAs point to consultation scheduling (not immediate payment).
3. Invoice is created after consultation using QuickBooks (or Stripe invoicing if you choose to keep it).
4. Kit handles marketing and lifecycle communication.
5. Optional Stripe webhook automation remains available for hosted checkout flows.
6. The website renders branded legal pages and optional checkout success/cancel routes.

## Frontend Environment Variables

Set these in Vercel `Production` for the frontend:

```bash
VITE_CALENDLY_URL=https://calendly.com/your-team/fleet-consultation
VITE_CONTACT_EMAIL=hello@example.com
VITE_KIT_FORM_UID=489af9b792
VITE_KIT_FORM_SCRIPT_URL=https://maestro-construction-intelligence.kit.com/489af9b792/index.js
VITE_KIT_FORM_SHARE_URL=https://maestro-construction-intelligence.kit.com/489af9b792
VITE_STRIPE_SETUP_PRICE_LABEL="$1,500 one-time setup"
VITE_STRIPE_MONTHLY_PRICE_LABEL="$400 / month optional coverage"
```

These are safe to expose because they are public URLs and labels only.

## Server-Side Environment Variables

Set these in Vercel `Production` for webhook automation:

```bash
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SETUP_PRICE_ID=price_...
STRIPE_MONTHLY_PRICE_ID=price_...
STRIPE_SETUP_PAYMENT_LINK_ID=plink_...
STRIPE_MONTHLY_PAYMENT_LINK_ID=plink_...
KIT_API_KEY=kit_live_...
KIT_TAG_CUSTOMER=...
KIT_TAG_SETUP_PAID=...
KIT_TAG_MONTHLY_ACTIVE=...
KIT_TAG_FORMER_MONTHLY=...                  # optional
KIT_SEQUENCE_SETUP_CUSTOMERS=...            # optional
KIT_SEQUENCE_MONTHLY_CUSTOMERS=...          # optional

# QuickBooks invoicing endpoint (recommended for consultation-first flow)
INVOICING_API_TOKEN=replace_with_long_random_token
QBO_ENV=production
QBO_REALM_ID=123456789012345
QBO_CLIENT_ID=...
QBO_CLIENT_SECRET=...
QBO_REFRESH_TOKEN=...
QBO_SERVICE_ITEM_ID=...                     # optional, auto-created if omitted
QBO_SERVICE_ITEM_NAME=Maestro Fleet Services
```

## API Endpoints

The project now includes:

- `GET /api/health`
  - quick env sanity check
- `GET /api/stripe/session?session_id=cs_...`
  - safe checkout confirmation payload for the branded success page
- `POST /api/stripe/webhook`
  - Stripe webhook endpoint
  - syncs setup and monthly purchases into Kit
  - handles subscription activation and deactivation tags for the managed monthly price
- `POST /api/invoicing/quickbooks/invoice`
  - secured QuickBooks invoice creation endpoint
  - creates or reuses customer by email
  - reuses configured service item or auto-creates one when omitted
  - optional immediate invoice send
  - syncs Kit lifecycle tags and customer onboarding sequences on invoice creation
  - accepts optional `kitLifecycle` of `setup`, `monthly`, `former_monthly`, or `none`
  - when omitted, infers `setup` for `$1500` or setup/deployment descriptions, and `monthly` for `$400` or monthly/coverage descriptions

### QuickBooks Invoice Request Example

```bash
curl -X POST "https://your-production-domain.com/api/invoicing/quickbooks/invoice" \
  -H "Content-Type: application/json" \
  -H "x-invoicing-token: ${INVOICING_API_TOKEN}" \
  -d '{
    "customerEmail": "owner@example.com",
    "customerName": "Example Construction LLC",
    "amount": 1500,
    "description": "Maestro Fleet one-time setup",
    "dueDate": "2026-03-20",
    "memo": "Invoice created after consultation",
    "reference": "Consultation follow-up",
    "kitLifecycle": "setup",
    "sendEmail": true
  }'
```

### QuickBooks Setup Notes (EIN-safe)

You can configure this now without an EIN:

1. Create/finish QuickBooks company profile with your legal name or DBA.
2. Create an Intuit app to get `QBO_CLIENT_ID` and `QBO_CLIENT_SECRET`.
3. Run the OAuth helper to generate the consent URL:

```bash
cd /Users/seanschneidewent/maestro-openclaw-agent-teams/website
QBO_CLIENT_ID=... QBO_REDIRECT_URI=... npm run qbo:auth-url
```

4. After consent, exchange auth code for refresh token:

```bash
QBO_CLIENT_ID=... \
QBO_CLIENT_SECRET=... \
QBO_REDIRECT_URI=... \
QBO_CODE_VERIFIER=... \
QBO_AUTH_CODE=... \
QBO_REALM_ID=... \
QBO_ENV=production \
npm run qbo:exchange-code
```

5. Set resulting `QBO_REFRESH_TOKEN` in Vercel Production.
6. Set the Vercel env vars above.
7. Run one test invoice call with `sendEmail=false` first.

When EIN is ready, update it in QuickBooks company settings. No code changes are needed.

## Stripe CLI Flow

Authenticate once:

```bash
/Users/seanschneidewent/.local/bin/stripe login
```

Generate live payment links against the production domain:

```bash
cd /Users/seanschneidewent/maestro-openclaw-agent-teams/website
SITE_URL=https://your-production-domain.com STRIPE_LIVE_MODE=1 STRIPE_API_KEY=sk_live_... npm run stripe:links
```

If your Stripe CLI supports `--live`, authenticated dashboard login is enough. If it does not, pass an explicit live secret key as shown above.

That prints:

- frontend `VITE_...` values
- backend Stripe IDs for the webhook classifier

## Stripe Webhook Setup

In Stripe, point the live webhook endpoint to:

```bash
https://your-production-domain.com/api/stripe/webhook
```

Subscribe it to:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Use the returned signing secret as `STRIPE_WEBHOOK_SECRET`.

For local testing with the Stripe CLI:

```bash
stripe listen --forward-to localhost:3000/api/stripe/webhook
```

If you use `vercel dev` locally, forward to that local URL instead.

## Kit Setup

Recommended tags:

- `Customer`
- `Setup Paid`
- `Monthly Active`
- `Former Monthly` (optional)

Recommended sequences:

- `Setup Customer Onboarding`
- `Monthly Coverage Onboarding`

Map the IDs from Kit into the env vars above. The Stripe webhook and QuickBooks invoice endpoint add tags and optionally enroll the customer into those sequences.

## Vercel Notes

Client-side pages now exist for:

- `/checkout/success`
- `/checkout/cancel`
- `/privacy`
- `/terms`
- `/refund`

`vercel.json` rewrites those paths back to the SPA entry so direct visits work in production.
