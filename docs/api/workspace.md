# Workspace APIs

Canonical Solo workspace surface:

- UI: `/workspace`
- WS: `/workspace/ws`
- API prefix: `/workspace/api/*`

Slug-scoped compatibility routes remain available:

- `/{slug}/api/*`

## Core Read APIs

1. `GET /workspace/api/project`
2. `GET /workspace/api/disciplines`
3. `GET /workspace/api/pages`
4. `GET /workspace/api/pages/{page_name}`
5. `GET /workspace/api/pages/{page_name}/regions`
6. `GET /workspace/api/workspaces`
7. `GET /workspace/api/workspaces/{ws_slug}`

## Project Notes APIs

1. `GET /workspace/api/project-notes`
2. `GET /{slug}/api/project-notes` (compat)

Response shape:

- `ok`, `project_slug`, `version`, `updated_at`
- `category_count`, `note_count`
- `categories[]`
- `notes[]`

WebSocket update event for note mutations:

- `project_notes_updated`

## Schedule APIs

1. `GET /workspace/api/schedule/status`
2. `GET /workspace/api/schedule/timeline`
3. `GET /workspace/api/schedule/items`
4. `POST /workspace/api/schedule/items/upsert`
5. `POST /workspace/api/schedule/constraints`
6. `POST /workspace/api/schedule/items/{item_id}/close`
