# Website Production Wiring

This app is a Vite frontend with Vercel serverless functions under `website/api/`.

Production flow:

1. Calendly handles booking.
2. Stripe Payment Links handle checkout.
3. Stripe webhooks hit Vercel.
4. Vercel syncs customers into Kit using tags and optional onboarding sequences.
5. The website renders branded checkout success, cancel, and legal pages.

## Frontend Environment Variables

Set these in Vercel `Production` for the frontend:

```bash
VITE_CALENDLY_URL=https://calendly.com/your-team/fleet-consultation
VITE_CONTACT_EMAIL=hello@example.com
VITE_KIT_FORM_UID=489af9b792
VITE_KIT_FORM_SCRIPT_URL=https://maestro-construction-intelligence.kit.com/489af9b792/index.js
VITE_KIT_FORM_SHARE_URL=https://maestro-construction-intelligence.kit.com/489af9b792
VITE_STRIPE_SETUP_PAYMENT_LINK=https://buy.stripe.com/...
VITE_STRIPE_MONTHLY_PAYMENT_LINK=https://buy.stripe.com/...
VITE_STRIPE_SETUP_PRICE_LABEL="$1,500"
VITE_STRIPE_MONTHLY_PRICE_LABEL="$400 / month"
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

Map the IDs from Kit into the env vars above. The webhook adds tags and optionally enrolls the customer into those sequences.

## Vercel Notes

Client-side pages now exist for:

- `/checkout/success`
- `/checkout/cancel`
- `/privacy`
- `/terms`
- `/refund`

`vercel.json` rewrites those paths back to the SPA entry so direct visits work in production.
