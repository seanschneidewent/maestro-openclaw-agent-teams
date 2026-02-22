# Maintenance

## Common Checks

1. OpenClaw gateway running
2. gateway auth token aligned
3. telegram configured and paired
4. fleet store path exists
5. command center build present

## Safe Update Flow

1. `maestro update`
2. `maestro doctor --fix`
3. `maestro up`

## Known Failure Pattern

If port 3000 is already in use, stop previous process before re-running `maestro up`.
