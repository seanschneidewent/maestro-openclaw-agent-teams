# ADR 0002: Strict Agent Isolation

## Decision

Project maestros are strictly project-scoped. Commander orchestrates communication, not direct project-file access.

## Rationale

- safety and tenant isolation
- predictable behavior for customers
- clean multi-agent architecture

## Consequences

- project nodes must report not-ready when no local project store exists
- Commander must route through project agents for project-level answers
