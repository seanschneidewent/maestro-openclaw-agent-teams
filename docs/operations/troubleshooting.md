# Troubleshooting

## 401 Invalid API Key

- ensure key in `~/.openclaw/openclaw.json` is real, not placeholder
- run `maestro-solo doctor --fix`
- restart with `maestro-solo up --tui`

## Gateway Unauthorized / Token Missing

- align `gateway.auth.token` and `gateway.remote.token`
- run `maestro-solo doctor --fix`

## Command Center Not Updating

- verify websocket endpoint `/ws/command-center`
- verify file watcher has access to fleet store root

## Node Missing in Command Center

- ensure project exists in fleet store and contains `project.json`
- run `maestro-fleet update`
- run `maestro-fleet up --tui`
