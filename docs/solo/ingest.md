# Solo Ingest

## Command

```bash
maestro-solo ingest /abs/path/to/plans
```

## Default Semantics

- If `--project-name` is omitted, Solo uses the input folder name as the project name.
- Ingest writes to that project store and records it as the active project in install state.

## Explicit Project Name

```bash
maestro-solo ingest /abs/path/to/plans --project-name "Project B"
```

## Notes

- Re-running ingest with the same project name updates that project.
- Re-running ingest with a different folder (or explicit name) creates/updates a different project.
