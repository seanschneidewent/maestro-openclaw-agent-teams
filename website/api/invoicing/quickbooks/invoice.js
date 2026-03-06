import { createQuickBooksInvoice } from '../../_lib/quickbooks.js';
import { requireEnv } from '../../_lib/env.js';

function unauthorized() {
  return Response.json({ error: 'Unauthorized.' }, { status: 401 });
}

function isAuthorized(request) {
  const expected = requireEnv('INVOICING_API_TOKEN');
  const provided = request.headers.get('x-invoicing-token') || '';
  return provided && provided === expected;
}

export default {
  async fetch(request) {
    if (request.method !== 'POST') {
      return Response.json({ error: 'Method not allowed.' }, { status: 405, headers: { Allow: 'POST' } });
    }

    try {
      if (!isAuthorized(request)) {
        return unauthorized();
      }
    } catch (error) {
      return Response.json(
        {
          error: 'Invoicing endpoint is not configured.',
          message: error instanceof Error ? error.message : 'Unknown error.',
        },
        { status: 503 },
      );
    }

    let payload = null;
    try {
      payload = await request.json();
    } catch {
      return Response.json({ error: 'Invalid JSON body.' }, { status: 400 });
    }

    try {
      const invoice = await createQuickBooksInvoice({
        customerEmail: payload.customerEmail,
        customerName: payload.customerName,
        amount: payload.amount,
        description: payload.description,
        dueDate: payload.dueDate,
        memo: payload.memo,
        reference: payload.reference,
        sendEmail: payload.sendEmail,
      });

      return Response.json({ ok: true, invoice });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          error: 'Invoice creation failed.',
          message: error instanceof Error ? error.message : 'Unknown error.',
        },
        { status: 400 },
      );
    }
  },
};
