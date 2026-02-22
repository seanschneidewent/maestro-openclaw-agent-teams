# System Model

Maestro is a two-tier multi-agent system.

1. **The Commander** (`maestro-company`)
- Control-plane agent
- Owns Command Center orchestration
- Coordinates project maestros
- Maintains system awareness and repair actions

2. **Project Maestro agents** (`maestro-project-*`)
- Data-plane agents
- Scoped to one project knowledge store each
- Execute deep project reasoning and tooling

## Frontends

1. Command Center (`/command-center`)
- Fleet topology
- Commander node + project nodes
- Node modal with conversation and intelligence

2. Workspace frontend (`/{project-slug}` and `/agents/{agent-id}/workspace`)
- Page/pointer/workspace interaction for a single project context

## Core Principle

Command Center is orchestration and communication.
Project workspaces are project execution and detail retrieval.
