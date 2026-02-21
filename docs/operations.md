# Operations

## New Install

```bash
pip install -e .
maestro-setup
maestro up
```

## Daily Startup

```bash
maestro up
```

With monitor:

```bash
maestro up --tui
```

## Upgrade Existing Install

```bash
maestro update
maestro doctor --fix
maestro up
```

## Provision Project Maestro

```bash
maestro-purchase
```

Then ingest project plans for that project:

```bash
maestro ingest "/abs/path/to/project/pdfs" --project-name "Project Name"
```

## Recommended Operator Defaults

- Prefer `maestro up` over `maestro start`.
- Treat `maestro start` as legacy/compat path.
- Avoid manual `--store` unless debugging or running fixtures.
- Use absolute ingest paths.

## URL Expectations

- Local: `http://localhost:3000/command-center`
- Tailnet: `http://<tailscale-ip>:3000/command-center`
- Preferred URL comes from `/api/system/awareness.network.recommended_url`.
