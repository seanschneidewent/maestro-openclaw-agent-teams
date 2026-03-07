import { optionalEnv, requireEnv } from './env.js';

const KIT_API_BASE = 'https://api.kit.com/v4';

async function kitRequest(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${KIT_API_BASE}${path}`, {
    method,
    headers: {
      'X-Kit-Api-Key': requireEnv('KIT_API_KEY'),
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Kit API ${method} ${path} failed: ${response.status} ${text}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export function getKitConfig() {
  return {
    customerTagId: optionalEnv('KIT_TAG_CUSTOMER'),
    setupPaidTagId: optionalEnv('KIT_TAG_SETUP_PAID'),
    monthlyActiveTagId: optionalEnv('KIT_TAG_MONTHLY_ACTIVE'),
    formerMonthlyTagId: optionalEnv('KIT_TAG_FORMER_MONTHLY'),
    setupOnboardingSequenceId: optionalEnv('KIT_SEQUENCE_SETUP_CUSTOMERS'),
    monthlyOnboardingSequenceId: optionalEnv('KIT_SEQUENCE_MONTHLY_CUSTOMERS'),
  };
}

async function findSubscriberByEmail(email) {
  if (!email) {
    return null;
  }

  const payload = await kitRequest(`/subscribers?email_address=${encodeURIComponent(email)}`);
  return payload?.subscribers?.[0] || null;
}

export async function upsertSubscriber({ email, firstName }) {
  if (!email) {
    return null;
  }

  return kitRequest('/subscribers', {
    method: 'POST',
    body: {
      email_address: email,
      first_name: firstName || undefined,
    },
  });
}

export async function addTagByEmail(tagId, email) {
  if (!tagId || !email) {
    return null;
  }

  return kitRequest(`/tags/${tagId}/subscribers`, {
    method: 'POST',
    body: {
      email_address: email,
    },
  });
}

export async function removeTagByEmail(tagId, email) {
  if (!tagId || !email) {
    return null;
  }

  const subscriber = await findSubscriberByEmail(email);
  if (!subscriber?.id) {
    return null;
  }

  return kitRequest(`/tags/${tagId}/subscribers/${subscriber.id}`, {
    method: 'DELETE',
  });
}

export async function addSubscriberToSequence(sequenceId, email) {
  if (!sequenceId || !email) {
    return null;
  }

  return kitRequest(`/sequences/${sequenceId}/subscribers`, {
    method: 'POST',
    body: {
      email_address: email,
    },
  });
}
