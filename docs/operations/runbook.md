# Runtime Runbook

## Solo Daily Path (Default)

```bash
maestro-solo up --tui
```

Then open:

- `http://localhost:3000/workspace`
- `http://<tailscale-ip>:3000/workspace` (same tailnet for field devices)

## Setup and Upgrade

```bash
maestro-solo setup
```

If you need to migrate from the old mixed install:

```bash
maestro-solo migrate-legacy
```

## Repair

```bash
maestro-solo doctor --fix
```

Regenerate frontend artifacts if runtime/UI assets are missing:

```bash
maestro-solo update
```

Require field URL readiness in Solo:

```bash
maestro-solo doctor --fix --field-access-required
```

## Solo Fast Restart (Advanced)

```bash
maestro-solo up --skip-doctor
```

## Fleet Enablement (Advanced)

```bash
maestro-fleet enable
maestro-fleet status
maestro-fleet update
maestro-fleet up --tui
```

Then open:

- `http://localhost:3000/command-center`
