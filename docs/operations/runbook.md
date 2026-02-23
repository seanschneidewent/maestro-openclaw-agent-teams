# Runtime Runbook

## Solo Daily Path (Default)

```bash
maestro up
```

Then open:

- `http://localhost:3000/workspace`
- `http://<tailscale-ip>:3000/workspace` (same tailnet for field devices)

## Setup and Upgrade

```bash
maestro setup
maestro update
```

## Repair

```bash
maestro doctor --fix
```

Require field URL readiness in Solo:

```bash
maestro doctor --fix --field-access-required
```

## Server Only

```bash
maestro serve --port 3000
```

## Fleet Enablement (Advanced)

```bash
maestro fleet enable
maestro fleet status
```

Then open:

- `http://localhost:3000/command-center`
