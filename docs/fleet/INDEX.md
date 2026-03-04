# Fleet Docs Index

Start here for Maestro Fleet architecture, operator flow, and code navigation.

## Operator Guides

1. [Remote Deploy Playbook](deploy-playbook.md)
2. [Operator Flow (Current)](operator-flow.md)
3. [Supported Topologies](supported-topologies.md)
4. [Release + Launcher Runbook](release-launcher.md)

## Product Behavior Contracts

1. [Commander Behavior Contract](commander-behavior-contract.md)
2. [Fleet Command Center Notes](command-center.md)
3. [Project Create Flow](project-create.md)

## Implementation Maps

1. [Fleet Code Map](code-map.md)
2. [Fleet Enable](enable.md)

## Fast Pointers

- Primary deploy orchestration: `maestro/fleet_deploy.py`
- Fleet CLI wrapper: `packages/maestro-fleet/src/maestro_fleet/cli.py`
- Root CLI integration: `maestro/cli.py`
- Installer entrypoint: `scripts/install-maestro-fleet.sh`
