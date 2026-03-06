import Stripe from 'stripe';

import { requireEnv, optionalEnv } from './env.js';

let cachedStripeClient = null;

export function getStripeClient() {
  if (!cachedStripeClient) {
    cachedStripeClient = new Stripe(requireEnv('STRIPE_SECRET_KEY'));
  }

  return cachedStripeClient;
}

export async function readRawBody(req) {
  if (Buffer.isBuffer(req.body)) {
    return req.body;
  }

  if (typeof req.body === 'string') {
    return Buffer.from(req.body);
  }

  const chunks = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk);
  }

  return Buffer.concat(chunks);
}

export async function getCustomerEmail(stripe, customerId) {
  if (!customerId) {
    return '';
  }

  const customer = await stripe.customers.retrieve(customerId);
  if (customer.deleted) {
    return '';
  }

  return customer.email ?? '';
}

export async function getCheckoutSessionSummary(stripe, sessionId) {
  const session = await stripe.checkout.sessions.retrieve(sessionId);
  const lineItems = await stripe.checkout.sessions.listLineItems(sessionId, { limit: 100 });

  return {
    session,
    lineItems,
    priceIds: lineItems.data
      .map((item) => (typeof item.price === 'string' ? item.price : item.price?.id))
      .filter(Boolean),
  };
}

export function classifyPurchase({
  session,
  priceIds,
  setupPriceId,
  monthlyPriceId,
  setupPaymentLinkId,
  monthlyPaymentLinkId,
}) {
  const paymentLinkId = typeof session.payment_link === 'string'
    ? session.payment_link
    : session.payment_link?.id;

  const isSetup = Boolean(
    (setupPriceId && priceIds.includes(setupPriceId)) ||
      (setupPaymentLinkId && paymentLinkId === setupPaymentLinkId),
  );

  const isMonthly = Boolean(
    (monthlyPriceId && priceIds.includes(monthlyPriceId)) ||
      (monthlyPaymentLinkId && paymentLinkId === monthlyPaymentLinkId) ||
      session.mode === 'subscription',
  );

  if (isSetup && !isMonthly) {
    return 'setup';
  }

  if (isMonthly) {
    return 'monthly';
  }

  return 'unknown';
}

export function getStripeConfig() {
  return {
    setupPriceId: optionalEnv('STRIPE_SETUP_PRICE_ID'),
    monthlyPriceId: optionalEnv('STRIPE_MONTHLY_PRICE_ID'),
    setupPaymentLinkId: optionalEnv('STRIPE_SETUP_PAYMENT_LINK_ID'),
    monthlyPaymentLinkId: optionalEnv('STRIPE_MONTHLY_PAYMENT_LINK_ID'),
  };
}
