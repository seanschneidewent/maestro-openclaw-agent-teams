# CLI Reference

## Solo Commands (Primary)

- `maestro-solo setup`
- `maestro-solo setup --quick [--company-name "..."] [--replay]`
- `maestro-solo auth status|login|logout`
- `maestro-solo purchase [--preview]`
- `maestro-solo unsubscribe`
- `maestro-solo status [--remote-verify]`
- `maestro-solo up --tui`
- `maestro-solo ingest <folder> [--dpi N] [--project-name "..."] [--store ...]`
- `maestro-solo doctor [--fix] [--json] [--store ...] [--no-restart] [--field-access-required]`
- `maestro-solo migrate-legacy [--dry-run]`

## Fleet Commands (Advanced Namespace)

- `maestro-fleet enable [--dry-run] [--no-restart]`
- `maestro-fleet status`
- `maestro-fleet purchase [flags...]`
- `maestro-fleet command-center [--open]`
- `maestro-fleet ingest <folder> [--project-name "..."] [--dpi N] [--store ...]`
- `maestro-fleet doctor [--fix] [--json] [--store ...] [--no-restart]`
- `maestro-fleet up --tui`
- `maestro-fleet serve [--port 3000] [--host 0.0.0.0] [--store ...]`
- `maestro-fleet update [--workspace ...] [--dry-run] [--no-restart]`

## Compatibility Aliases (Deprecated)

- `maestro-setup` forwards to `maestro-solo setup`
- `maestro-purchase` forwards to `maestro-fleet purchase`
- `maestro fleet ...` forwards to `maestro-fleet ...` during transition
- `maestro start` is deprecated; use `maestro-solo up --tui`

## Ingest Behavior in Solo

1. If `--project-name` is omitted, ingest uses the input folder name.
2. Solo records that target as active project metadata in install state.
3. Use `--project-name` to force a specific target name.

## Notes

- `maestro-fleet` is the dedicated Fleet product CLI.
- Fleet internals are being split into package-native modules in a later phase; current CLI behavior is stable now.
- `setup --quick` is a macOS fast path designed for one-command install/bootstrap and requires Telegram configuration.
- `setup --quick --replay` re-renders the full setup journey while reusing existing configuration.
- `purchase --preview` renders purchase UX without creating checkout sessions.
- `journey` is an internal installer orchestrator used by `/free` and `/pro` launcher scripts.
- `maestro-solo purchase` and `maestro-solo unsubscribe` require a valid billing auth session (`maestro-solo auth login`).
