# Doctor and Directives

## System Doctor

UI action calls `doctor_fix` via action API.

- validates OpenClaw gateway/auth state
- checks token alignment and pairing readiness
- returns structured check results

## System Directives

Stored at `<store_root>/.command_center/system_directives.json`.

Active directives feed Command Center right rail and backend state.
Lifecycle actions:

1. list
2. upsert
3. archive

Directives are alignment policy records, not transient chat memory.
