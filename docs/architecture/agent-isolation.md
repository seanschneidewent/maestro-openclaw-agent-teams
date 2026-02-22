# Agent Isolation

Isolation is a hard product boundary.

## Rules

1. Commander does not run project knowledge tools directly.
2. A project maestro cannot read sibling project stores.
3. Cross-project synthesis is brokered by Commander orchestration only.
4. Commander conversation send endpoint is restricted to `maestro-project-*` targets.

## Enforcement Layers

1. Workspace role policy (`MAESTRO_AGENT_ROLE`)
2. Tooling/runtime guards in Python modules
3. Command Center API send guards
4. Registry-scoped project/agent mapping

## Practical Outcome

If a project node has no ingested store, that node should report not-ready state instead of answering from other project data.
