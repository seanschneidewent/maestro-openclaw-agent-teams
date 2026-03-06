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
- No project-license generation or activation
- OpenClaw agent + Telegram routing configuration
- Gateway reload and ingest command output

Switch an existing project to a different model/provider:

```bash
maestro-fleet project set-model \
  --project "CFA Love Field" \
  --model "anthropic/claude-opus-4-6"
```

Project Maestro creation is direct. There is no separate Fleet license step.
