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

## Installer Fails with "Package spec is empty"

- this means billing launcher variables are not set for wheel install specs
- in Railway billing service set:
  - `MAESTRO_INSTALLER_CORE_PACKAGE_SPEC`
  - `MAESTRO_INSTALLER_PRO_PACKAGE_SPEC`
- confirm `/free` or `/pro` output includes both `maestro_engine` and `maestro_solo` wheel URLs

## Installer Stuck Before Auth/Purchase

- ensure billing service URL is reachable from client machine
- verify `MAESTRO_BILLING_URL` is correct in launcher output
- test directly:
  - `maestro-solo auth status --billing-url https://<billing-domain>`
  - `maestro-solo purchase --email you@example.com --plan solo_monthly --mode live --preview --billing-url https://<billing-domain>`
