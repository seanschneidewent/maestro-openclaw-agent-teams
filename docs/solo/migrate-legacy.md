# Solo Migration from Mixed Install

## Goal

Copy existing Solo-relevant state from old mixed install paths into isolated Solo paths.

## Command

```bash
maestro-solo migrate-legacy
```

Dry-run mode:

```bash
maestro-solo migrate-legacy --dry-run
```

## Migration Sources

- `~/.maestro/install.json` (old install state)
- Old workspace references found in state/config
- Existing local Solo license file (if present)

## Migration Behavior

1. Idempotent: safe to run more than once.
2. Non-destructive: does not delete old paths.
3. Writes current state to `~/.maestro-solo/install.json`.

## When to Use

- Before first `maestro-solo setup` on a machine with previous mixed installs.
- Before clean-machine verification if you want to preserve prior state.
