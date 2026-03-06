import { optionalEnv, requireEnv } from './env.js';

const QUICKBOOKS_TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer';

function getApiBase(environment) {
  return environment === 'sandbox'
    ? 'https://sandbox-quickbooks.api.intuit.com'
    : 'https://quickbooks.api.intuit.com';
}

function toBasicAuth(clientId, clientSecret) {
  return Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
}

function escapeQueryLiteral(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function normalizeQuickBooksError(payload) {
  const detail =
    payload?.Fault?.Error?.map((entry) => entry?.Detail || entry?.Message).filter(Boolean).join(' | ') ||
    payload?.fault?.error?.[0]?.detail ||
    '';
  return detail || 'Unknown QuickBooks error.';
}

async function quickBooksRequest(path, accessToken, { method = 'GET', body, environment, realmId, contentType } = {}) {
  const baseUrl = getApiBase(environment);
  const url = `${baseUrl}/v3/company/${realmId}${path}`;

  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: 'application/json',
      'Content-Type': contentType || 'application/json',
    },
    body: body ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined,
  });

  const text = await response.text();
  let payload = null;

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail = payload ? normalizeQuickBooksError(payload) : text || 'Unknown QuickBooks API error.';
    throw new Error(`QuickBooks API ${method} ${path} failed (${response.status}): ${detail}`);
  }

  return payload;
}

async function runQuery(accessToken, config, query) {
  const encodedQuery = encodeURIComponent(query);
  return quickBooksRequest(`/query?query=${encodedQuery}`, accessToken, {
    method: 'GET',
    environment: config.environment,
    realmId: config.realmId,
  });
}

async function findCustomerByEmail(accessToken, config, email) {
  const query = `SELECT * FROM Customer WHERE PrimaryEmailAddr = '${escapeQueryLiteral(email)}' MAXRESULTS 1`;
  const payload = await runQuery(accessToken, config, query);
  const customers = payload?.QueryResponse?.Customer || [];
  return customers[0] || null;
}

async function createCustomer(accessToken, config, { email, name }) {
  const payload = await quickBooksRequest('/customer?minorversion=75', accessToken, {
    method: 'POST',
    environment: config.environment,
    realmId: config.realmId,
    body: {
      DisplayName: name || email,
      PrimaryEmailAddr: { Address: email },
    },
  });

  return payload?.Customer || null;
}

async function resolveIncomeAccount(accessToken, config) {
  const query = "SELECT * FROM Account WHERE AccountType = 'Income' AND Active = true MAXRESULTS 1";
  const payload = await runQuery(accessToken, config, query);
  const accounts = payload?.QueryResponse?.Account || [];
  const account = accounts[0];

  if (!account?.Id) {
    throw new Error('No active Income account found in QuickBooks. Create one before invoicing.');
  }

  return account.Id;
}

async function findServiceItemByName(accessToken, config, itemName) {
  const query = `SELECT * FROM Item WHERE Name = '${escapeQueryLiteral(itemName)}' MAXRESULTS 1`;
  const payload = await runQuery(accessToken, config, query);
  const items = payload?.QueryResponse?.Item || [];
  return items[0] || null;
}

async function createServiceItem(accessToken, config, itemName) {
  const incomeAccountId = await resolveIncomeAccount(accessToken, config);
  const payload = await quickBooksRequest('/item?minorversion=75', accessToken, {
    method: 'POST',
    environment: config.environment,
    realmId: config.realmId,
    body: {
      Name: itemName,
      Type: 'Service',
      IncomeAccountRef: { value: incomeAccountId },
    },
  });

  return payload?.Item || null;
}

async function resolveServiceItemId(accessToken, config) {
  if (config.serviceItemId) {
    return config.serviceItemId;
  }

  const itemName = config.serviceItemName || 'Maestro Fleet Services';
  const existingItem = await findServiceItemByName(accessToken, config, itemName);
  if (existingItem?.Id) {
    return existingItem.Id;
  }

  const createdItem = await createServiceItem(accessToken, config, itemName);
  if (!createdItem?.Id) {
    throw new Error('Unable to create a QuickBooks service item for invoicing.');
  }

  return createdItem.Id;
}

