# Solo Ingest

## Command

```bash
maestro ingest /abs/path/to/plans
```

## Default Semantics

- Solo keeps one active project target by default.
- First ingest sets active project slug/name.
- Later ingests update the active project unless explicitly overridden.

## Explicit New Project

```bash
maestro ingest /abs/path/to/plans --new-project-name "Project B"
```

Compatibility flag:

```bash
maestro ingest /abs/path/to/plans --project-name "Project B"
```

In Solo this is treated as explicit new-project intent.
