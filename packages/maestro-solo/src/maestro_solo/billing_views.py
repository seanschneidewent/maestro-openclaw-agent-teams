"""HTML view renderers for Maestro Solo billing pages."""

from __future__ import annotations

import html
import json


def render_upgrade_page(*, authenticated_email: str = "") -> str:
    safe_email = html.escape(authenticated_email)
    email_json = json.dumps(authenticated_email)
    signed_in_display = "block" if authenticated_email else "none"
    return """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Upgrade to Maestro Solo Pro</title>
    <style>
      :root {
        --ink: #13212f;
        --muted: #4a5b6a;
        --accent: #0d9f6e;
        --accent-strong: #0b825b;
        --card: rgba(255, 255, 255, 0.88);
        --bg-a: #f6efe5;
        --bg-b: #dce9f5;
        --line: #d3deea;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        min-height: 100vh;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(1200px 720px at -10% -10%, #ffe4c5 0%, transparent 60%),
          radial-gradient(800px 480px at 110% 110%, #d5ecff 0%, transparent 60%),
          linear-gradient(150deg, var(--bg-a), var(--bg-b));
        display: grid;
        place-items: center;
        padding: 20px;
      }
      .panel {
        width: min(560px, 100%);
        border: 1px solid var(--line);
        border-radius: 18px;
        background: var(--card);
        box-shadow: 0 18px 48px rgba(28, 44, 60, 0.12);
        backdrop-filter: blur(4px);
        padding: 26px;
      }
      .eyebrow {
        display: inline-block;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #0c6d92;
        font-weight: 700;
        margin-bottom: 8px;
      }
      h1 {
        margin: 0 0 8px;
        font-size: clamp(28px, 4vw, 36px);
        line-height: 1.08;
        letter-spacing: -0.02em;
      }
      p {
        margin: 0 0 16px;
        color: var(--muted);
        line-height: 1.5;
      }
      form {
        margin-top: 14px;
        display: grid;
        gap: 12px;
      }
      label {
        display: grid;
        gap: 6px;
        font-size: 13px;
        color: #2d4254;
      }
      input, select {
        border: 1px solid #b8c6d4;
        border-radius: 12px;
        padding: 12px 13px;
        font-size: 15px;
        background: #fff;
        color: #142536;
      }
      button {
        margin-top: 4px;
        border: 0;
        border-radius: 12px;
        padding: 13px 16px;
        font-size: 15px;
        font-weight: 700;
        color: #fff;
        background: linear-gradient(135deg, var(--accent), #1ca47b);
        cursor: pointer;
      }
      button:hover { background: linear-gradient(135deg, var(--accent-strong), #198f6b); }
      button[disabled] { opacity: 0.7; cursor: default; }
      .note {
        margin-top: 12px;
        font-size: 12px;
        color: #486071;
      }
      .error {
        display: none;
        margin-top: 10px;
        padding: 11px 12px;
        border-radius: 10px;
        border: 1px solid #f4b2b2;
        background: #fff4f4;
        color: #952626;
        font-size: 13px;
      }
      .error.show { display: block; }
    </style>
  </head>
  <body>
    <main class="panel">
      <div class="eyebrow">Maestro Solo Pro</div>
      <h1>Upgrade to Pro</h1>
      <p>Enter your email, continue to secure Stripe checkout, and Pro capabilities are provisioned automatically after payment.</p>
      <p class="note" id="signed-in-note" style="display:""" + signed_in_display + """;">Signed in as <strong id="signed-in-email">""" + safe_email + """</strong>.</p>
      <form id="upgrade-form">
        <label>
          Email
          <input id="email" type="email" required placeholder="you@example.com" />
        </label>
        <label>
          Plan
          <select id="plan">
            <option value="solo_monthly" selected>Solo Pro Monthly</option>
          </select>
        </label>
        <button id="submit" type="submit">Continue to Secure Checkout</button>
      </form>
      <div id="error" class="error"></div>
      <div class="note">Payment is processed by Stripe. Your card details are never entered on this page.</div>
    </main>
    <script>
      const form = document.getElementById("upgrade-form");
      const email = document.getElementById("email");
      const plan = document.getElementById("plan");
      const submit = document.getElementById("submit");
      const error = document.getElementById("error");
      const signedIn = document.getElementById("signed-in-email");
      const signedInNote = document.getElementById("signed-in-note");
      const authEmail = """ + email_json + """;

      if (authEmail && !email.value.trim()) {
        email.value = authEmail;
      }
      if (authEmail) {
        signedIn.textContent = authEmail;
        signedInNote.style.display = "block";
      } else {
        signedInNote.style.display = "none";
      }

      function showError(message) {
        error.textContent = message || "Unable to start checkout.";
        error.classList.add("show");
      }

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        error.classList.remove("show");
        submit.disabled = true;
        submit.textContent = "Starting checkout...";

        try {
          const res = await fetch("/v1/solo/purchases", {
            method: "POST",
            headers: { "content-type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
              email: email.value.trim(),
              plan_id: plan.value,
              mode: "live"
            })
          });
          const data = await res.json();
          if (!res.ok) {
            if (res.status === 401) {
              throw new Error("auth_required: sign in with Google first.");
            }
            throw new Error((data && data.detail) || "purchase_create_failed");
          }
          if (!data.checkout_url) {
            throw new Error("missing_checkout_url");
          }
          window.location.href = data.checkout_url;
        } catch (err) {
          showError(String(err.message || err));
          submit.disabled = false;
          submit.textContent = "Continue to Secure Checkout";
        }
      });
    </script>
  </body>
</html>"""


