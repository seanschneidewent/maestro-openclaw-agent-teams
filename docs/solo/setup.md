# Solo Setup

## Goal

Provision a personal Maestro engine (`maestro-solo-personal`) and run the workspace UI.

## Fast Path (macOS)

1. Run `maestro-solo setup --quick`.
2. Complete required prompts:
   - OpenAI OAuth (required)
   - Gemini API key (required)
   - Telegram bot + pairing (required)
3. Optionally configure Tailscale (can defer).
4. Start runtime with `maestro-solo up --tui`.

Quick setup auto-creates a local trial license when no valid local license exists.

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
- Workspace awareness state is written to `<workspace>/AWARENESS.md` by `maestro-solo doctor --fix`.
