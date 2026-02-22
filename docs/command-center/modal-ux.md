# Node Modal UX

## Sections

1. Control Plane panel
- system posture
- URLs/paths
- workspace links (project nodes)
- ingest command and preflight
- concise status summary card

2. Live Conversation panel
- normalized user/assistant timeline
- manual send for project nodes
- clear disabled state for unsupported nodes

3. Project Drawers (project nodes only)
- operational health
- critical path and constraints
- RFI/submittal control
- decision/exposure
- scope gaps/overlaps

## Refresh Model

- Conversation and status poll every 5s while modal is open.
- Command Center websocket refresh keeps node cards current.

## Accessibility

- Focus trap in modal
- ESC closes modal
- Backdrop click closes modal
