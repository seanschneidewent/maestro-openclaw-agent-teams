#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${STRIPE_BIN:-}" ]]; then
  :
elif command -v stripe >/dev/null 2>&1; then
  STRIPE_BIN="$(command -v stripe)"
elif [[ -x "$HOME/.local/bin/stripe" ]]; then
  STRIPE_BIN="$HOME/.local/bin/stripe"
else
  echo "Stripe CLI not found. Install it first or set STRIPE_BIN." >&2
  exit 1
fi

STRIPE_AUTH_KEY="${STRIPE_API_KEY:-${STRIPE_SECRET_KEY:-}}"

if [[ -z "${STRIPE_AUTH_KEY:-}" && ! -f "${HOME}/.config/stripe/config.toml" ]]; then
  cat >&2 <<EOF
Stripe CLI is not authenticated.
Run one of the following, then rerun this script:

  ${STRIPE_BIN} login
  STRIPE_API_KEY=sk_test_... npm run stripe:links
EOF
  exit 1
fi

MODE_LABEL="test"
if [[ "${STRIPE_LIVE_MODE:-0}" == "1" ]]; then
  MODE_LABEL="live"
fi

SETUP_NAME="${SETUP_NAME:-Maestro Fleet Deployment}"
SETUP_DESCRIPTION="${SETUP_DESCRIPTION:-One-time deployment and remote setup session.}"
SETUP_PRICE_CENTS="${SETUP_PRICE_CENTS:-150000}"
MONTHLY_NAME="${MONTHLY_NAME:-Maestro Fleet Monthly Coverage}"
MONTHLY_DESCRIPTION="${MONTHLY_DESCRIPTION:-Recurring support, monitoring, and operating coverage.}"
MONTHLY_PRICE_CENTS="${MONTHLY_PRICE_CENTS:-40000}"
SITE_URL="${SITE_URL:-http://localhost:5173}"
SUCCESS_URL="${SUCCESS_URL:-${SITE_URL%/}/checkout/success?session_id={CHECKOUT_SESSION_ID}}"

require_number() {
  local value="$1"
  local name="$2"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "${name} must be an integer number of cents." >&2
    exit 1
  fi
}

require_number "$SETUP_PRICE_CENTS" "SETUP_PRICE_CENTS"
require_number "$MONTHLY_PRICE_CENTS" "MONTHLY_PRICE_CENTS"

usd_label() {
  node -e 'const cents = Number(process.argv[1]); const suffix = process.argv[2]; const dollars = (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }); process.stdout.write(`${dollars}${suffix}`);' "$1" "$2"
}

run_stripe() {
  local args=("$STRIPE_BIN")
  if [[ -n "${STRIPE_AUTH_KEY:-}" ]]; then
    args+=(--api-key "$STRIPE_AUTH_KEY")
  elif [[ "${STRIPE_LIVE_MODE:-0}" == "1" ]]; then
    if "$STRIPE_BIN" --help 2>/dev/null | grep -q -- '--live'; then
      args+=(--live)
    else
      echo "This Stripe CLI build does not support --live." >&2
      echo "Set STRIPE_API_KEY=sk_live_... (or STRIPE_SECRET_KEY=sk_live_...) and rerun." >&2
      exit 1
    fi
  fi
  args+=("$@" -c)
  "${args[@]}"
}

json_field() {
  jq -r "$1"
}

require_json_field() {
  local json="$1"
  local jq_expr="$2"
  local label="$3"
  local value

  value="$(printf '%s' "$json" | jq -r "$jq_expr")"
  if [[ -z "$value" || "$value" == "null" ]]; then
    echo "Stripe response missing ${label}." >&2
    printf '%s\n' "$json" >&2
    exit 1
  fi
  printf '%s\n' "$value"
}

