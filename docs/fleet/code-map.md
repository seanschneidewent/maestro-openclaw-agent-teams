# Fleet Code Map

Use this map to quickly find where Fleet behavior is implemented.

## Entry Points

1. `scripts/install-maestro-fleet.sh`
2. `packages/maestro-fleet/src/maestro_fleet/cli.py`
3. `maestro/cli.py`
4. `maestro/fleet_deploy.py`

## Deploy Step Ownership

The `run_deploy(...)` function in `maestro/fleet_deploy.py` uses searchable markers:

1. `FLEET_STEP_1_PREREQS`
2. `FLEET_STEP_2_MODELS`
3. `FLEET_STEP_3_COMPANY_PROFILE`
4. `FLEET_STEP_4_PROVIDER_KEYS`
5. `FLEET_STEP_5_COMMANDER_TELEGRAM`
6. `FLEET_STEP_6_INITIAL_PROJECT`
7. `FLEET_STEP_7_DOCTOR_RUNTIME`
8. `FLEET_STEP_8_COMMISSIONING`

## Shared Constants

- `maestro/fleet_constants.py`
  - Fleet profile and port defaults
  - Deploy step titles
  - Provider key/model labels

## OpenClaw Safety + Routing

1. `maestro/openclaw_guard.py`  
   - override protection / fail-closed checks
2. `maestro/openclaw_profile.py`  
   - profile-aware config/workspace pathing
3. `maestro/fleet_deploy.py`  
   - gateway repair and pairing readiness

## Project Provisioning

1. `maestro/purchase.py` (project provisioning path reused by Fleet)
2. `docs/fleet/project-create.md`

## Runtime + Health

1. `maestro/doctor.py`
2. `maestro/fleet_deploy.py` (`_run_doctor_for_deploy`, detached server bring-up, commissioning report)
3. `packages/maestro-fleet/src/maestro_fleet/monitor.py`

## Tests To Run For Fleet Changes

```bash
pytest tests/test_fleet_deploy.py tests/test_doctor.py tests/test_cli.py packages/maestro-fleet/tests/test_fleet_cli_parser.py -q
```

## Operator-Facing Docs

1. `docs/fleet/operator-flow.md`
2. `docs/fleet/deploy-playbook.md`
3. `docs/fleet/supported-topologies.md`
4. `docs/fleet/release-launcher.md`
