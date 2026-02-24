# Fleet Enable

Fleet features are explicit and opt-in.
Fleet is a distinct product surface from Solo.

## Command

```bash
maestro-fleet enable
```

This command:

1. Sets profile to `fleet`.
2. Runs update migration flow.
3. Runs doctor fix flow.

## Verify

```bash
maestro-fleet status
```
