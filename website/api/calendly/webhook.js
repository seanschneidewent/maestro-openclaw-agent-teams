import { optionalEnv } from '../_lib/env.js';
import { getCalendlyInviteeDetails, verifyCalendlyWebhookSignature } from '../_lib/calendly.js';
import { syncKitConsultationBookingByEmail } from '../_lib/kit-lifecycle.js';

export default {
  async fetch(request) {
    if (request.method !== 'POST') {
      return Response.json({ error: 'Method not allowed.' }, { status: 405, headers: { Allow: 'POST' } });
    }

    const rawBody = await request.text();
    const signingKey = optionalEnv('CALENDLY_WEBHOOK_SIGNING_KEY');
    const signatureHeader = request.headers.get('calendly-webhook-signature');

    if (!signingKey) {
      return Response.json({ error: 'Missing Calendly webhook signing key.' }, { status: 500 });
    }

    const signatureCheck = verifyCalendlyWebhookSignature({
      headerValue: signatureHeader,
      rawBody,
      signingKey,
    });

    if (!signatureCheck.ok) {
      return Response.json(
        {
          error: 'Invalid Calendly webhook signature.',
          reason: signatureCheck.reason,
        },
        { status: 401 },
      );
    }

    let payload;
    try {
      payload = JSON.parse(rawBody);
    } catch {
      return Response.json({ error: 'Invalid JSON body.' }, { status: 400 });
    }

    const invitee = getCalendlyInviteeDetails(payload);
    if (!invitee) {
      return Response.json({ received: true, ignored: true, event: payload?.event || '' });
    }

    try {
      const result = await syncKitConsultationBookingByEmail({
        email: invitee.email,
        firstName: invitee.firstName,
      });

      return Response.json({
        received: true,
        result: {
          ...result,
          eventType: invitee.eventType,
          inviteeUri: invitee.inviteeUri,
        },
      });
    } catch (error) {
      return Response.json(
        {
          error: 'Calendly webhook processing failed.',
          message: error instanceof Error ? error.message : 'Unknown error.',
        },
        { status: 500 },
      );
    }
  },
};
