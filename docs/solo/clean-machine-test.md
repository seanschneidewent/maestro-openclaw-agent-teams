# Solo Clean-Machine Test

## Goal

Run a fresh end-to-end validation from install through licensed runtime.

## Sequence

1. (macOS fast path) Run one command:

```bash
curl -fsSL https://raw.githubusercontent.com/seanschneidewent/maestro-openclaw-agent-teams/main/scripts/install-maestro-macos.sh | bash
```

Manual path:

```bash
pip install -e /absolute/path/to/repo/packages/maestro-engine -e /absolute/path/to/repo/packages/maestro-solo
```

2. Run setup:

```bash
maestro-solo setup
```

3. Start local payment services (separate terminals):

```bash
maestro-solo-license-service --port 8082
maestro-solo-billing-service --port 8081
```

4. Complete purchase:

```bash
maestro-solo purchase --email you@example.com --plan solo_test_monthly
```

5. Verify license:

```bash
maestro-solo status --remote-verify
```

6. Start runtime:

```bash
maestro-solo up --tui
```

7. Ingest plans:

```bash
maestro-solo ingest /abs/path/to/plans
```

8. Open workspace:

`http://localhost:3000/workspace`

## Pass Criteria

1. Setup succeeds with valid model auth.
2. Purchase transitions to licensed.
3. `maestro-solo status` reports local valid license.
4. `maestro-solo up --tui` starts and shows workspace URL.
5. Workspace search/ingest flow works with no Fleet UI elements.
