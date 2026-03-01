# Fleet Project Create

Create and provision a new Project Maestro node:

```bash
maestro-fleet project create \
  --project-name "CFA Love Field" \
  --assignee "Sean" \
  --telegram-token "<project_bot_token>" \
  --non-interactive
```

Behavior in Fleet mode:

- No payment/billing gates
- Local project key generation only
- 1-year project-key expiry
- OpenClaw agent + Telegram routing configuration
- Gateway reload and ingest command output

Generate a key explicitly (no project creation):

```bash
maestro-fleet license generate --project-name "CFA Love Field"
```
