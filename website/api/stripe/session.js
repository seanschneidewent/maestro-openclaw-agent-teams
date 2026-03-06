import { classifyPurchase, getCheckoutSessionSummary, getStripeClient, getStripeConfig } from '../_lib/stripe.js';

function formatCurrency(amount, currency) {
  if (typeof amount !== 'number' || !currency) {
    return '';
  }

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(amount / 100);
}

export default {
  async fetch(request) {
    if (request.method !== 'GET') {
      return Response.json({ error: 'Method not allowed.' }, { status: 405, headers: { Allow: 'GET' } });
    }

    const url = new URL(request.url);
    const sessionId = url.searchParams.get('session_id') || '';

    if (!sessionId) {
      return Response.json({ error: 'Missing session_id query parameter.' }, { status: 400 });
    }

    try {
      const stripe = getStripeClient();
      const summary = await getCheckoutSessionSummary(stripe, sessionId);
      const purchaseType = classifyPurchase({
        session: summary.session,
        priceIds: summary.priceIds,
        ...getStripeConfig(),
      });

      return Response.json({
        sessionId,
        purchaseType,
        customerName: summary.session.customer_details?.name ?? '',
        customerEmail: summary.session.customer_details?.email ?? summary.session.customer_email ?? '',
        paymentStatus: summary.session.payment_status,
        mode: summary.session.mode,
        amountTotal: summary.session.amount_total,
        amountTotalFormatted: formatCurrency(summary.session.amount_total, summary.session.currency),
        lineItems: summary.lineItems.data.map((item) => ({
          description: item.description ?? '',
          quantity: item.quantity ?? 1,
        })),
      });
    } catch (error) {
      return Response.json(
        {
          error: 'Unable to load checkout session.',
          message: error instanceof Error ? error.message : 'Unknown error.',
        },
        { status: 500 },
      );
    }
  },
};
