# Command Center

## Purpose

Command Center is Company Maestro's control-plane UI for fleet visibility and guided operations.
It is not a raw-file browser; it consumes normalized backend state.

## URL and Routing

- URL: `/command-center`
- Assets: `/command-center/assets/*`
- Live updates: `/ws/command-center`

## Backend Contracts

- `GET /api/command-center/state`
- `GET /api/command-center/projects/{slug}`
- `GET /api/system/awareness`
- `GET /api/command-center/fleet-registry`
- `POST /api/command-center/actions`

## Current UI Modules

- `/Users/seanschneidewent/maestro-openclaw-agent-teams/command_center_frontend/src/App.jsx`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/command_center_frontend/src/components/ProjectNode.jsx`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/command_center_frontend/src/components/NodeIntelligenceModal.jsx`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/command_center_frontend/src/components/DoctorPanel.jsx`
- `/Users/seanschneidewent/maestro-openclaw-agent-teams/command_center_frontend/src/components/PurchaseCommandModal.jsx`

## Interaction Model

- Project card click opens node intelligence modal.
- Add-node tile opens purchase command helper.
- Doctor panel triggers backend repair action (`doctor_fix`).
- Websocket updates refresh fleet cards + awareness + open modal detail.

## Fixture Validation Path

- `/Users/seanschneidewent/Desktop/knowledge_store_data`
