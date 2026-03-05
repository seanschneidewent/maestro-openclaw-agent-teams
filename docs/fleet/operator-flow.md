# Fleet Operator Flow (Current)

This is the current end-to-end workflow for setting up Fleet on a customer machine.

## 1. Launch

Run:

```bash
curl -fsSL https://maestro-billing-service-production.up.railway.app/fleet | bash
```

What this does:

1. Downloads the platform wrapper.
2. Runs `scripts/install-maestro-fleet.sh`.
3. Verifies/install prerequisites (python, node, npm, openclaw, tailscale when required).
4. Creates `~/.maestro/venv-maestro-fleet`.
5. Installs pinned Fleet wheels.
6. Starts `maestro-fleet deploy`.

## 2. Deploy Wizard Steps

Deploy currently runs 8 steps:

1. Prerequisites
2. Commander + Project Models
3. Company Profile
4. Provider Keys
5. Commander Telegram
6. Initial Project Maestro (optional, default: No)
7. Doctor + Runtime Health
8. Commander Commissioning

## 3. Runtime Bring-Up

During deploy:

1. Fleet profile is set.
2. Fleet OpenClaw config is written under `~/.openclaw-maestro-fleet`.
3. Gateway is repaired/restarted if needed.
4. Detached Maestro server is started (default web port 3000).
5. Command Center API health is checked.
6. Deployment summary is printed with URLs and bot handles.
7. If no project flags are provided, Fleet stays commander-only after install.

Create project maestros later (explicitly) with:

```bash
maestro-fleet project create --project-name "..." --assignee "..."
```

## 4. Telegram Pairing

Commander pairing can be approved during deploy (interactive), or later:

```bash
openclaw --profile maestro-fleet pairing approve telegram <CODE>
```

## 5. Post-Deploy Operator Checks

```bash
openclaw --profile maestro-fleet gateway status --json
curl -fsS http://127.0.0.1:3000/api/command-center/state
maestro-fleet doctor --fix
```

## 6. Runtime TUI

For live monitoring:

```bash
maestro-fleet up --tui
```