function formatDueDate(input) {
  if (input) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(input)) {
      throw new Error('dueDate must use YYYY-MM-DD format.');
    }
    return input;
  }

  const due = new Date();
  due.setDate(due.getDate() + 7);
  return due.toISOString().slice(0, 10);
}

function sanitizeAmount(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error('amount must be a positive number.');
  }
  return Math.round(parsed * 100) / 100;
}

export function getQuickBooksConfig() {
  return {
    environment: optionalEnv('QBO_ENV', 'production').toLowerCase() === 'sandbox' ? 'sandbox' : 'production',
    realmId: requireEnv('QBO_REALM_ID'),
    clientId: requireEnv('QBO_CLIENT_ID'),
    clientSecret: requireEnv('QBO_CLIENT_SECRET'),
    refreshToken: requireEnv('QBO_REFRESH_TOKEN'),
    serviceItemId: optionalEnv('QBO_SERVICE_ITEM_ID'),
    serviceItemName: optionalEnv('QBO_SERVICE_ITEM_NAME', 'Maestro Fleet Services'),
  };
}

export async function getQuickBooksAccessToken() {
  const config = getQuickBooksConfig();

  const response = await fetch(QUICKBOOKS_TOKEN_URL, {
    method: 'POST',
    headers: {
      Authorization: `Basic ${toBasicAuth(config.clientId, config.clientSecret)}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: config.refreshToken,
    }).toString(),
  });

  const payload = await response.json();
  if (!response.ok || !payload?.access_token) {
    const detail = payload?.error_description || payload?.error || 'Unable to refresh QuickBooks access token.';
    throw new Error(`QuickBooks OAuth token refresh failed: ${detail}`);
  }

  return payload.access_token;
}

export async function createQuickBooksInvoice(input) {
  const email = (input.customerEmail || '').trim().toLowerCase();
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw new Error('customerEmail is required and must be valid.');
  }

  const amount = sanitizeAmount(input.amount);
  const dueDate = formatDueDate(input.dueDate);
  const description = (input.description || 'Maestro Fleet service').trim();
  const customerName = (input.customerName || '').trim();
  const sendEmail = Boolean(input.sendEmail);
  const memo = (input.memo || '').trim();
  const reference = (input.reference || '').trim();

  const config = getQuickBooksConfig();
  const accessToken = await getQuickBooksAccessToken();

  const customer = (await findCustomerByEmail(accessToken, config, email)) ||
    (await createCustomer(accessToken, config, { email, name: customerName }));

  if (!customer?.Id) {
    throw new Error('Unable to resolve a QuickBooks customer record.');
  }

  const serviceItemId = await resolveServiceItemId(accessToken, config);

  const invoicePayload = {
    CustomerRef: { value: customer.Id },
    BillEmail: { Address: email },
    DueDate: dueDate,
    Line: [
      {
        Amount: amount,
        Description: description,
        DetailType: 'SalesItemLineDetail',
        SalesItemLineDetail: {
          ItemRef: { value: serviceItemId },
        },
      },
    ],
  };

  if (memo) {
    invoicePayload.PrivateNote = memo;
  }

  if (reference) {
    invoicePayload.CustomerMemo = { value: reference };
  }

  const created = await quickBooksRequest('/invoice?minorversion=75', accessToken, {
    method: 'POST',
    environment: config.environment,
    realmId: config.realmId,
    body: invoicePayload,
  });

  const invoice = created?.Invoice;
  if (!invoice?.Id) {
    throw new Error('QuickBooks returned an invalid invoice response.');
  }

  if (sendEmail) {
    await quickBooksRequest(`/invoice/${invoice.Id}/send?minorversion=75`, accessToken, {
      method: 'POST',
      environment: config.environment,
      realmId: config.realmId,
      body: {},
    });
  }

  return {
    id: invoice.Id,
    docNumber: invoice.DocNumber || '',
    total: invoice.TotalAmt || amount,
    balance: invoice.Balance || amount,
    dueDate: invoice.DueDate || dueDate,
    customerId: customer.Id,
    customerEmail: email,
    emailed: sendEmail,
    environment: config.environment,
  };
}
