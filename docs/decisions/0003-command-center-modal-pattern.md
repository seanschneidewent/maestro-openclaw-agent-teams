# ADR 0003: Topology + Modal Pattern

## Decision

Keep Command Center as tactical topology UI and place conversation/status/deep intelligence inside node modal expansion.

## Rationale

- preserves high-level fleet situational view
- keeps detailed interaction contextual to selected node
- avoids replacing familiar control-plane visual language

## Consequences

- modal complexity managed via component/hook decomposition
- backend node APIs remain reusable regardless of shell layout
