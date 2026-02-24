# System Model

Maestro is a split-product system with shared engine primitives.

1. **Maestro Solo**
- Product for individual superintendent workflows
- Primary CLI: `maestro-solo`
- Primary UI: `/workspace`
- Uses one active workspace/store context at a time

2. **Maestro Fleet**
- Product for enterprise control-plane workflows
- Primary CLI: `maestro-fleet`
- Primary UI: `/command-center`
- Coordinates Commander + project maestros across projects

## Fleet Agent Roles

1. **The Commander** (`maestro-company`)
- Control-plane agent
- Owns command-center orchestration
- Coordinates project maestros
- Maintains system awareness and repair actions

2. **Project Maestro agents** (`maestro-project-*`)
- Data-plane agents
- Scoped to one project knowledge store each
- Execute deep project reasoning and tooling

## Frontends

1. Workspace frontend (`/workspace`)
- Solo-first default interface
- Project search, pointers, notes, and schedule operations

2. Command Center (`/command-center`)
- Fleet topology
- Commander node + project nodes
- Node modal with conversation and intelligence

Compatibility routes remain for transition (`/{project-slug}`, `/agents/{agent-id}/workspace`).

## Core Principle

Solo and Fleet are distinct product surfaces.
Shared engine modules remain product-agnostic.
