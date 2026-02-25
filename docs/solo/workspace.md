# Solo Workspace

## Canonical Routes

- UI: `/workspace`
- WS: `/workspace/ws`
- API: `/workspace/api/*`

## Field Access (Tailnet)

1. Ensure the host machine is connected to Tailscale.
2. Ensure field device is connected to same tailnet.
3. Open `http://<tailscale-ip>:3000/workspace`.

Doctor enforcement:

```bash
maestro-solo doctor --fix --field-access-required
```

## Capability Focus

1. Search ingested project knowledge.
2. Build/manage workspaces.
3. Review project notes and linked source pages.
4. Manage schedule items and constraints.

## Compatibility Routes

Compatibility routes remain active during transition:

- `/{slug}/...`
- `/agents/{agent_id}/workspace/...`
