# maestro-fleet

Fleet/enterprise product package for Maestro.

Current staging behavior:

- This package provides the dedicated `maestro-fleet` CLI.
- Runtime behavior is delegated to the current Fleet runtime modules in `maestro/`.
- `maestro-fleet up --tui` runs a Fleet-native setup monitor (separate from Solo monitor internals).
- Solo and Fleet are split at the package + command level while Fleet internals are migrated into package-native modules.

## Local install (development)

```bash
pip install -e /absolute/path/to/repo -e /absolute/path/to/repo/packages/maestro-fleet
```

## Remote install (customer machine)

Install from pinned wheel URLs (no repo checkout):

```bash
MAESTRO_FLEET_PACKAGE_SPEC="<root_wheel_url> <fleet_wheel_url>" \
MAESTRO_INSTALL_BASE_URL="<pinned_install_script_url>" \
curl -fsSL "<pinned_linux_wrapper_script_url>" | bash
```

Release helper:

```bash
bash scripts/release-maestro-fleet.sh <version>
```

The release helper now:
- publishes Fleet wheels to GitHub Release tag `fleet-v<version>`
- updates Railway billing vars for `/fleet` launcher (`MAESTRO_INSTALLER_FLEET_PACKAGE_SPEC`)
- waits for Railway deploy success and smoke-checks `GET /fleet`

## Commands

- `maestro-fleet enable`
- `maestro-fleet status`
- `maestro-fleet project create`
- `maestro-fleet project set-model`
- `maestro-fleet commander set-model`
- `maestro-fleet license generate`
- `maestro-fleet deploy`
- `maestro-fleet command-center`
- `maestro-fleet up --tui`
