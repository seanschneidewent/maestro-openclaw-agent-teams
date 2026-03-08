import { optionalEnv } from './_lib/env.js';

export default {
  async fetch(request) {
    if (request.method !== 'GET') {
      return Response.json({ error: 'Method not allowed.' }, { status: 405, headers: { Allow: 'GET' } });
    }

    return Response.json({
      ok: true,
      checks: {
        calendlyPersonalAccessToken: Boolean(optionalEnv('CALENDLY_PERSONAL_ACCESS_TOKEN')),
        calendlyWebhookSigningKey: Boolean(optionalEnv('CALENDLY_WEBHOOK_SIGNING_KEY')),
        stripeSecretKey: Boolean(optionalEnv('STRIPE_SECRET_KEY')),
        stripeWebhookSecret: Boolean(optionalEnv('STRIPE_WEBHOOK_SECRET')),
        stripeSetupPriceId: Boolean(optionalEnv('STRIPE_SETUP_PRICE_ID')),
        stripeMonthlyPriceId: Boolean(optionalEnv('STRIPE_MONTHLY_PRICE_ID')),
        kitApiKey: Boolean(optionalEnv('KIT_API_KEY')),
        kitConsultationBookedTagId: Boolean(optionalEnv('KIT_TAG_CONSULTATION_BOOKED')),
        kitCustomerTagId: Boolean(optionalEnv('KIT_TAG_CUSTOMER')),
        qboRealmId: Boolean(optionalEnv('QBO_REALM_ID')),
        qboClientId: Boolean(optionalEnv('QBO_CLIENT_ID')),
        qboClientSecret: Boolean(optionalEnv('QBO_CLIENT_SECRET')),
        qboRefreshToken: Boolean(optionalEnv('QBO_REFRESH_TOKEN')),
        invoicingApiToken: Boolean(optionalEnv('INVOICING_API_TOKEN')),
      },
    });
  },
};