def render_checkout_login_page(*, login_url: str) -> str:
    safe_url = html.escape(login_url, quote=True)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Sign in to Maestro</title>
    <style>
      body {{ font-family: "Avenir Next", "Segoe UI", sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: linear-gradient(145deg,#f7efe4,#dce9f7); color: #152535; padding: 18px; }}
      .card {{ width: min(520px, 100%); background: #fff; border: 1px solid #d6e1ec; border-radius: 16px; box-shadow: 0 18px 48px rgba(22,37,53,0.12); padding: 24px; }}
      h1 {{ margin: 0 0 10px; }}
      p {{ color: #4b6174; line-height: 1.45; }}
      a.button {{ display: inline-block; margin-top: 10px; text-decoration: none; color: #fff; background: #1a7fdd; padding: 11px 15px; border-radius: 10px; font-weight: 700; }}
      a.button:hover {{ background: #166ec0; }}
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Sign in with Google</h1>
      <p>Use your Google account to continue to Maestro Solo Pro checkout.</p>
      <a class="button" href="{safe_url}">Continue with Google</a>
    </main>
  </body>
</html>"""


def render_checkout_cli_auth_complete_page(*, email: str) -> str:
    safe_email = html.escape(email)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Authentication Complete</title>
    <style>
      body {{ font-family: "Avenir Next", "Segoe UI", sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f7fb; color: #152536; padding: 18px; }}
      .card {{ width: min(560px, 100%); background: #fff; border: 1px solid #d5dfeb; border-radius: 14px; padding: 22px; }}
      .pill {{ display: inline-block; background: #e8f7ee; color: #1f6a3f; font-size: 12px; font-weight: 700; border-radius: 999px; padding: 5px 10px; }}
      p {{ color: #4c6073; }}
    </style>
  </head>
  <body>
    <main class="card">
      <div class="pill">Success. You can close this tab.</div>
      <h2>Signed in to Maestro</h2>
      <p>Authenticated as <strong>{safe_email or "your Google account"}</strong>.</p>
      <p>Return to your terminal to continue.</p>
    </main>
  </body>
</html>"""


def render_checkout_success_page(purchase_id: str) -> str:
    purchase_safe = html.escape(purchase_id)
    purchase_json = json.dumps(purchase_id)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Payment Received</title>
    <style>
      body {{ font-family: "Avenir Next", "Segoe UI", sans-serif; margin: 0; padding: 22px; background: #f4f7fb; color: #172532; }}
      .box {{ max-width: 680px; margin: 0 auto; background: #fff; border: 1px solid #d8e2ec; border-radius: 12px; padding: 18px; }}
      .pill {{ display: inline-block; margin-bottom: 8px; padding: 6px 10px; border-radius: 999px; background: #e7f7ee; color: #1d6a3f; font-size: 12px; font-weight: 700; }}
      h2 {{ margin-top: 0; }}
      code {{ background: #f1f5f8; border-radius: 6px; padding: 2px 6px; }}
      .muted {{ color: #4c6073; }}
      .state {{ margin-top: 12px; padding: 10px 12px; border-radius: 8px; background: #edf3fb; border: 1px solid #d3e0ef; }}
      .state.ok {{ background: #e9f7ee; border-color: #c4e9d0; color: #175e37; }}
    </style>
  </head>
  <body>
    <div class="box">
      <div class="pill">Success. You can close this tab.</div>
      <h2>Payment received</h2>
      <p class="muted">Stripe checkout completed. We are confirming your license provisioning.</p>
      <p>Purchase ID: <code>{purchase_safe or "unknown"}</code></p>
      <div id="status" class="state">Checking purchase status...</div>
      <p class="muted">If you started this from the terminal, return to it and wait for <code>status: licensed</code>.</p>
    </div>
    <script>
      const purchaseId = {purchase_json};
      const statusEl = document.getElementById("status");

      async function poll() {{
        if (!purchaseId) {{
          statusEl.textContent = "Payment completed. You can close this tab.";
          statusEl.classList.add("ok");
          return;
        }}
        try {{
          const res = await fetch("/v1/solo/purchases/" + encodeURIComponent(purchaseId), {{
            credentials: "same-origin"
          }});
          const data = await res.json();
          const state = data.status || "unknown";
          if (state === "licensed") {{
            statusEl.textContent = "Success. License is active. You can close this tab.";
            statusEl.classList.add("ok");
            return;
          }}
          if (state === "failed" || state === "canceled") {{
            statusEl.textContent = "Checkout completed but license status is " + state + ". Return to terminal for details.";
            return;
          }}
          statusEl.textContent = "Current status: " + state;
          if (state !== "failed" && state !== "canceled") {{
            setTimeout(poll, 2500);
          }}
        }} catch (err) {{
          statusEl.textContent = "Payment completed. Status lookup failed; return to terminal to confirm license.";
        }}
      }}
      poll();
    </script>
  </body>
</html>"""


def render_checkout_cancel_page(purchase_id: str) -> str:
    purchase_safe = html.escape(purchase_id)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Checkout Canceled</title>
    <style>
      body {{ font-family: "Avenir Next", "Segoe UI", sans-serif; margin: 0; padding: 22px; background: #f7f8fa; color: #172532; }}
      .box {{ max-width: 620px; margin: 0 auto; background: #fff; border: 1px solid #dae1e8; border-radius: 12px; padding: 18px; }}
      h2 {{ margin-top: 0; }}
      code {{ background: #f2f5f7; border-radius: 6px; padding: 2px 6px; }}
      .muted {{ color: #4d6274; }}
    </style>
  </head>
  <body>
    <div class="box">
      <h2>Checkout canceled</h2>
      <p class="muted">No charge was completed. You can restart anytime from the upgrade page.</p>
      <p>Purchase ID: <code>{purchase_safe or "unknown"}</code></p>
      <p><a href="/upgrade">Return to Upgrade to Pro</a></p>
    </div>
  </body>
</html>"""


def render_checkout_dev_page(purchase_id: str) -> str:
    purchase_safe = html.escape(purchase_id)
    purchase_json = json.dumps(purchase_id)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Maestro Solo Checkout (Dev)</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; line-height: 1.5; }}
      .card {{ max-width: 680px; padding: 1.2rem; border: 1px solid #ddd; border-radius: 8px; }}
      button {{ padding: 0.6rem 0.9rem; border-radius: 6px; border: 0; background: #0a5; color: white; cursor: pointer; }}
      code {{ background: #f5f5f5; padding: 0.2rem 0.4rem; border-radius: 4px; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2>Maestro Solo Checkout (Test Mode)</h2>
      <p>Purchase id: <code>{purchase_safe}</code></p>
      <p>This is a development checkout page. Click the button to simulate payment completion.</p>
      <button onclick="markPaid()">Mark Paid + Provision License</button>
      <pre id="out"></pre>
    </div>
    <script>
      const purchaseId = {purchase_json};
      async function markPaid() {{
        const res = await fetch('/v1/solo/dev/mark-paid', {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          credentials: 'same-origin',
          body: JSON.stringify({{ purchase_id: purchaseId }})
        }});
        const data = await res.json();
        document.getElementById('out').textContent = JSON.stringify(data, null, 2);
      }}
    </script>
  </body>
</html>
"""
