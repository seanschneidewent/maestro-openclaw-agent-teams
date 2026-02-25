---
name: maestro
description: Maestro native tools for project knowledge, workspace management, and project-wide schedule management.
---

# Maestro Native Tools

Use native `maestro_*` tools first. These tools are direct agent-facing functions, not shell wrappers.

## Execution Discipline (Critical)

1. Use `maestro_*` tools for all plan/workspace/schedule tasks.
2. Do not use browser/web tools for plan tasks when a `maestro_*` tool exists.
3. Do not inspect Maestro source files to discover runtime behavior during normal operation.
4. Do not run recursive scans across `knowledge_store/` (`grep -R`, `find`, dumping `pass1.json`/`pass2.json`).
5. Use shell tools only for bounded runtime diagnostics.
6. Never use `canvas` or `nodes` for plan highlighting/navigation.
7. Never guess bbox coordinates from memory or rough visual estimates.

## Core Native Tools

### Project + Knowledge
- `maestro_project_context`
- `maestro_get_access_urls`
- `maestro_list_pages`
- `maestro_search`
- `maestro_get_sheet_summary`
- `maestro_list_regions`
- `maestro_get_region_detail`
- `maestro_find_cross_references`

### Workspaces
- `maestro_list_workspaces`
- `maestro_get_workspace`
- `maestro_create_workspace`
- `maestro_add_page`
- `maestro_remove_page`
- `maestro_select_pointers`
- `maestro_deselect_pointers`
- `maestro_add_description`
- `maestro_set_custom_highlight`
- `maestro_clear_custom_highlights`

### Project Notes (Project-wide)
- `maestro_get_project_notes`
- `maestro_upsert_note_category`
- `maestro_add_note`
- `maestro_update_note_state`

### Schedule (Project-wide)
- `maestro_get_schedule_status`
- `maestro_get_schedule_timeline`
- `maestro_list_schedule_items`
- `maestro_upsert_schedule_item`
- `maestro_set_schedule_constraint`
- `maestro_close_schedule_item`

## Workflow Patterns

### Plan Question Workflow
1. `maestro_search` to find likely pages.
2. `maestro_get_sheet_summary` for sheet-level context.
3. `maestro_list_regions` and `maestro_get_region_detail` for precise answers.
4. Cite page and region IDs in your response.

### Workspace Build Workflow
1. `maestro_create_workspace`
2. `maestro_add_page`
3. `maestro_select_pointers` and/or `maestro_set_custom_highlight`
4. `maestro_add_description` for per-page "what matters on this sheet" memory
5. `maestro_get_access_urls` and share the recommended URL.

### Notes Workflow
1. Sheet-specific memory: use `maestro_add_description` on the target page.
2. Project-wide ideas: use `maestro_add_note` (optionally with `source_pages`).
3. Category management: use `maestro_upsert_note_category` then `maestro_add_note`.
4. For note lifecycle changes (archive/reopen/pin/unpin), use `maestro_update_note_state`.
5. If the user includes due date/owner/action, use schedule tools instead of notes.

### Row-Level Highlight Workflow (Required for "highlight this specific row")
1. `maestro_get_workspace` to confirm workspace + target page.
2. Use `image` tool on `knowledge_store/<project>/pages/<page_name>/page.png` to get an exact bbox for the requested row text.
3. Call `maestro_set_custom_highlight` with that exact bbox.
4. If image evidence is unavailable or ambiguous, do **not** write a guessed bbox. Ask a brief follow-up instead.

### Schedule Workflow
1. `maestro_get_schedule_status` or `maestro_get_schedule_timeline`
2. `maestro_upsert_schedule_item` / `maestro_set_schedule_constraint`
3. `maestro_close_schedule_item` when completed/cancelled

## When Plans Aren't Ingested Yet

If no project is available, instruct the user to run:

`maestro-solo ingest <path-to-pdfs>`

## Messaging Discipline

- One complete response per turn.
- Include what changed and what link to open when relevant.
