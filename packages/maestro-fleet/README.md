# maestro-fleet

Fleet/enterprise product package for Maestro.

Current staging behavior:

- This package provides the dedicated `maestro-fleet` CLI.
- Runtime behavior is delegated to the current Fleet runtime modules in `maestro/`.
- Solo and Fleet are split at the package + command level while Fleet internals are migrated into package-native modules.

## Local install (development)

```bash
pip install -e /absolute/path/to/repo -e /absolute/path/to/repo/packages/maestro-fleet
```

## Commands

- `maestro-fleet enable`
- `maestro-fleet status`
- `maestro-fleet purchase`
- `maestro-fleet command-center`
- `maestro-fleet up --tui`
