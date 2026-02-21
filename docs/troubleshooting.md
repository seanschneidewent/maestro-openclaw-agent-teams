# Troubleshooting

## `401 Incorrect API key provided`

Common cause: placeholder value still present in `~/.openclaw/openclaw.json`.

Fix:
1. Set real provider key (`OPENAI_API_KEY`, `GEMINI_API_KEY`, or `ANTHROPIC_API_KEY`).
2. Run:
   ```bash
   maestro doctor --fix
   maestro up
   ```

## Gateway auth token mismatch

Symptom in logs: unauthorized / gateway token missing.

Fix:
```bash
maestro doctor --fix
```

The doctor flow can align local/remote gateway token fields.

## Device pairing required

Symptom: OpenClaw reports pairing required.

Fix:
1. Trigger pairing from Telegram/bot flow.
2. Run:
   ```bash
   maestro doctor --fix
   ```

## Port already in use (`0.0.0.0:3000`)

Another process is already serving.

Fix options:
1. Stop existing process.
2. Start on another port:
   ```bash
   maestro up --port 3001
   ```

## Command Center not updating

1. Confirm websocket endpoint reachable: `/ws/command-center`
2. Confirm store root is correct in awareness response.
3. Run:
   ```bash
   maestro doctor --fix
   maestro up
   ```
