# Solo Setup

## Goal

Provision a personal Maestro engine (`maestro-solo-personal`) and run the workspace UI.

## Steps

1. Run `maestro-solo setup`.
2. Configure model provider key.
3. Configure Gemini key only if you need vision/image features.
4. Optionally configure Telegram.
5. Configure Tailscale (recommended for field access).
6. Complete setup and start with `maestro-solo up --tui`.

## Result

- Install state is written to `~/.maestro-solo/install.json`.
- Primary route is `/workspace`.
- Field route (if Tailscale connected): `http://<tailscale-ip>:3000/workspace`.
