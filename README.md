# Maestro

Maestro is a **Solo-first** construction agent runtime with optional Fleet/enterprise mode.

## Quickstart (Solo, macOS)

```bash
MAESTRO_INSTALL_CHANNEL=core \
MAESTRO_CORE_PACKAGE_SPEC="https://downloads.example.com/maestro_engine-0.1.0-py3-none-any.whl https://downloads.example.com/maestro_solo-0.1.0-py3-none-any.whl" \
curl -fsSL https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/main/scripts/install-maestro-macos.sh | bash
```

This bootstrap installs prerequisites, installs the selected Solo package channel, runs quick setup, and starts `maestro-solo up --tui`.

Channel examples (private wheels):

```bash
MAESTRO_INSTALL_CHANNEL=core \
MAESTRO_CORE_PACKAGE_SPEC="https://downloads.example.com/maestro_engine-0.1.0-py3-none-any.whl https://downloads.example.com/maestro_solo-0.1.0-py3-none-any.whl" \
curl -fsSL https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/main/scripts/install-maestro-macos.sh | bash

MAESTRO_INSTALL_CHANNEL=pro \
MAESTRO_PRO_PACKAGE_SPEC="https://downloads.example.com/maestro_engine-0.1.0-py3-none-any.whl https://downloads.example.com/maestro_solo-0.1.0-py3-none-any.whl" \
curl -fsSL https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/main/scripts/install-maestro-macos.sh | bash
```

Notes:

- `MAESTRO_*_PACKAGE_SPEC` supports whitespace or comma-separated pip args.
- Pass both `maestro-engine` and `maestro-solo` wheel URLs unless your private index resolves dependencies.
- Local repo dev mode is still available via `MAESTRO_USE_LOCAL_REPO=1`.

Open:

- `http://localhost:3000/workspace`

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