create_setup_link() {
  local product_json
  local price_json
  local link_json
  local product_id
  local price_id
  local link_id
  local link_url

  product_json="$(run_stripe products create --name "$SETUP_NAME" --description "$SETUP_DESCRIPTION")"
  product_id="$(require_json_field "$product_json" '.id' 'product id')"

  price_json="$(run_stripe prices create --product "$product_id" --currency usd --unit-amount "$SETUP_PRICE_CENTS" --nickname "$SETUP_NAME")"
  price_id="$(require_json_field "$price_json" '.id' 'setup price id')"

  link_json="$(run_stripe payment_links create --after-completion.type redirect --after-completion.redirect.url "$SUCCESS_URL" --billing-address-collection auto --customer-creation always -d "line_items[0][price]=$price_id" -d "line_items[0][quantity]=1")"
  link_id="$(require_json_field "$link_json" '.id' 'setup payment link id')"
  link_url="$(require_json_field "$link_json" '.url' 'setup payment link url')"

  printf '%s\n%s\n%s\n' "$price_id" "$link_id" "$link_url"
}

create_monthly_link() {
  local product_json
  local price_json
  local link_json
  local product_id
  local price_id
  local link_id
  local link_url

  product_json="$(run_stripe products create --name "$MONTHLY_NAME" --description "$MONTHLY_DESCRIPTION")"
  product_id="$(require_json_field "$product_json" '.id' 'product id')"

  price_json="$(run_stripe prices create --product "$product_id" --currency usd --unit-amount "$MONTHLY_PRICE_CENTS" --nickname "$MONTHLY_NAME" --recurring.interval month)"
  price_id="$(require_json_field "$price_json" '.id' 'monthly price id')"

  link_json="$(run_stripe payment_links create --after-completion.type redirect --after-completion.redirect.url "$SUCCESS_URL" --billing-address-collection auto -d "line_items[0][price]=$price_id" -d "line_items[0][quantity]=1")"
  link_id="$(require_json_field "$link_json" '.id' 'monthly payment link id')"
  link_url="$(require_json_field "$link_json" '.url' 'monthly payment link url')"

  printf '%s\n%s\n%s\n' "$price_id" "$link_id" "$link_url"
}

setup_result="$(create_setup_link)"
monthly_result="$(create_monthly_link)"

setup_price_id="$(printf '%s\n' "$setup_result" | sed -n '1p')"
setup_link_id="$(printf '%s\n' "$setup_result" | sed -n '2p')"
setup_link_url="$(printf '%s\n' "$setup_result" | sed -n '3p')"
monthly_price_id="$(printf '%s\n' "$monthly_result" | sed -n '1p')"
monthly_link_id="$(printf '%s\n' "$monthly_result" | sed -n '2p')"
monthly_link_url="$(printf '%s\n' "$monthly_result" | sed -n '3p')"

setup_price_label="$(usd_label "$SETUP_PRICE_CENTS" ' one-time deployment')"
monthly_price_label="$(usd_label "$MONTHLY_PRICE_CENTS" '/month coverage')"

cat <<EOF
Stripe ${MODE_LABEL} payment links created.

Setup price ID: ${setup_price_id}
Setup payment link ID: ${setup_link_id}
Setup payment link: ${setup_link_url}
Monthly price ID: ${monthly_price_id}
Monthly payment link ID: ${monthly_link_id}
Monthly payment link: ${monthly_link_url}
Success redirect: ${SUCCESS_URL}

Paste the following into:
  ${ROOT_DIR}/.env.local

VITE_STRIPE_SETUP_PAYMENT_LINK=${setup_link_url}
VITE_STRIPE_MONTHLY_PAYMENT_LINK=${monthly_link_url}
VITE_STRIPE_SETUP_PRICE_LABEL="${setup_price_label}"
VITE_STRIPE_MONTHLY_PRICE_LABEL="${monthly_price_label}"

Paste the following into your server-side production environment too:

STRIPE_SETUP_PRICE_ID=${setup_price_id}
STRIPE_MONTHLY_PRICE_ID=${monthly_price_id}
STRIPE_SETUP_PAYMENT_LINK_ID=${setup_link_id}
STRIPE_MONTHLY_PAYMENT_LINK_ID=${monthly_link_id}

If you also want the website CTA live, make sure this exists too:
VITE_CALENDLY_URL=https://calendly.com/your-team/fleet-consultation
EOF
