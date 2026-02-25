from __future__ import annotations

import json
from pathlib import Path

from maestro_engine.server_workspace_data import load_project_notes


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_load_project_notes_defaults_to_general_category(tmp_path: Path):
    proj = {"path": str(tmp_path)}
    payload = load_project_notes(proj)

    assert payload["version"] == 1
    assert payload["notes"] == []
    assert payload["categories"]
    assert payload["categories"][0]["id"] == "general"


def test_load_project_notes_normalizes_note_payload(tmp_path: Path):
    _write_json(
        tmp_path / "notes" / "project_notes.json",
        {
            "version": 1,
            "updated_at": "2026-02-25T05:36:28.291Z",
            "categories": [
                {"id": "General", "name": "General", "color": "slate", "order": 0},
                {"id": "Field", "name": "Field", "color": "blue", "order": 10},
            ],
            "notes": [
                {
                    "id": "andy-inspection-note",
                    "text": "Spoke with Andy about two-stage pour.",
                    "category_id": "Field",
                    "source_pages": [
                        {"page_name": "VC_05_Header_and_Venting_Pipe_Cross_Section_p001"},
                        {"page_name": "VC_05_Header_and_Venting_Pipe_Cross_Section_p001"},
                        "S1_1_Foundation_Plan_p001",
                    ],
                    "status": "invalid_status",
                    "pinned": "true",
                }
            ],
        },
    )

    proj = {"path": str(tmp_path)}
    payload = load_project_notes(proj)

    assert len(payload["notes"]) == 1
    note = payload["notes"][0]
    assert note["id"] == "andy_inspection_note"
    assert note["category_id"] == "field"
    assert note["status"] == "open"
    assert note["pinned"] is True
    assert len(note["source_pages"]) == 2
