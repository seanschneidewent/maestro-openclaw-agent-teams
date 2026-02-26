# Solo Setup

## Goal

Provision a personal Maestro runtime and start either Free/Core mode or Pro mode.

## Fast Path (macOS)

Free install (setup -> up):

```bash
MAESTRO_CORE_PACKAGE_SPEC="<private-wheel-urls>" \
curl -fsSL https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/main/scripts/install-maestro-free-macos.sh | bash
```

Pro install (setup -> purchase -> up):

```bash
MAESTRO_CORE_PACKAGE_SPEC="<private-wheel-urls>" \
curl -fsSL https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/main/scripts/install-maestro-pro-macos.sh | bash
```

Installer behavior:

1. Installs prerequisites (brew/python/node/openclaw) if missing.
2. Creates `~/.maestro/venv-maestro-solo`.
3. Installs Solo private wheel spec.
4. Runs `maestro-solo setup --quick`.
5. Pro flow only: runs `maestro-solo purchase --mode live`.
6. Starts `maestro-solo up --tui`.

Existing install behavior:

- If setup is already complete, installer skips interactive setup.
- It runs `maestro-solo doctor --fix --no-restart` as a preflight check.
- It only falls back to interactive quick setup when preflight fails.

Optional env overrides:

- `MAESTRO_PURCHASE_EMAIL=person@example.com` for unattended Pro checkout launch.
- `MAESTRO_PRO_PLAN_ID=solo_monthly` to override default Pro plan ID.

Quick setup prompts:

- OpenAI OAuth (required)
- Gemini API key (required)
- Telegram pairing (optional but recommended)
- Tailscale (optional)

Quick setup auto-creates a local trial license when no valid local license exists.

## Manual Steps

1. Run `maestro-solo setup`.
2. Configure model provider key.
3. Configure Gemini key only if you need vision/image features.
4. Optionally configure Telegram.
5. Configure Tailscale (recommended for field access).
6. Complete setup and start with `maestro-solo up --tui`.

To upgrade an existing Free install:

```bash
maestro-solo purchase --email you@example.com --plan solo_monthly --mode live
```

## Result

- Install state is written to `~/.maestro-solo/install.json`.
- Free/Core route is `/` (text-only response + upgrade instruction).
- Pro route is `/workspace`.
- Field route (if Tailscale connected): `http://<tailscale-ip>:3000/` (Free) or `/workspace` (Pro).
- Workspace awareness state is written to `<workspace>/AWARENESS.md` by `maestro-solo doctor --fix`.
