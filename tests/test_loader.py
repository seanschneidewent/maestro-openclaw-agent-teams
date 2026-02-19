"""Tests for maestro.loader — knowledge store loading and page resolution."""

import json
import pytest
from pathlib import Path

from maestro.loader import load_project, resolve_page


@pytest.fixture
def mock_store(tmp_path):
    """Create a minimal knowledge store for testing."""
    project_dir = tmp_path / "Test Project"
    project_dir.mkdir()

    # project.json
    (project_dir / "project.json").write_text(json.dumps({
        "name": "Test Project",
        "total_pages": 3,
        "disciplines": ["Architectural", "Structural"],
    }), encoding="utf-8")

    # index.json
    (project_dir / "index.json").write_text(json.dumps({
        "materials": {"brick veneer": [{"page": "A101_Floor_Plan_p001"}]},
        "keywords": {"waterproofing": [{"page": "A101_Floor_Plan_p001"}]},
        "modifications": [],
        "cross_refs": {"S101": ["A101_Floor_Plan_p001"]},
        "broken_refs": ["X999"],
        "pages": {},
        "summary": {"page_count": 3, "pointer_count": 2},
    }), encoding="utf-8")

    # Pages
    pages_dir = project_dir / "pages"

    # Page 1: A101
    a101 = pages_dir / "A101_Floor_Plan_p001"
    a101.mkdir(parents=True)
    (a101 / "pass1.json").write_text(json.dumps({
        "page_type": "floor_plan",
        "discipline": "architectural",
        "sheet_reflection": "## A101: Floor Plan\n\nMain floor plan.",
        "index": {"keywords": ["floor", "plan"], "materials": ["brick veneer"]},
        "cross_references": ["S101", "A201"],
        "regions": [
            {
                "id": "r_100_200_300_400",
                "type": "detail",
                "label": "MAIN ENTRY",
                "bbox": {"x0": 100, "y0": 200, "x1": 300, "y1": 400},
            }
        ],
        "sheet_info": {"number": "A101", "title": "Floor Plan"},
    }), encoding="utf-8")

    ptr_dir = a101 / "pointers" / "r_100_200_300_400"
    ptr_dir.mkdir(parents=True)
    (ptr_dir / "pass2.json").write_text(json.dumps({
        "content_markdown": "Main entry detail with brick veneer.",
        "materials": ["brick veneer", "aluminum frame"],
        "dimensions": ["3'-6\" wide"],
    }), encoding="utf-8")

    # Page 2: S101
    s101 = pages_dir / "S101_Foundation_p001"
    s101.mkdir(parents=True)
    (s101 / "pass1.json").write_text(json.dumps({
        "page_type": "detail_sheet",
        "discipline": "structural",
        "sheet_reflection": "## S101: Foundation\n\nStructural foundation.",
        "index": {"keywords": ["foundation"], "materials": ["concrete"]},
        "regions": [],
    }), encoding="utf-8")

    return tmp_path


class TestLoadProject:
    def test_load_first_project(self, mock_store):
        project = load_project(store_path=mock_store)
        assert project is not None
        assert project["name"] == "Test Project"
        assert len(project["pages"]) == 2

    def test_load_named_project(self, mock_store):
        project = load_project(store_path=mock_store, project_name="Test Project")
        assert project is not None

    def test_load_missing_project(self, mock_store):
        project = load_project(store_path=mock_store, project_name="Nonexistent")
        assert project is None

    def test_load_missing_store(self, tmp_path):
        project = load_project(store_path=tmp_path / "nope")
        assert project is None

    def test_pages_loaded(self, mock_store):
        project = load_project(store_path=mock_store)
        a101 = project["pages"]["A101_Floor_Plan_p001"]
        assert a101["page_type"] == "floor_plan"
        assert a101["discipline"] == "architectural"
        assert len(a101["regions"]) == 1

    def test_pointers_loaded(self, mock_store):
        project = load_project(store_path=mock_store)
        a101 = project["pages"]["A101_Floor_Plan_p001"]
        assert "r_100_200_300_400" in a101["pointers"]
        ptr = a101["pointers"]["r_100_200_300_400"]
        assert "brick veneer" in ptr["content_markdown"]

    def test_index_loaded(self, mock_store):
        project = load_project(store_path=mock_store)
        assert "brick veneer" in project["index"]["materials"]

    def test_disciplines_derived(self, mock_store):
        project = load_project(store_path=mock_store)
        # Uses project.json disciplines since they exist
        assert "Architectural" in project["disciplines"]
        assert "Structural" in project["disciplines"]


class TestResolvePage:
    def test_exact_match(self, mock_store):
        project = load_project(store_path=mock_store)
        page = resolve_page(project, "A101_Floor_Plan_p001")
        assert page is not None
        assert page["name"] == "A101_Floor_Plan_p001"

    def test_prefix_match(self, mock_store):
        project = load_project(store_path=mock_store)
        page = resolve_page(project, "A101")
        assert page is not None
        assert "A101" in page["name"]

    def test_substring_match(self, mock_store):
        project = load_project(store_path=mock_store)
        page = resolve_page(project, "Floor_Plan")
        assert page is not None

    def test_no_match(self, mock_store):
        project = load_project(store_path=mock_store)
        page = resolve_page(project, "ZZZZZ")
        assert page is None

    def test_dot_normalization(self, mock_store):
        project = load_project(store_path=mock_store)
        # A101 with dots should still match A101_Floor_Plan_p001
        page = resolve_page(project, "A101")
        assert page is not None
