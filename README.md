# Maestro

Maestro is a **Solo-first** construction agent runtime with optional Fleet/enterprise mode.

## Quickstart (Solo, macOS)

Free one-liner (setup -> up):

```bash
curl -fsSL https://maestro-billing-service-production.up.railway.app/free | bash
```

Pro one-liner (setup -> purchase -> up):

```bash
curl -fsSL https://maestro-billing-service-production.up.railway.app/pro | bash
```

Pro flow prompts for billing email, opens Stripe Checkout, waits for license provisioning, then starts runtime.
If setup already exists, installer runs a fast `doctor --fix` preflight and skips re-entering setup values.
Pro flow now runs Google sign-in (`maestro-solo auth login`) before checkout when needed.

Branding tip: point `get.maestro.run` (or your preferred domain) to the billing service and publish:

```bash
curl -fsSL https://get.maestro.run/free | bash
curl -fsSL https://get.maestro.run/pro | bash
```

Advanced channel override (optional):

```bash
MAESTRO_INSTALL_CHANNEL=pro \
MAESTRO_PRO_PACKAGE_SPEC="https://downloads.example.com/maestro_engine-0.1.0-py3-none-any.whl https://downloads.example.com/maestro_solo-0.1.0-py3-none-any.whl" \
curl -fsSL https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/refs/heads/main/scripts/install-maestro-pro-macos.sh | bash
```

Notes:

- `MAESTRO_*_PACKAGE_SPEC` supports whitespace or comma-separated pip args.
- Pass both `maestro-engine` and `maestro-solo` wheel URLs unless your private index resolves dependencies.
- Optional for unattended Pro installs: `MAESTRO_PURCHASE_EMAIL=person@example.com`.
- Optional override to force a new checkout even when Pro is already active: `MAESTRO_FORCE_PRO_PURCHASE=1`.
- Local repo dev mode is still available via `MAESTRO_USE_LOCAL_REPO=1`.

Open:

- Free/Core: `http://localhost:3000/` (text-only runtime + upgrade prompt)
- Pro: `http://localhost:3000/workspace`

## Manual Setup (Development)

```bash
pip install -e /absolute/path/to/repo/packages/maestro-engine -e /absolute/path/to/repo/packages/maestro-solo
maestro-solo setup
maestro-solo update
maestro-solo up --tui
maestro-solo ingest /abs/path/to/plans
```

## Fleet (Advanced)

```bash
pip install -e /absolute/path/to/repo/packages/maestro-fleet
maestro-fleet enable
maestro-fleet update
maestro-fleet status
```

Fleet UI:

- `http://localhost:3000/command-center`

## Documentation

Primary documentation index:

- [docs/README.md](docs/README.md)

Core sections:

- [Solo Setup](docs/solo/setup.md)
- [Solo Workspace](docs/solo/workspace.md)
- [Solo Ingest](docs/solo/ingest.md)
- [Solo Payment and License](docs/solo/payment-license.md)
- [Fleet Enablement](docs/fleet/enable.md)
- [CLI Reference](docs/reference/cli.md)
- [Paths and Environment](docs/reference/paths-env.md)

## Repository Layout

- `packages/maestro-engine`: shared engine/server modules
- `packages/maestro-solo`: solo CLI/runtime package
- `packages/maestro-fleet`: fleet CLI/runtime package
- `workspace_frontend`: workspace UI
- `command_center_frontend`: command-center UI
- `agent`: Maestro agent skills/extensions
