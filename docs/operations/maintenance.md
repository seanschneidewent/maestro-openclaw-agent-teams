# Maintenance

## Common Checks

1. OpenClaw gateway running
2. gateway auth token aligned
3. license state valid for the product you are running
4. store path exists and is writable
5. frontend build artifacts present (`workspace_frontend/dist`, `command_center_frontend/dist`)

## Frontend Artifact Policy

- `workspace_frontend/dist` and `command_center_frontend/dist` are generated build artifacts.
- They should not be committed to git.
- `maestro update` auto-builds missing frontend dist artifacts for the active profile.
  - Solo: ensures `workspace_frontend/dist`
  - Fleet: ensures both `workspace_frontend/dist` and `command_center_frontend/dist`

## Manual Frontend Rebuild (if needed)

```bash
npm --prefix workspace_frontend install
npm --prefix workspace_frontend run build

npm --prefix command_center_frontend install
npm --prefix command_center_frontend run build
```

## Solo Safe Update Flow

1. `maestro-solo setup`
2. `maestro-solo doctor --fix`
3. `maestro-solo up --tui`

## Fleet Safe Update Flow

1. `maestro-fleet enable`
2. `maestro-fleet update`
3. `maestro-fleet doctor --fix`
4. `maestro-fleet up --tui`

## Known Failure Pattern

If port 3000 is already in use, stop previous process before re-running `maestro-solo up --tui`.
