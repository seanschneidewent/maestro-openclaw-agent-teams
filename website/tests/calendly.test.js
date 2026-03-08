import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeCalendlyWebhookSignature,
  extractCalendlyBookingPayloadDetails,
  getCalendlyInviteeDetails,
  normalizeCalendlyInviteeResource,
  parseCalendlyWebhookSignature,
  verifyCalendlyWebhookSignature,
} from '../api/_lib/calendly.js';
import calendlyBooked from '../api/calendly/booked.js';
import calendlyWebhook from '../api/calendly/webhook.js';

function restoreEnv(name, value) {
  if (typeof value === 'undefined') {
    delete process.env[name];
    return;
  }

  process.env[name] = value;
}

function createMockRes() {
  return {
    headers: {},
    statusCode: 200,
    jsonBody: null,
    setHeader(name, value) {
      this.headers[name] = value;
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.jsonBody = payload;
      return this;
    },
  };
}

test('parseCalendlyWebhookSignature extracts timestamp and v1 signature', () => {
  const parsed = parseCalendlyWebhookSignature('t=1700000000,v1=abc123');

  assert.equal(parsed.timestamp, 1700000000);
  assert.equal(parsed.signature, 'abc123');
});

test('verifyCalendlyWebhookSignature accepts valid signatures', () => {
  const rawBody = JSON.stringify({ event: 'invitee.created', payload: { email: 'owner@example.com' } });
  const timestamp = 1700000000;
  const signingKey = 'test_signing_key';
  const signature = computeCalendlyWebhookSignature({ signingKey, timestamp, rawBody });

  const result = verifyCalendlyWebhookSignature({
    headerValue: `t=${timestamp},v1=${signature}`,
    rawBody,
    signingKey,
    now: timestamp * 1000,
  });

  assert.equal(result.ok, true);
  assert.equal(result.reason, 'verified');
});

