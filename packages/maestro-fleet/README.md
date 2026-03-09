# maestro-fleet

Fleet/enterprise product package for Maestro.

Current runtime behavior:

- This package provides the dedicated `maestro-fleet` CLI.
- Most command behavior is still delegated to the current Fleet runtime modules in `maestro/`.
- `maestro-fleet up --tui` now uses Fleet-native runtime/state helpers plus the package-native `maestro_fleet.server` entrypoint.
- Solo and Fleet are split at the package + command level, with Fleet commands now preferring package-native runtime modules and only falling back to compatibility shims where needed.
- Fleet model defaults and labels are centralized in `maestro/fleet_constants.py`.

## Local install (development)

```bash
pip install -e /absolute/path/to/repo -e /absolute/path/to/repo/packages/maestro-fleet
```

## Remote install (customer machine)

Install from pinned wheel URLs (no repo checkout):

```bash
MAESTRO_FLEET_PACKAGE_SPEC="<engine_wheel_url> <root_wheel_url> <fleet_wheel_url>" \
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
