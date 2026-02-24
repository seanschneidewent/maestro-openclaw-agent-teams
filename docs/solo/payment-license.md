# Solo Payment and License Flow

## Goal

Validate that a completed payment provisions a license key through a separate license service, then unlocks `maestro-solo up`.

## Local Services

Run in separate terminals:

```bash
maestro-solo-license-service --port 8082
maestro-solo-billing-service --port 8081
```

Optional environment overrides:

- `MAESTRO_LICENSE_URL` (default `http://127.0.0.1:8082`)
- `MAESTRO_BILLING_URL` (default `http://127.0.0.1:8081`)
- `MAESTRO_INTERNAL_TOKEN` (shared service-to-service token)

## Purchase Flow

```bash
maestro-solo purchase --email you@example.com --plan solo_test_monthly
```

What happens:

1. Billing purchase is created.
2. CLI opens checkout URL.
3. On payment, billing calls license service.
4. License key is returned and saved locally under `~/.maestro-solo/`.

## Validate License

```bash
maestro-solo status
maestro-solo status --remote-verify
```

## Start Runtime

```bash
maestro-solo up --tui
```

If no valid license exists, startup is blocked until purchase succeeds.
