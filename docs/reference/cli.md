# CLI Reference

## Solo Commands (Primary)

- `maestro setup`
- `maestro up [--tui] [--skip-doctor] [--no-fix] [--no-restart] [--field-access-required] [--port 3000] [--store ...]`
- `maestro ingest <folder> [--dpi N] [--new-project-name "..."] [--project-name "..."] [--store ...]`
- `maestro doctor [--fix] [--json] [--store ...] [--no-restart] [--field-access-required]`
- `maestro update [--dry-run] [--no-restart] [--workspace ...]`
- `maestro serve [--port 3000] [--host 0.0.0.0] [--store ...]`

## Fleet Commands (Advanced Namespace)

- `maestro fleet enable [--dry-run] [--no-restart]`
- `maestro fleet status`
- `maestro fleet purchase [flags...]`
- `maestro fleet command-center [--open]`

## Compatibility Aliases (Deprecated)

- `maestro-setup` -> `maestro setup`
- `maestro-purchase` -> `maestro fleet purchase`
- `maestro start` is legacy; use `maestro up`

## Ingest Behavior in Solo

1. If no active project is set, ingest creates/uses the folder-name project and marks it active.
2. If an active project exists, ingest updates that project by default.
3. Use `--new-project-name` to intentionally create/switch project target.
4. `--project-name` is accepted for compatibility and treated as explicit new-project intent in Solo.

## Notes

- `maestro --help` is Solo-first.
- Fleet actions are grouped under `maestro fleet --help`.
