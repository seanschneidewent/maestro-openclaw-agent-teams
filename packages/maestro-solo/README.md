# maestro-solo

Standalone Maestro Solo product package.

## Local install (development)

```bash
pip install -e /absolute/path/to/repo/packages/maestro-engine -e /absolute/path/to/repo/packages/maestro-solo
```

## Commands

- `maestro-solo setup`
- `maestro-solo setup --quick`
- `maestro-solo auth login`
- `maestro-solo auth status`
- `maestro-solo auth logout`
- `maestro-solo purchase`
- `maestro-solo unsubscribe`
- `maestro-solo status`
- `maestro-solo entitlements status`
- `maestro-solo entitlements activate --token <token>`
- `maestro-solo up --tui`
- `maestro-solo ingest <path-to-pdfs>`
- `maestro-solo doctor --fix`
- `maestro-solo migrate-legacy`

## Core/Pro Distribution

- Installer supports user-facing flow mode via `MAESTRO_INSTALL_FLOW=free|pro`.
- `free` flow: setup -> up.
- `pro` flow: setup -> purchase -> up.
- Installer channel is controlled by `MAESTRO_INSTALL_CHANNEL=auto|core|pro`.
- Channel is persisted to `~/.maestro-solo/install-channel.txt`.
- Production install is expected to use private wheel specs (`MAESTRO_CORE_PACKAGE_SPEC` / `MAESTRO_PRO_PACKAGE_SPEC`), not editable repo installs.
- Runtime resolves effective capabilities from:
  1. install channel policy,
  2. signed entitlement token cache,
  3. paid local license fallback,
  4. default core mode.
