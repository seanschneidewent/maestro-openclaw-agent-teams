# Command Center Overview

Command Center is The Commander control plane.

## Layout

1. Top commander node (Tier 1)
2. Project node cards (Tier 2)
3. Right rail: System Doctor + System Directives
4. Add-node purchase tile

## Node Click Behavior

Selecting any node opens the intelligence modal.

- Commander modal: control-plane conversation + status
- Project modal: conversation + status + operational drawers

## Boundaries

- Commander send is read-only in modal by default.
- Project node send is manual and guarded by backend rules.
- Command Center never parses raw project files in-browser.
