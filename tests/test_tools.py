"""Tests for maestro.tools — MaestroTools query engine."""

import json
import pytest
from pathlib import Path

from maestro.tools import MaestroTools


@pytest.fixture
def mock_store(tmp_path):
    """Create a minimal knowledge store for testing."""
    project_dir = tmp_path / "Test Project"
    project_dir.mkdir()

    (project_dir / "project.json").write_text(json.dumps({
        "name": "Test Project",
        "total_pages": 2,
    }), encoding="utf-8")

    (project_dir / "index.json").write_text(json.dumps({
        "materials": {
            "brick veneer": [{"page": "A101_Floor_Plan_p001"}],
            "concrete": [{"page": "S101_Foundation_p001"}],
        },
        "keywords": {
            "waterproofing": [{"page": "A101_Floor_Plan_p001"}],
            "rebar": [{"page": "S101_Foundation_p001"}],
        },
        "modifications": [
            {"action": "install", "item": "new door", "note": "", "source": {"page": "A101_Floor_Plan_p001"}},
        ],
        "cross_refs": {"S101": ["A101_Floor_Plan_p001"]},
        "broken_refs": ["X999"],
        "pages": {},
        "summary": {"page_count": 2, "pointer_count": 1},
    }), encoding="utf-8")

    pages_dir = project_dir / "pages"

    a101 = pages_dir / "A101_Floor_Plan_p001"
    a101.mkdir(parents=True)
    (a101 / "pass1.json").write_text(json.dumps({
        "page_type": "floor_plan",
        "discipline": "architectural",
        "sheet_reflection": "## A101: Floor Plan\n\nMain floor plan with waterproofing details.",
        "index": {"keywords": ["floor", "plan", "waterproofing"], "materials": ["brick veneer"]},
        "cross_references": ["S101"],
        "regions": [
            {
                "id": "r_100_200_300_400",
                "type": "detail",
                "label": "MAIN ENTRY",
                "bbox": {"x0": 100, "y0": 200, "x1": 300, "y1": 400},
            }
        ],
    }), encoding="utf-8")

    ptr_dir = a101 / "pointers" / "r_100_200_300_400"
    ptr_dir.mkdir(parents=True)
    (ptr_dir / "pass2.json").write_text(json.dumps({
        "content_markdown": "Main entry with brick veneer and waterproofing membrane.",
        "materials": ["brick veneer", "waterproofing membrane"],
    }), encoding="utf-8")

    s101 = pages_dir / "S101_Foundation_p001"
    s101.mkdir(parents=True)
    (s101 / "pass1.json").write_text(json.dumps({
        "page_type": "detail_sheet",
        "discipline": "structural",
        "sheet_reflection": "## S101: Foundation Plan",
        "index": {"keywords": ["foundation", "rebar"], "materials": ["concrete"]},
        "regions": [],
        "cross_references": [],
    }), encoding="utf-8")

    # Workspaces dir
    (project_dir / "workspaces").mkdir()

    return tmp_path


@pytest.fixture
def tools(mock_store):
    return MaestroTools(store_path=mock_store)


class TestKnowledgeQueries:
    def test_list_disciplines(self, tools):
        result = tools.list_disciplines()
        assert "architectural" in result or "Architectural" in result

    def test_list_pages(self, tools):
        pages = tools.list_pages()
        assert len(pages) == 2
        names = [p["name"] for p in pages]
        assert "A101_Floor_Plan_p001" in names

    def test_list_pages_filtered(self, tools):
        pages = tools.list_pages(discipline="architectural")
        assert len(pages) == 1
        assert pages[0]["name"] == "A101_Floor_Plan_p001"

    def test_get_sheet_summary(self, tools):
        result = tools.get_sheet_summary("A101")
        assert "Floor Plan" in result

    def test_get_sheet_summary_not_found(self, tools):
        result = tools.get_sheet_summary("ZZZZZ")
        assert "not found" in result.lower()

    def test_get_sheet_index(self, tools):
        result = tools.get_sheet_index("A101")
        assert isinstance(result, dict)
        assert "keywords" in result

    def test_list_regions(self, tools):
        result = tools.list_regions("A101")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["label"] == "MAIN ENTRY"

    def test_get_region_detail(self, tools):
        result = tools.get_region_detail("A101_Floor_Plan_p001", "r_100_200_300_400")
        assert "brick veneer" in result

    def test_get_region_detail_not_found(self, tools):
        result = tools.get_region_detail("A101", "nonexistent")
        assert "not found" in result.lower()

    def test_search_material(self, tools):
        results = tools.search("brick")
        assert isinstance(results, list)
        assert len(results) > 0
        assert any(r["type"] == "material" for r in results)

    def test_search_keyword(self, tools):
        results = tools.search("waterproofing")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_search_in_content(self, tools):
        results = tools.search("membrane")
        assert isinstance(results, list)
        assert any(r["type"] == "pointer" for r in results)

    def test_search_no_results(self, tools):
        result = tools.search("xyznonexistent")
        assert isinstance(result, str)
        assert "No results" in result

    def test_find_cross_references(self, tools):
        result = tools.find_cross_references("A101_Floor_Plan_p001")
        assert isinstance(result, dict)
        assert "S101" in result["references_from_this_page"]

    def test_list_modifications(self, tools):
        result = tools.list_modifications()
        assert len(result) == 1
        assert result[0]["item"] == "new door"

    def test_check_gaps(self, tools):
        result = tools.check_gaps()
        assert isinstance(result, list)
        assert any(g["type"] == "broken_ref" for g in result)


class TestWorkspaces:
    def test_create_workspace(self, tools):
        result = tools.create_workspace("Test WS", "A test workspace")
        assert result["status"] == "created"
        assert result["slug"] == "test_ws"

    def test_create_workspace_duplicate(self, tools):
        tools.create_workspace("Test WS", "First")
        result = tools.create_workspace("Test WS", "Second")
        assert isinstance(result, str)
        assert "already exists" in result

    def test_list_workspaces(self, tools):
        tools.create_workspace("WS1", "First workspace")
        result = tools.list_workspaces()
        assert len(result) == 1
        assert result[0]["slug"] == "ws1"

    def test_add_page_to_workspace(self, tools):
        tools.create_workspace("Test", "Test workspace")
        result = tools.add_workspace_page("test", "A101")
        assert result["status"] == "added"

    def test_add_page_not_found(self, tools):
        tools.create_workspace("Test", "Test workspace")
        result = tools.add_workspace_page("test", "NONEXISTENT")
        assert "not found" in result.lower()

    def test_select_pointers(self, tools):
        tools.create_workspace("Test", "Test workspace")
        tools.add_workspace_page("test", "A101")
        result = tools.select_pointers("test", "A101_Floor_Plan_p001", ["r_100_200_300_400"])
        assert result["status"] == "selected"

    def test_add_note(self, tools):
        tools.create_workspace("Test", "Test workspace")
        result = tools.add_note("test", "Check waterproofing at entry", source_page="A101")
        assert result["status"] == "added"

    def test_remove_page(self, tools):
        tools.create_workspace("Test", "Test workspace")
        tools.add_workspace_page("test", "A101")
        result = tools.remove_workspace_page("test", "A101_Floor_Plan_p001")
        assert result["status"] == "removed"
