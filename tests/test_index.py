"""Tests for maestro.index — project index builder."""

import json
import pytest
from pathlib import Path

from maestro.index import build_index


@pytest.fixture
def mock_project(tmp_path):
    """Create a minimal project directory for index building."""
    pages_dir = tmp_path / "pages"

    # Page with regions and pointers
    a101 = pages_dir / "A101_Floor_Plan_p001"
    a101.mkdir(parents=True)
    (a101 / "pass1.json").write_text(json.dumps({
        "discipline": "architectural",
        "page_type": "floor_plan",
        "index": {
            "keywords": ["floor plan", "entry", "waterproofing"],
            "materials": ["brick veneer", "aluminum storefront"],
            "keynotes": [{"number": "1", "text": "See spec section 07 1300"}],
        },
        "cross_references": ["S101", "A201"],
        "regions": [
            {"id": "r_100_200_300_400", "type": "detail", "label": "ENTRY"},
        ],
    }), encoding="utf-8")

    ptr = a101 / "pointers" / "r_100_200_300_400"
    ptr.mkdir(parents=True)
    (ptr / "pass2.json").write_text(json.dumps({
        "materials": ["brick veneer", "mortar"],
        "keynotes_referenced": ["1"],
        "specifications": ["07 1300"],
        "cross_references": [{"sheet": "A201", "context": "elevation"}],
        "modifications": [
            {"action": "install", "item": "new threshold", "note": "per RFI #3"},
        ],
    }), encoding="utf-8")

    # Page without pointers
    s101 = pages_dir / "S101_Foundation_p001"
    s101.mkdir(parents=True)
    (s101 / "pass1.json").write_text(json.dumps({
        "discipline": "structural",
        "page_type": "detail_sheet",
        "index": {
            "keywords": ["foundation", "rebar"],
            "materials": ["concrete", "#5 rebar"],
        },
        "cross_references": ["A101"],
        "regions": [],
    }), encoding="utf-8")

    return tmp_path


class TestBuildIndex:
    def test_builds_successfully(self, mock_project):
        idx = build_index(mock_project)
        assert idx is not None
        assert "summary" in idx

    def test_page_count(self, mock_project):
        idx = build_index(mock_project)
        assert idx["summary"]["page_count"] == 2

    def test_pointer_count(self, mock_project):
        idx = build_index(mock_project)
        assert idx["summary"]["pointer_count"] == 1

    def test_materials_indexed(self, mock_project):
        idx = build_index(mock_project)
        assert "brick veneer" in idx["materials"]
        assert "concrete" in idx["materials"]
        assert "mortar" in idx["materials"]  # From pass2

    def test_keywords_indexed(self, mock_project):
        idx = build_index(mock_project)
        assert "floor plan" in idx["keywords"]
        assert "foundation" in idx["keywords"]

    def test_cross_refs(self, mock_project):
        idx = build_index(mock_project)
        assert "S101" in idx["cross_refs"]
        assert "A101_Floor_Plan_p001" in idx["cross_refs"]["S101"]

    def test_broken_refs(self, mock_project):
        idx = build_index(mock_project)
        # A201 is referenced but doesn't exist as a page dir
        assert "A201" in idx["broken_refs"]

    def test_modifications(self, mock_project):
        idx = build_index(mock_project)
        assert len(idx["modifications"]) == 1
        assert idx["modifications"][0]["item"] == "new threshold"

    def test_writes_index_file(self, mock_project):
        build_index(mock_project)
        assert (mock_project / "index.json").exists()

    def test_empty_project(self, tmp_path):
        idx = build_index(tmp_path)
        assert idx["summary"]["page_count"] == 0
