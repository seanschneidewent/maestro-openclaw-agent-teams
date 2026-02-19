"""Tests for maestro.utils — JSON parsing, bbox normalization, helpers."""

import json
import pytest
from pathlib import Path

from maestro.utils import (
    clean_json_string,
    parse_json,
    parse_json_list,
    normalize_bbox,
    bbox_to_region_id,
    bbox_valid,
    slugify,
    slugify_underscore,
    load_json,
    save_json,
)


# ── JSON Parsing ──────────────────────────────────────────────────────────────

class TestCleanJsonString:
    def test_trailing_comma_object(self):
        assert clean_json_string('{"a": 1,}') == '{"a": 1}'

    def test_trailing_comma_array(self):
        assert clean_json_string('[1, 2,]') == '[1, 2]'

    def test_no_trailing_comma(self):
        assert clean_json_string('{"a": 1}') == '{"a": 1}'

    def test_nested_trailing(self):
        assert clean_json_string('{"a": [1, 2,],}') == '{"a": [1, 2]}'


class TestParseJson:
    def test_direct_json(self):
        result = parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_code_block(self):
        text = 'Here is the result:\n```json\n{"key": "value"}\n```'
        assert parse_json(text) == {"key": "value"}

    def test_code_block_no_lang(self):
        text = '```\n{"key": 42}\n```'
        assert parse_json(text) == {"key": 42}

    def test_brace_extraction(self):
        text = 'Some text before {"key": "value"} and after'
        assert parse_json(text) == {"key": "value"}

    def test_empty_string(self):
        assert parse_json("") == {}

    def test_invalid_json(self):
        assert parse_json("not json at all") == {}

    def test_trailing_comma_in_block(self):
        text = '```json\n{"a": 1, "b": 2,}\n```'
        assert parse_json(text) == {"a": 1, "b": 2}

    def test_returns_dict_not_list(self):
        # parse_json should return dict, not list
        assert parse_json("[1, 2, 3]") == {}

    def test_nested_json(self):
        text = '{"regions": [{"id": "r1", "bbox": {"x0": 0}}]}'
        result = parse_json(text)
        assert result["regions"][0]["id"] == "r1"


class TestParseJsonList:
    def test_direct_list(self):
        result = parse_json_list('[{"a": 1}, {"a": 2}]')
        assert result == [{"a": 1}, {"a": 2}]

    def test_dict_with_key(self):
        result = parse_json_list('{"highlights": [{"label": "test"}]}', list_key="highlights")
        assert result == [{"label": "test"}]

    def test_code_block_list(self):
        text = '```json\n{"highlights": []}\n```'
        result = parse_json_list(text, list_key="highlights")
        assert result == []

    def test_empty_returns_none(self):
        assert parse_json_list("") is None

    def test_no_match_returns_none(self):
        assert parse_json_list("no json here", list_key="items") is None

    def test_bracket_extraction(self):
        text = 'Found these: [1, 2, 3] in the response'
        assert parse_json_list(text) == [1, 2, 3]


# ── Bbox Normalization ────────────────────────────────────────────────────────

class TestNormalizeBbox:
    def test_gemini_native_format(self):
        # [ymin, xmin, ymax, xmax] → {x0, y0, x1, y1}
        result = normalize_bbox([100, 50, 400, 300])
        assert result == {"x0": 50, "y0": 100, "x1": 300, "y1": 400}

    def test_legacy_dict_format(self):
        result = normalize_bbox({"x0": 10, "y0": 20, "x1": 100, "y1": 200})
        assert result == {"x0": 10, "y0": 20, "x1": 100, "y1": 200}

    def test_clamping(self):
        result = normalize_bbox([-10, -20, 1100, 1200])
        assert result["x0"] >= 0
        assert result["y0"] >= 0
        assert result["x1"] <= 1000
        assert result["y1"] <= 1000

    def test_zero_width_fix(self):
        result = normalize_bbox([100, 100, 100, 100])
        assert result["x1"] > result["x0"]
        assert result["y1"] > result["y0"]

    def test_invalid_input(self):
        result = normalize_bbox("garbage")
        assert result == {"x0": 0, "y0": 0, "x1": 1000, "y1": 1000}

    def test_none_input(self):
        result = normalize_bbox(None)
        assert result == {"x0": 0, "y0": 0, "x1": 1000, "y1": 1000}

    def test_float_values(self):
        result = normalize_bbox([100.5, 50.7, 400.9, 300.2])
        assert all(isinstance(v, int) for v in result.values())

    def test_short_list(self):
        result = normalize_bbox([100, 50])
        assert result == {"x0": 0, "y0": 0, "x1": 1000, "y1": 1000}


class TestBboxHelpers:
    def test_region_id(self):
        bbox = {"x0": 50, "y0": 100, "x1": 300, "y1": 400}
        assert bbox_to_region_id(bbox) == "r_50_100_300_400"

    def test_bbox_valid_true(self):
        assert bbox_valid({"x0": 0, "y0": 0, "x1": 100, "y1": 100})

    def test_bbox_valid_false_zero_area(self):
        assert not bbox_valid({"x0": 100, "y0": 100, "x1": 100, "y1": 100})

    def test_bbox_valid_none(self):
        assert not bbox_valid(None)


# ── Slugify ───────────────────────────────────────────────────────────────────

class TestSlugify:
    def test_basic(self):
        assert slugify("My Project Name") == "my-project-name"

    def test_special_chars(self):
        assert slugify("Chick-fil-A Love Field FSU 03904 -CPS") == "chick-fil-a-love-field-fsu-03904-cps"

    def test_empty(self):
        assert slugify("") == "default"

    def test_underscore_slug(self):
        assert slugify_underscore("Refuse Enclosure") == "refuse_enclosure"

    def test_underscore_empty(self):
        assert slugify_underscore("") == "workspace"


# ── File Helpers ──────────────────────────────────────────────────────────────

class TestFileHelpers:
    def test_load_json_missing(self, tmp_path):
        assert load_json(tmp_path / "missing.json") == {}

    def test_load_json_default(self, tmp_path):
        assert load_json(tmp_path / "missing.json", default=[]) == []

    def test_save_and_load_json(self, tmp_path):
        data = {"key": "value", "number": 42}
        path = tmp_path / "sub" / "test.json"
        save_json(path, data)
        assert load_json(path) == data

    def test_load_json_invalid(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json!", encoding="utf-8")
        assert load_json(bad) == {}