test('verifyCalendlyWebhookSignature rejects stale signatures', () => {
  const rawBody = JSON.stringify({ event: 'invitee.created', payload: { email: 'owner@example.com' } });
  const timestamp = 1700000000;
  const signingKey = 'test_signing_key';
  const signature = computeCalendlyWebhookSignature({ signingKey, timestamp, rawBody });

  const result = verifyCalendlyWebhookSignature({
    headerValue: `t=${timestamp},v1=${signature}`,
    rawBody,
    signingKey,
    now: (timestamp + 601) * 1000,
    toleranceSeconds: 300,
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'stale_signature');
});

test('getCalendlyInviteeDetails normalizes invitee email and first name', () => {
  const details = getCalendlyInviteeDetails({
    event: 'invitee.created',
    payload: {
      email: ' Owner@Example.com ',
      name: 'Owner Person',
      uri: 'https://api.calendly.com/invitees/AAA',
    },
  });

  assert.deepEqual(details, {
    email: 'owner@example.com',
    firstName: 'Owner',
    eventType: 'invitee.created',
    inviteeUri: 'https://api.calendly.com/invitees/AAA',
  });
});

test('extractCalendlyBookingPayloadDetails pulls invitee uri and email from embed payload', () => {
  const details = extractCalendlyBookingPayloadDetails({
    payload: {
      invitee: {
        uri: 'https://api.calendly.com/scheduled_events/AAA/invitees/BBB',
        email: ' Owner@Example.com ',
        name: 'Owner Person',
      },
      event: {
        uri: 'https://api.calendly.com/scheduled_events/AAA',
      },
    },
  });

  assert.deepEqual(details, {
    email: 'owner@example.com',
    firstName: 'Owner',
    inviteeUri: 'https://api.calendly.com/scheduled_events/AAA/invitees/BBB',
  });
});

test('normalizeCalendlyInviteeResource normalizes API invitee payloads', () => {
  assert.deepEqual(
    normalizeCalendlyInviteeResource({
      email: 'Owner@Example.com ',
      name: 'Owner Person',
      uri: 'https://api.calendly.com/scheduled_events/AAA/invitees/BBB',
    }),
    {
      email: 'owner@example.com',
      firstName: 'Owner',
      inviteeUri: 'https://api.calendly.com/scheduled_events/AAA/invitees/BBB',
    },
  );
});

test('Calendly webhook upserts booked invitees into Kit', async (t) => {
  const originalFetch = globalThis.fetch;
  const originalSigningKey = process.env.CALENDLY_WEBHOOK_SIGNING_KEY;
  const originalKitApiKey = process.env.KIT_API_KEY;
  const originalBookedTag = process.env.KIT_TAG_CONSULTATION_BOOKED;
  const originalBookedSequence = process.env.KIT_SEQUENCE_CONSULTATION_BOOKED;

  process.env.CALENDLY_WEBHOOK_SIGNING_KEY = 'test_signing_key';
  process.env.KIT_API_KEY = 'kit_test_key';
  delete process.env.KIT_TAG_CONSULTATION_BOOKED;
  delete process.env.KIT_SEQUENCE_CONSULTATION_BOOKED;

  t.after(() => {
    globalThis.fetch = originalFetch;
    restoreEnv('CALENDLY_WEBHOOK_SIGNING_KEY', originalSigningKey);
    restoreEnv('KIT_API_KEY', originalKitApiKey);
    restoreEnv('KIT_TAG_CONSULTATION_BOOKED', originalBookedTag);
    restoreEnv('KIT_SEQUENCE_CONSULTATION_BOOKED', originalBookedSequence);
  });

  let kitRequestCount = 0;
  globalThis.fetch = async (url, options = {}) => {
    kitRequestCount += 1;
    assert.equal(url, 'https://api.kit.com/v4/subscribers');
    assert.equal(options.method, 'POST');

    return new Response(JSON.stringify({ subscriber: { id: 123 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  const payload = {
    event: 'invitee.created',
    payload: {
      email: 'owner@example.com',
      name: 'Owner Person',
      uri: 'https://api.calendly.com/invitees/AAA',
    },
  };
  const rawBody = JSON.stringify(payload);
  const timestamp = Math.floor(Date.now() / 1000);
  const signature = computeCalendlyWebhookSignature({
    signingKey: process.env.CALENDLY_WEBHOOK_SIGNING_KEY,
    timestamp,
    rawBody,
  });

  const response = await calendlyWebhook.fetch(
    new Request('https://example.com/api/calendly/webhook', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Calendly-Webhook-Signature': `t=${timestamp},v1=${signature}`,
      },
      body: rawBody,
    }),
  );

  assert.equal(response.status, 200);
  assert.equal(kitRequestCount, 1);

  const data = await response.json();
  assert.equal(data.received, true);
  assert.equal(data.result.email, 'owner@example.com');
  assert.equal(data.result.synced, true);
});

test('Calendly booked endpoint fetches invitee details and syncs Kit', async (t) => {
  const originalFetch = globalThis.fetch;
  const originalCalendlyPat = process.env.CALENDLY_PERSONAL_ACCESS_TOKEN;
  const originalKitApiKey = process.env.KIT_API_KEY;
  const originalBookedTag = process.env.KIT_TAG_CONSULTATION_BOOKED;
  const originalBookedSequence = process.env.KIT_SEQUENCE_CONSULTATION_BOOKED;

  process.env.CALENDLY_PERSONAL_ACCESS_TOKEN = 'cal_pat_test';
  process.env.KIT_API_KEY = 'kit_test_key';
  delete process.env.KIT_TAG_CONSULTATION_BOOKED;
  delete process.env.KIT_SEQUENCE_CONSULTATION_BOOKED;

  t.after(() => {
    globalThis.fetch = originalFetch;
    restoreEnv('CALENDLY_PERSONAL_ACCESS_TOKEN', originalCalendlyPat);
    restoreEnv('KIT_API_KEY', originalKitApiKey);
    restoreEnv('KIT_TAG_CONSULTATION_BOOKED', originalBookedTag);
    restoreEnv('KIT_SEQUENCE_CONSULTATION_BOOKED', originalBookedSequence);
  });

  const seenUrls = [];
  globalThis.fetch = async (url, options = {}) => {
    seenUrls.push(String(url));

    if (String(url) === 'https://api.calendly.com/scheduled_events/AAA/invitees/BBB') {
      assert.equal(options.method || 'GET', 'GET');
      assert.equal(options.headers.Authorization, 'Bearer cal_pat_test');

      return new Response(
        JSON.stringify({
          resource: {
            email: 'owner@example.com',
            name: 'Owner Person',
            uri: 'https://api.calendly.com/scheduled_events/AAA/invitees/BBB',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }

    if (String(url) === 'https://api.kit.com/v4/subscribers') {
      assert.equal(options.method, 'POST');
      return new Response(JSON.stringify({ subscriber: { id: 456 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    throw new Error(`Unexpected fetch URL: ${url}`);
  };

  const res = createMockRes();
  await calendlyBooked(
    {
      method: 'POST',
      body: {
        payload: {
          invitee: {
            uri: 'https://api.calendly.com/scheduled_events/AAA/invitees/BBB',
          },
        },
      },
    },
    res,
  );

  assert.equal(res.statusCode, 200);
  assert.equal(res.jsonBody.ok, true);
  assert.equal(res.jsonBody.kit.email, 'owner@example.com');
  assert.deepEqual(seenUrls, [
    'https://api.calendly.com/scheduled_events/AAA/invitees/BBB',
    'https://api.kit.com/v4/subscribers',
  ]);
});
