import crypto from 'node:crypto';

import { requireEnv } from './env.js';

const DEFAULT_SIGNATURE_TOLERANCE_SECONDS = 300;
const CALENDLY_API_BASE = 'https://api.calendly.com';

function safeHexCompare(expected, actual) {
  if (!expected || !actual || expected.length !== actual.length) {
    return false;
  }

  return crypto.timingSafeEqual(Buffer.from(expected, 'hex'), Buffer.from(actual, 'hex'));
}

function normalizeEmail(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function firstNonEmptyString(...values) {
  return (
    values.find((value) => typeof value === 'string' && value.trim())?.trim() || ''
  );
}

function firstNameFrom(value) {
  const fullName = firstNonEmptyString(value);
  return fullName ? fullName.split(/\s+/)[0] : '';
}

async function calendlyRequest(pathOrUrl, { method = 'GET', body } = {}) {
  const target = String(pathOrUrl || '').startsWith('http') ? String(pathOrUrl) : `${CALENDLY_API_BASE}${pathOrUrl}`;
  const response = await fetch(target, {
    method,
    headers: {
      Authorization: `Bearer ${requireEnv('CALENDLY_PERSONAL_ACCESS_TOKEN')}`,
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Calendly API ${method} ${target} failed: ${response.status} ${text}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export function parseCalendlyWebhookSignature(headerValue) {
  const parts = String(headerValue || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);

  const parsed = Object.fromEntries(
    parts.map((part) => {
      const separatorIndex = part.indexOf('=');
      if (separatorIndex === -1) {
        return [part, ''];
      }

      return [part.slice(0, separatorIndex), part.slice(separatorIndex + 1)];
    }),
  );

  const timestamp = Number(parsed.t);
  return {
    timestamp: Number.isFinite(timestamp) ? timestamp : null,
    signature: parsed.v1 || '',
  };
}

export function computeCalendlyWebhookSignature({ signingKey, timestamp, rawBody }) {
  return crypto.createHmac('sha256', signingKey).update(`${timestamp}.${rawBody}`).digest('hex');
}

export function verifyCalendlyWebhookSignature({
  headerValue,
  rawBody,
  signingKey,
  toleranceSeconds = DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
  now = Date.now(),
}) {
  if (!signingKey) {
    return { ok: false, reason: 'missing_signing_key' };
  }

  const { timestamp, signature } = parseCalendlyWebhookSignature(headerValue);

  if (!timestamp || !signature) {
    return { ok: false, reason: 'missing_signature' };
  }

  const ageMs = Math.abs(now - timestamp * 1000);
  if (ageMs > toleranceSeconds * 1000) {
    return { ok: false, reason: 'stale_signature' };
  }

  const expectedSignature = computeCalendlyWebhookSignature({ signingKey, timestamp, rawBody });
  const isValid = safeHexCompare(expectedSignature, signature);
  return {
    ok: isValid,
    reason: isValid ? 'verified' : 'signature_mismatch',
  };
}

export function getCalendlyInviteeDetails(payload) {
  if (payload?.event !== 'invitee.created') {
    return null;
  }

  const invitee = payload?.payload;
  const email = normalizeEmail(invitee?.email);
  if (!email) {
    return null;
  }

  const name = firstNonEmptyString(invitee?.name);
  const firstName = firstNameFrom(name);

  return {
    email,
    firstName,
    eventType: payload.event,
    inviteeUri: typeof invitee?.uri === 'string' ? invitee.uri : '',
  };
}

export function extractCalendlyBookingPayloadDetails({ payload, email, firstName, inviteeUri } = {}) {
  const normalizedPayload = payload && typeof payload === 'object' ? payload : {};
  const candidateEmail = normalizeEmail(
    firstNonEmptyString(
      email,
      normalizedPayload.email,
      normalizedPayload.invitee_email,
      normalizedPayload.invitee?.email,
      normalizedPayload.inviteeEmail,
    ),
  );
  const candidateName = firstNonEmptyString(
    normalizedPayload.name,
    normalizedPayload.invitee_name,
    normalizedPayload.invitee?.name,
    normalizedPayload.full_name,
  );
  const resolvedInviteeUri = firstNonEmptyString(
    inviteeUri,
    normalizedPayload.invitee_uri,
    normalizedPayload.inviteeUri,
    normalizedPayload.invitee?.uri,
    normalizedPayload.resource?.uri,
  );

  return {
    email: candidateEmail,
    firstName: firstNonEmptyString(firstName, firstNameFrom(candidateName)),
    inviteeUri: resolvedInviteeUri,
  };
}

export async function getCalendlyInviteeByUri(inviteeUri) {
  const normalizedUri = firstNonEmptyString(inviteeUri);
  if (!normalizedUri) {
    return null;
  }

  const payload = await calendlyRequest(normalizedUri);
  return payload?.resource || payload?.collection?.[0] || payload || null;
}

export function normalizeCalendlyInviteeResource(invitee) {
  if (!invitee || typeof invitee !== 'object') {
    return { email: '', firstName: '', inviteeUri: '' };
  }

  const email = normalizeEmail(firstNonEmptyString(invitee.email, invitee.email_address));
  const name = firstNonEmptyString(invitee.name, invitee.full_name);

  return {
    email,
    firstName: firstNameFrom(name),
    inviteeUri: firstNonEmptyString(invitee.uri, invitee.resource_uri),
  };
}
