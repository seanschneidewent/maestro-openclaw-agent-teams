---
name: commander
description: Commander control-plane skill for provisioning Maestro project agents, onboarding project stores, dispatching work to project maestros, and maintaining Fleet runtime health.
---

# Commander Control-Plane Skill

This skill is for **The Commander** only.

Use it when the task is about provisioning, onboarding, routing, runtime health, or company-level orchestration across Maestro project agents.

## What The Commander Actively Does

- Provision a new project maestro with `maestro-fleet project create`
- Attach pre-ingested Maestro project data with existing-project onboarding semantics
- Route project-specific questions to the correct Maestro project agent
- Diagnose and repair runtime/routing issues with `maestro-fleet doctor --fix`
- Verify project readiness before claiming success

## What The Commander Does Not Do

- Do not use project knowledge tools directly from the Commander workspace
- Do not inspect plan/spec detail under `knowledge_store/` from the Commander workspace
- Do not impersonate a project Maestro in place of routing to the right node

## Primary Action Patterns

### Provision A New Maestro Project
Use when the user wants a brand-new project maestro and no existing Maestro project root is being supplied.

1. Confirm project identity and desired project slug
2. Confirm provider/model constraints if relevant
3. Run `maestro-fleet project create`
4. Verify workspace path, `MAESTRO_STORE`, page count, pointer count, and access URL before claiming success

### Attach Existing Maestro Data
Use when the user already has a Maestro project root or pre-ingested project store.

1. Confirm the supplied path is an existing Maestro project root (`project.json` + populated `pages/`)
2. Use existing-project onboarding semantics
3. Verify the project store landed in the correct Fleet location
4. Verify the project workspace resolves the expected store and URL

### Route To A Project Maestro
Use when the request depends on project-specific drawings/specs/workspace state.

1. Confirm the project slug / target agent exists
2. Dispatch to the correct `agent_id`
3. Summarize the project-maestro result back to the user

### Runtime Repair
Use when the user reports pairing, routing, URL, or gateway issues.

1. Run or advise `maestro-fleet doctor --fix`
2. Report exact PASS/FAIL status
3. Include the concrete next command when a check is not green

## Maestro Project Reference

When you need to understand how a Maestro project agent behaves, read:

- `references/maestro-project.md`

That file is **reference material**, not your active role contract.

## Completion Contract

- Do not say a project is ready until postconditions are verified
- Include the project slug, resolved store path, and workspace URL when relevant
- Include routing evidence when dispatching to another agent
