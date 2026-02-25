# Solo Clean-Machine Test

## Goal

Run a fresh end-to-end validation from wheel install through Core startup and Pro purchase unlock.

## Sequence

1. (macOS fast path) Run one command:

```bash
MAESTRO_INSTALL_CHANNEL=core \
MAESTRO_CORE_PACKAGE_SPEC="https://downloads.example.com/maestro_engine-0.1.0-py3-none-any.whl https://downloads.example.com/maestro_solo-0.1.0-py3-none-any.whl" \
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

3. Verify status before purchase (should still run in Core):

```bash
maestro-solo status
maestro-solo entitlements status
```

4. Start local payment services (separate terminals):

```bash
maestro-solo-license-service --port 8082
maestro-solo-billing-service --port 8081
```

5. Complete purchase:

```bash
maestro-solo purchase --email you@example.com --plan solo_test_monthly --mode test --billing-url http://127.0.0.1:8081
```

6. Verify Pro entitlement after purchase:

```bash
maestro-solo status --remote-verify
maestro-solo entitlements status
```

7. Verify unsubscribe portal opens:

```bash
maestro-solo unsubscribe
```

8. Start runtime:

```bash
maestro-solo up --tui
```

9. Ingest plans:

```bash
maestro-solo ingest /abs/path/to/plans
```

10. Open workspace:

`http://localhost:3000/workspace`

## Pass Criteria

1. Setup succeeds with valid model auth.
2. Core install runs without source checkout and without editable installs.
3. `maestro-solo up --tui` starts in Core mode before purchase.
4. Purchase transitions to licensed and status resolves Pro tier.
5. `maestro-solo unsubscribe` opens Stripe Customer Portal for self-serve cancellation.
6. Workspace search/ingest flow works with no Fleet UI elements.
