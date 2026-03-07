#!/usr/bin/env node

import crypto from 'node:crypto';
import process from 'node:process';

function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function usage() {
  console.log(`
QuickBooks OAuth helper

Commands:
  auth-url
    Prints a QuickBooks OAuth URL and generated PKCE values.

  exchange-code
    Exchanges authorization code for access/refresh tokens.

Required env for auth-url:
  QBO_CLIENT_ID
  QBO_REDIRECT_URI

Required env for exchange-code:
  QBO_CLIENT_ID
  QBO_CLIENT_SECRET
  QBO_REDIRECT_URI
  QBO_AUTH_CODE
Optional env for exchange-code:
  QBO_REALM_ID

Optional env:
  QBO_ENV=sandbox|production   (default: production)
  QBO_STATE=<value>            (default: random)
  QBO_CODE_VERIFIER=<value>    (default: random)
`);
}

function base64url(buffer) {
  return Buffer.from(buffer).toString('base64url');
}

function getEnvironment() {
  return (process.env.QBO_ENV || 'production').toLowerCase() === 'sandbox' ? 'sandbox' : 'production';
}

function getAuthorizeHost() {
  return getEnvironment() === 'sandbox'
    ? 'https://appcenter.intuit.com'
    : 'https://appcenter.intuit.com';
}

function makeCodeVerifier() {
  return base64url(crypto.randomBytes(48));
}

function makeCodeChallenge(verifier) {
  return base64url(crypto.createHash('sha256').update(verifier).digest());
}

async function printAuthUrl() {
  const clientId = required('QBO_CLIENT_ID');
  const redirectUri = required('QBO_REDIRECT_URI');

  const state = process.env.QBO_STATE || crypto.randomUUID();
  const codeVerifier = process.env.QBO_CODE_VERIFIER || makeCodeVerifier();
  const codeChallenge = makeCodeChallenge(codeVerifier);
  const scope = 'com.intuit.quickbooks.accounting';
  const authBase = getAuthorizeHost();

  const url = new URL('/connect/oauth2', authBase);
  url.searchParams.set('client_id', clientId);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('scope', scope);
  url.searchParams.set('redirect_uri', redirectUri);
  url.searchParams.set('state', state);
  url.searchParams.set('code_challenge', codeChallenge);
  url.searchParams.set('code_challenge_method', 'S256');

  console.log('Open this URL and approve access:');
  console.log(url.toString());
  console.log('');
  console.log('Store these values for token exchange:');
  console.log(`QBO_STATE=${state}`);
  console.log(`QBO_CODE_VERIFIER=${codeVerifier}`);
  console.log('');
  console.log('After approval, copy `code` and `realmId` from the redirect URL.');
}

async function exchangeCode() {
  const clientId = required('QBO_CLIENT_ID');
  const clientSecret = required('QBO_CLIENT_SECRET');
  const redirectUri = required('QBO_REDIRECT_URI');
  const authCode = required('QBO_AUTH_CODE');
  const codeVerifier = required('QBO_CODE_VERIFIER');

  const response = await fetch('https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer', {
    method: 'POST',
    headers: {
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString('base64')}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      code: authCode,
      redirect_uri: redirectUri,
      code_verifier: codeVerifier,
    }),
  });

  const payload = await response.json();
  if (!response.ok) {
    const message = payload?.error_description || payload?.error || JSON.stringify(payload);
    throw new Error(`Token exchange failed: ${message}`);
  }

  console.log('Token exchange succeeded.');
  console.log('');
  console.log('Set these in Vercel server env:');
  console.log(`QBO_CLIENT_ID=${clientId}`);
  console.log(`QBO_CLIENT_SECRET=${clientSecret}`);
  console.log(`QBO_REFRESH_TOKEN=${payload.refresh_token}`);

  if (process.env.QBO_REALM_ID) {
    console.log(`QBO_REALM_ID=${process.env.QBO_REALM_ID}`);
  } else {
    console.log('QBO_REALM_ID=<from callback realmId query param>');
  }

  console.log(`QBO_ENV=${getEnvironment()}`);
  console.log('');
  console.log('Token metadata:');
  console.log(`refresh_token_expires_in=${payload.x_refresh_token_expires_in || 'unknown'}`);
  console.log(`access_token_expires_in=${payload.expires_in || 'unknown'}`);
}

async function main() {
  const command = process.argv[2];
  if (!command || command === '--help' || command === '-h') {
    usage();
    process.exit(0);
  }

  if (command === 'auth-url') {
    await printAuthUrl();
    return;
  }

  if (command === 'exchange-code') {
    await exchangeCode();
    return;
  }

  usage();
  throw new Error(`Unknown command: ${command}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
