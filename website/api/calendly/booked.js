import {
  extractCalendlyBookingPayloadDetails,
  getCalendlyInviteeByUri,
  normalizeCalendlyInviteeResource,
} from '../_lib/calendly.js';
import { syncKitConsultationBookingByEmail } from '../_lib/kit-lifecycle.js';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed.' });
  }

  const { payload, email, firstName, inviteeUri } = req.body || {};

  try {
    const bookingDetails = extractCalendlyBookingPayloadDetails({
      payload,
      email,
      firstName,
      inviteeUri,
    });

    let resolvedEmail = bookingDetails.email;
    let resolvedFirstName = bookingDetails.firstName;
    let resolvedInviteeUri = bookingDetails.inviteeUri;

    if ((!resolvedEmail || !EMAIL_PATTERN.test(resolvedEmail)) && resolvedInviteeUri) {
      const invitee = normalizeCalendlyInviteeResource(await getCalendlyInviteeByUri(resolvedInviteeUri));
      resolvedEmail = invitee.email || resolvedEmail;
      resolvedFirstName = invitee.firstName || resolvedFirstName;
      resolvedInviteeUri = invitee.inviteeUri || resolvedInviteeUri;
    }

    if (!resolvedEmail || !EMAIL_PATTERN.test(resolvedEmail)) {
      return res.status(400).json({ error: 'Unable to determine invitee email from Calendly booking.' });
    }

    const kit = await syncKitConsultationBookingByEmail({
      email: resolvedEmail,
      firstName: resolvedFirstName,
    });

    return res.status(200).json({
      ok: true,
      kit,
      inviteeUri: resolvedInviteeUri,
    });
  } catch (error) {
    console.error('Calendly booked sync error:', error);
    return res.status(500).json({
      error: 'Unable to sync Calendly booking to Kit.',
      message: error instanceof Error ? error.message : 'Unknown error.',
    });
  }
}
