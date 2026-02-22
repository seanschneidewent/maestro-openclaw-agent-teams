# Runtime Runbook

## Preferred Daily Startup

```bash
maestro up
```

This runs doctor/fix and starts server.

## Setup and Upgrade

```bash
maestro-setup
maestro update
```

## Repair

```bash
maestro doctor --fix
```

## Server Only

```bash
maestro serve --port 3000
```

## Validation URLs

- local: `http://localhost:3000/command-center`
- tailnet: `http://<tailscale-ip>:3000/command-center`
