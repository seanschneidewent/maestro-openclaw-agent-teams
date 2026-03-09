# Maestro Project Agent Reference

This file explains how a **Maestro project agent** behaves so The Commander can provision, onboard, and route work correctly.

## What A Maestro Project Agent Is

A Maestro project agent is a project-scoped OpenClaw agent with:

- a project workspace
- a project `MAESTRO_STORE`
- the Maestro project skill bundle
- Maestro-native tools for project knowledge, workspaces, notes, and schedule

## What A Maestro Project Agent Actively Does

- Answer project-specific drawing/spec/detail questions
- Manage workspace pages, highlights, and descriptions
- Manage project-wide notes
- Manage project-wide schedule state
- Return project-specific links and access URLs

## What The Commander Should Provide When Routing

- target project slug / `agent_id`
- exact user question
- any important company-level context
- whether the request is informational, mutating, or verification-oriented

## What The Commander Should Provide When Onboarding Data

- project identity (name + slug)
- source path classification
- whether the path is:
  - an existing Maestro project root
  - a multi-project store root
  - a raw PDF/input folder

## Success Criteria For A Project Maestro

The Commander should consider a project maestro ready only when:

- the project workspace exists
- `MAESTRO_STORE` resolves to the intended project root
- the project store contains expected data
- the workspace URL resolves correctly
- the project agent is present in OpenClaw config

## Boundary Reminder

The Commander should understand these capabilities, but should not perform project knowledge work from the Commander workspace directly.
