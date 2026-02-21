# Command Center

Current implementation reference for Company Maestro Command Center.

## What Is Implemented

- React tactical UI served at `/command-center`
- Fleet topology cards + project node selection
- Node Intelligence modal drawers per project
- Command Center websocket updates (`/ws/command-center`)
- Read API surface:
  - `GET /api/command-center/state`
  - `GET /api/command-center/projects/{slug}`
  - `GET /api/system/awareness`
  - `GET /api/command-center/fleet-registry`
- Control-plane actions via:
  - `POST /api/command-center/actions`

## UI Behavior

- Command Center is the **control-plane display** for Company Maestro.
- Telegram/default-agent conversation remains primary for orchestration.
- UI includes controlled mutations through action API (for example `doctor_fix`).
- Node click opens modal with:
  - operational health
  - critical path + constraints
  - RFI/submittal control
  - decision + exposure
  - scope watchlist

## Data Contracts

The frontend consumes normalized backend contracts only.
It does not parse raw project store JSON directly.

Primary server modules:
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/command_center.py`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/control_plane.py`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server.py`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/maestro/server_actions.py`

## Store Layout Support

Command Center supports both:
1. single-project root (`<store>/project.json`)
2. multi-project root (`<store>/<project>/project.json`)

Fixture path used during implementation/testing:
- `/Users/seanschneidewent/Desktop/knowledge_store_data`

## Operational Notes

- Preferred runtime command: `maestro up`
- Use `maestro up --tui` for live monitor mode.
- Use `maestro update` after upgrades.
- Use `maestro doctor --fix` for repair/self-heal.

## Related Docs

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/command-center.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/api-contracts.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/operations.md`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/docs/troubleshooting.md`
