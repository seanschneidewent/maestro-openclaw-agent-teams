"""
Maestro Ingest CLI — Build a knowledge_store from construction plan PDFs.

Usage:
    python ingest.py <path-to-pdf-folder> [--project-name "My Project"] [--dpi 200]

Outputs:
    knowledge_store/<project_name>/
        project.json
        index.json
        pages/<page_name>/
            page.png
            pass1.json
            pointers/<region_id>/
                crop.png
                pass2.json
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

MODEL = "gemini-3-flash-preview"
THINKING = "high"
MAX_GEMINI_BYTES = 9 * 1024 * 1024  # 9 MB safety margin

PASS1_PROMPT = """\
You are analyzing a construction drawing for a superintendent. Your job: DEEPLY COMPREHEND this sheet and make it searchable.

## YOUR OUTPUT

### 1. Regions (with bounding boxes)
Map every distinct area on the sheet:
- Details (numbered: 1, 2, 3... or 1/A401)
- Schedules, legends, notes sections
- Title block, revision block
- Plan areas, sections, elevations

For each region:
- id, type, box_2d [ymin, xmin, ymax, xmax] normalized to 0-1000
- label (the title shown)
- detail_number if applicable
- confidence
- shows (short description)
- region_index (structured hints for search)

### 2. Sheet Reflection (superintendent briefing)
Write a structured markdown summary. Use this format:

```
## [Sheet Number]: [Sheet Title]

[One paragraph overview - what type of sheet, what it covers, key purpose]

**Key Details:**
- **Detail [#] - [Name]:** [What it shows, key specs]
- **Detail [#] - [Name]:** [What it shows, key specs]
...

**Materials & Specs:**
- [Material 1 with spec]
- [Material 2 with spec]

**Coordination Notes:**
- [Cross-reference or coordination point]
- [Another coordination point]
```

Be specific. Name the details. Include actual specs and dimensions when visible.

### 3. Index (for search/retrieval)
Structured data for RAG queries:
- **keywords**: Every searchable term (materials, equipment, actions, detail names)
- **items**: Significant elements [{name, action, location, detail_number}]
- **keynotes**: If present [{number, text}]
- **materials**: Specific materials called out
- **cross_refs**: Sheet references with context [{sheet, context}]

## RETURN JSON

```json
{
  "page_type": "detail_sheet or floor_plan or schedule or section or elevation or notes or cover or rcp",
  "discipline": "architectural or structural or mechanical or electrical or plumbing or civil",
  "sheet_info": {"number": "A401", "title": "Architectural Details"},

  "regions": [
    {
      "id": "region_001",
      "type": "detail",
      "detail_number": "1",
      "label": "DRIVE-THRU SILL DETAIL",
      "box_2d": [100, 50, 400, 300],
      "confidence": 0.95,
      "shows": "Tormax door sill with air curtain integration",
      "region_index": {}
    }
  ],

  "sheet_reflection": "## A401: Architectural Details\\n\\n...",

  "index": {
    "keywords": ["drive-thru", "Tormax", "sill"],
    "items": [{"name": "Tormax automated door", "detail_number": "1,2,3", "location": "drive-thru"}],
    "materials": ["brick veneer", "aluminum storefront"],
    "keynotes": [],
    "cross_refs": [{"sheet": "A1.3", "context": "walk-up window location"}]
  },

  "cross_references": ["A1.3", "S-101"],

  "questions_this_sheet_answers": [
    "What is the sill detail at the drive-thru?",
    "What flashing is specified at window heads?"
  ]
}
```

## GUIDELINES

- Count details carefully. If you see 8 detail bubbles, create 8 regions.
- Bounding boxes should fully contain each region (title + content)
- Sheet reflection MUST use markdown headers (##) and bold (**) formatting
- Index keywords should be comprehensive - think "what would someone search for?"
- Materials list should include specific products/specs when visible
"""

PASS2_PROMPT = """\
You are analyzing a cropped construction-plan region for deep technical extraction.

Context:
- Sheet Number: {sheet_number}
- Sheet Title: {sheet_title}
- Discipline: {discipline}
- Region Type: {region_type}
- Region Label: {region_label}
- {detail_number_line}

Sheet Reflection:
{sheet_reflection}

Prior Region Notes:
{region_index_text}

Known Keynotes:
{keynotes_text}

Known Cross References:
{cross_refs_text}

Task:
- extract every readable technical detail from this crop,
- produce a superintendent-useful technical brief,
- include uncertain or ambiguous readings explicitly.

Return one JSON object with the following keys:
- content_markdown: detailed markdown technical brief
- materials: list
- dimensions: list
- keynotes_referenced: list
- specifications: list
- cross_references: list
- coordination_notes: list
- questions_answered: list
- assembly: list
- connections: list
- areas: list
- equipment: list
- modifications: list
- keynotes: list
- schedule_type: string
- columns: list
- rows: list
- note_categories: list

Quality bar:
- do not invent data not visible in the crop.
- separate observed facts from assumptions.
- include units when dimensions are visible.
"""


# ── Gemini Client ─────────────────────────────────────────────────────────────

def _client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("ERROR: Set GEMINI_API_KEY in .env or environment.")
        sys.exit(1)
    return genai.Client(api_key=key)


# ── JSON Parsing ──────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s).strip()


def parse_json(text: str) -> dict:
    """Extract a JSON object from Gemini's text output."""
    if not text:
        return {}
    s = text.strip()

    # Direct parse
    try:
        p = json.loads(s)
        if isinstance(p, dict):
            return p
    except json.JSONDecodeError:
        pass

    # Code block
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)\n?```", s, re.DOTALL | re.IGNORECASE):
        try:
            p = json.loads(_clean(m.group(1)))
            if isinstance(p, dict):
                return p
        except json.JSONDecodeError:
            continue

    # Brace match
    start = s.find("{")
    end = s.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(_clean(s[start:end]))
        except json.JSONDecodeError:
            pass

    return {}


# ── Response Collector ────────────────────────────────────────────────────────

def collect(response) -> tuple[str, list[bytes], list[dict]]:
    """Collect text, images, and trace from a Gemini response."""
    text_parts: list[str] = []
    images: list[bytes] = []
    trace: list[dict] = []

    candidates = getattr(response, "candidates", []) or []
    if not candidates:
        return "", images, trace

    parts = getattr(getattr(candidates[0], "content", None), "parts", []) or []
    for part in parts:
        if getattr(part, "thought", None):
            trace.append({"type": "thought", "content": getattr(part, "text", "")})
            continue
        if (t := getattr(part, "text", None)) is not None:
            text_parts.append(t)
            trace.append({"type": "text", "content": t})
        if (code := getattr(part, "executable_code", None)) is not None:
            trace.append({"type": "code", "content": getattr(code, "code", "")})
        if (cr := getattr(part, "code_execution_result", None)) is not None:
            trace.append({"type": "code_result", "content": getattr(cr, "output", "") or ""})
        try:
            img = part.as_image()
            if img and img.image_bytes:
                images.append(bytes(img.image_bytes))
                trace.append({"type": "image", "index": len(images) - 1})
        except Exception:
            pass

    return "\n".join(text_parts), images, trace


# ── PDF Helpers ───────────────────────────────────────────────────────────────

def discover_pdfs(folder: Path) -> list[dict]:
    pdfs = sorted(folder.rglob("*.pdf"), key=lambda p: p.as_posix().lower())
    result = []
    for pdf in pdfs:
        try:
            with fitz.open(str(pdf)) as doc:
                count = doc.page_count
        except Exception as e:
            print(f"  [WARN] Skipping {pdf.name}: {e}")
            continue
        if count <= 0:
            continue
        result.append({
            "path": str(pdf),
            "name": pdf.name,
            "page_count": count,
            "discipline": _infer_discipline(pdf),
        })
    return result


def _infer_discipline(path: Path) -> str:
    h = f"{path.as_posix()} {path.stem}".lower()
    if "architectural" in h or "arch" in h or re.search(r"(^|[^a-z])a\d{2,4}([^a-z]|$)", h) or "a-" in h:
        return "Architectural"
    if any(x in h for x in ("mep", "mechanical", "electrical", "plumbing", "hvac", "fire protection")):
        return "MEP"
    if re.search(r"(^|[^a-z])(m|e|p|fp)\d{2,4}([^a-z]|$)", h):
        return "MEP"
    if any(x in h for x in ("m-", "e-", "p-", "fp-")):
        return "MEP"
    if "structural" in h or "struct" in h or re.search(r"(^|[^a-z])s\d{2,4}([^a-z]|$)", h) or "s-" in h:
        return "Structural"
    return "General"


def render_page(pdf_path: str, page_num: int, output: Path, dpi: int = 200) -> tuple[int, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        pix.save(str(output))
        return pix.width, pix.height


def page_name(pdf_path: str, page_num: int) -> str:
    stem = Path(pdf_path).stem
    safe = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_") or "page"
    return f"{safe}_p{page_num + 1:03d}"


def resize_for_gemini(png_path: Path) -> Path:
    if png_path.stat().st_size <= MAX_GEMINI_BYTES:
        return png_path
    resized = png_path.with_name("page_pass1.png")
    img = Image.open(png_path)
    w, h = img.size
    img.resize((w // 2, h // 2), Image.LANCZOS).save(resized, "PNG")
    if resized.stat().st_size > MAX_GEMINI_BYTES:
        img2 = Image.open(resized)
        w2, h2 = img2.size
        img2.resize((w2 // 2, h2 // 2), Image.LANCZOS).save(resized, "PNG")
    return resized


# ── Bbox / Crop Helpers ───────────────────────────────────────────────────────

def _int(v, default=0) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def normalize_bbox(raw) -> dict:
    """Convert Gemini's box_2d [ymin, xmin, ymax, xmax] or legacy {x0,y0,x1,y1} to {x0,y0,x1,y1}."""
    if isinstance(raw, list) and len(raw) >= 4:
        # Gemini native: [ymin, xmin, ymax, xmax]
        ymin, xmin, ymax, xmax = _int(raw[0]), _int(raw[1]), _int(raw[2]), _int(raw[3])
        x0, y0, x1, y1 = xmin, ymin, xmax, ymax
    elif isinstance(raw, dict):
        # Legacy format: {x0, y0, x1, y1}
        x0, y0 = _int(raw.get("x0")), _int(raw.get("y0"))
        x1, y1 = _int(raw.get("x1"), 1000), _int(raw.get("y1"), 1000)
    else:
        return {"x0": 0, "y0": 0, "x1": 1000, "y1": 1000}
    x0, y0 = max(0, min(1000, x0)), max(0, min(1000, y0))
    x1, y1 = max(0, min(1000, x1)), max(0, min(1000, y1))
    if x1 <= x0:
        x1 = min(1000, x0 + 1)
    if y1 <= y0:
        y1 = min(1000, y0 + 1)
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def region_id(bbox: dict) -> str:
    return f"r_{bbox['x0']}_{bbox['y0']}_{bbox['x1']}_{bbox['y1']}"


def crop_region(image_path: Path, bbox: dict, output_path: Path, padding: int = 20):
    img = Image.open(image_path)
    w, h = img.size
    x0 = max(0, int((bbox["x0"] / 1000) * w) - padding)
    y0 = max(0, int((bbox["y0"] / 1000) * h) - padding)
    x1 = min(w, int((bbox["x1"] / 1000) * w) + padding)
    y1 = min(h, int((bbox["y1"] / 1000) * h) + padding)
    if x1 <= x0:
        x1 = min(w, x0 + 1)
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.crop((x0, y0, x1, y1)).save(str(output_path))


# ── Save Trace Images ─────────────────────────────────────────────────────────

def save_trace(trace: list[dict], images: list[bytes], directory: Path, prefix: str = "trace"):
    directory.mkdir(parents=True, exist_ok=True)
    for entry in trace:
        if entry.get("type") == "image" and "index" in entry:
            idx = entry.pop("index")
            if isinstance(idx, int) and 0 <= idx < len(images):
                fname = f"{prefix}_{idx}.png"
                (directory / fname).write_bytes(images[idx])
                entry["path"] = fname
            else:
                entry["path"] = None


# ── Pass 1 ────────────────────────────────────────────────────────────────────

def run_pass1(client: genai.Client, pdf_bytes: bytes, pg_name: str, discipline: str) -> dict:
    prompt = f"{PASS1_PROMPT}\n\nPAGE NAME: {pg_name}\nDISCIPLINE: {discipline}"

    start = time.perf_counter()
    response = client.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            types.Part.from_text(text=prompt),
        ])],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level=THINKING),
            tools=[types.Tool(code_execution=types.ToolCodeExecution)],
        ),
    )
    elapsed = int((time.perf_counter() - start) * 1000)

    text, images, trace = collect(response)
    parsed = parse_json(text)

    raw_regions = parsed.get("regions", [])
    if not isinstance(raw_regions, list):
        raw_regions = []

    regions = []
    for i, r in enumerate(raw_regions):
        if not isinstance(r, dict):
            continue
        # Accept box_2d (Gemini native) or bbox (legacy)
        raw_box = r.pop("box_2d", None) or r.get("bbox", {})
        r["bbox"] = normalize_bbox(raw_box)
        r["id"] = region_id(r["bbox"])
        r.setdefault("type", "unknown")
        r.setdefault("label", "")
        r.setdefault("confidence", 0.0)
        regions.append(r)

    return {
        "page_name": pg_name,
        "page_type": parsed.get("page_type", "unknown"),
        "discipline": parsed.get("discipline", discipline),
        "regions": regions,
        "sheet_reflection": parsed.get("sheet_reflection", ""),
        "index": parsed.get("index", {}),
        "cross_references": parsed.get("cross_references", []),
        "sheet_info": parsed.get("sheet_info", {}),
        "processing_time_ms": elapsed,
        "_images": images,
        "_trace": trace,
    }


# ── Pass 2 ────────────────────────────────────────────────────────────────────

def run_pass2(client: genai.Client, crop_path: Path, region: dict, pass1: dict) -> dict:
    sheet_info = pass1.get("sheet_info", {}) or {}
    index = pass1.get("index", {}) or {}

    # Region index text
    ri = region.get("region_index", {})
    ri_lines = []
    if isinstance(ri, dict):
        for k, v in ri.items():
            if v:
                ri_lines.append(f"{k}: {v}")
    if not ri_lines:
        ri_lines.append(str(region.get("shows", "No prior analysis")))

    # Keynotes text
    keynotes = index.get("keynotes", [])
    if isinstance(keynotes, list) and keynotes:
        kt = "\n".join(f"- {k.get('number', '?')}: {k.get('text', '')}" for k in keynotes if isinstance(k, dict))
    else:
        kt = "None found"

    # Cross refs text
    xrefs = pass1.get("cross_references", [])
    xrt = ", ".join(str(x) for x in xrefs) if isinstance(xrefs, list) and xrefs else "None"

    prompt = PASS2_PROMPT.format(
        sheet_number=sheet_info.get("number", pass1.get("page_name", "Unknown")),
        sheet_title=sheet_info.get("title", ""),
        discipline=pass1.get("discipline", ""),
        region_type=region.get("type", "unknown"),
        region_label=region.get("label", ""),
        detail_number_line=f"Detail Number: {region['detail_number']}" if region.get("detail_number") else "",
        sheet_reflection=pass1.get("sheet_reflection", ""),
        region_index_text="\n".join(ri_lines),
        keynotes_text=kt,
        cross_refs_text=xrt,
    )

    crop_bytes = crop_path.read_bytes()
    start = time.perf_counter()

    response = client.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=[
            types.Part.from_bytes(data=crop_bytes, mime_type="image/png"),
            types.Part.from_text(text=prompt),
        ])],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level=THINKING),
            tools=[types.Tool(code_execution=types.ToolCodeExecution)],
        ),
    )
    elapsed = int((time.perf_counter() - start) * 1000)

    text, images, trace = collect(response)
    parsed = parse_json(text)

    return {
        "content_markdown": parsed.get("content_markdown", text),
        "materials": parsed.get("materials", []),
        "dimensions": parsed.get("dimensions", []),
        "keynotes_referenced": parsed.get("keynotes_referenced", []),
        "specifications": parsed.get("specifications", []),
        "cross_references": parsed.get("cross_references", []),
        "coordination_notes": parsed.get("coordination_notes", []),
        "questions_answered": parsed.get("questions_answered", []),
        "assembly": parsed.get("assembly", []),
        "connections": parsed.get("connections", []),
        "areas": parsed.get("areas", []),
        "equipment": parsed.get("equipment", []),
        "modifications": parsed.get("modifications", []),
        "keynotes": parsed.get("keynotes", []),
        "schedule_type": parsed.get("schedule_type", ""),
        "columns": parsed.get("columns", []),
        "rows": parsed.get("rows", []),
        "note_categories": parsed.get("note_categories", []),
        "processing_time_ms": elapsed,
        "_trace": trace,
        "_trace_images": images,
    }


# ── Index Builder ─────────────────────────────────────────────────────────────

def _flatten_strings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(k, str) and k.strip():
                out.append(k.strip())
            out.extend(_flatten_strings(v))
        return out
    return []


def _add_term(bucket: dict, term: str, source: dict):
    t = term.strip()
    if not t:
        return
    bucket.setdefault(t, [])
    if source not in bucket[t]:
        bucket[t].append(source)


_SHEET_RE = re.compile(r"\b[A-Z]{1,3}-?\d{2,4}(?:\.\d+)?\b")


def _extract_refs(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        m = _SHEET_RE.findall(value.upper())
        return m if m else ([value.strip()] if value.strip() else [])
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_extract_refs(item))
        return out
    if isinstance(value, dict):
        for k in ("sheet", "sheet_number", "target", "page", "ref", "to"):
            if k in value:
                return _extract_refs(value[k])
        out = []
        for v in value.values():
            out.extend(_extract_refs(v))
        return out
    return []


def build_index(project_dir: Path) -> dict:
    pages_dir = project_dir / "pages"
    idx = {
        "materials": {},
        "keywords": {},
        "modifications": [],
        "cross_refs": {},
        "broken_refs": [],
        "pages": {},
        "summary": {"page_count": 0, "pointer_count": 0, "unique_material_count": 0,
                     "unique_keyword_count": 0, "modification_count": 0, "broken_ref_count": 0},
    }
    if not pages_dir.exists():
        return idx

    page_dirs = sorted([d for d in pages_dir.iterdir() if d.is_dir()], key=lambda p: p.name.lower())
    page_names = {d.name for d in page_dirs}

    for pd in page_dirs:
        pn = pd.name
        p1 = _load_json(pd / "pass1.json")
        pi = p1.get("index", {}) if isinstance(p1.get("index"), dict) else {}
        regions = p1.get("regions", []) if isinstance(p1.get("regions"), list) else []

        page_info = {
            "discipline": p1.get("discipline", "General"),
            "page_type": p1.get("page_type", "unknown"),
            "region_count": len(regions),
            "pointer_count": 0,
        }
        idx["pages"][pn] = page_info

        for mat in _flatten_strings(pi.get("materials", [])):
            _add_term(idx["materials"], mat, {"page": pn})
        for kw in _flatten_strings(pi.get("keywords", [])):
            _add_term(idx["keywords"], kw, {"page": pn})
        for ref in _extract_refs(p1.get("cross_references", [])):
            idx["cross_refs"].setdefault(ref, [])
            if pn not in idx["cross_refs"][ref]:
                idx["cross_refs"][ref].append(pn)

        ptrs_dir = pd / "pointers"
        ptr_dirs = sorted([d for d in ptrs_dir.iterdir() if d.is_dir()], key=lambda p: p.name) if ptrs_dir.exists() else []
        page_info["pointer_count"] = len(ptr_dirs)

        for ptr_dir in ptr_dirs:
            rid = ptr_dir.name
            p2 = _load_json(ptr_dir / "pass2.json")
            src = {"page": pn, "region_id": rid}

            for mat in _flatten_strings(p2.get("materials", [])):
                _add_term(idx["materials"], mat, src)
            for field in (p2.get("keynotes_referenced", []), p2.get("keynotes", []), p2.get("specifications", [])):
                for kw in _flatten_strings(field):
                    _add_term(idx["keywords"], kw, src)
            for ref in _extract_refs(p2.get("cross_references", [])):
                idx["cross_refs"].setdefault(ref, [])
                if pn not in idx["cross_refs"][ref]:
                    idx["cross_refs"][ref].append(pn)
            for mod in (p2.get("modifications", []) if isinstance(p2.get("modifications"), list) else []):
                if isinstance(mod, dict):
                    entry = {"action": str(mod.get("action", "")), "item": str(mod.get("item", "")),
                             "note": str(mod.get("note", "")), "source": src}
                elif isinstance(mod, str) and mod.strip():
                    entry = {"action": "", "item": mod.strip(), "note": "", "source": src}
                else:
                    continue
                if entry not in idx["modifications"]:
                    idx["modifications"].append(entry)

    idx["broken_refs"] = sorted(t for t in idx["cross_refs"] if t not in page_names)
    s = idx["summary"]
    s["page_count"] = len(page_names)
    s["pointer_count"] = sum(p["pointer_count"] for p in idx["pages"].values())
    s["unique_material_count"] = len(idx["materials"])
    s["unique_keyword_count"] = len(idx["keywords"])
    s["modification_count"] = len(idx["modifications"])
    s["broken_ref_count"] = len(idx["broken_refs"])

    with (project_dir / "index.json").open("w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2)
    return idx


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Main Ingest ───────────────────────────────────────────────────────────────

def ingest(folder_path: str, project_name: str | None = None, dpi: int = 200):
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        print(f"ERROR: Folder not found: {folder}")
        sys.exit(1)

    name = project_name or folder.name
    store = Path("knowledge_store") / name
    store.mkdir(parents=True, exist_ok=True)

    pdfs = discover_pdfs(folder)
    if not pdfs:
        print(f"No PDFs found in {folder}")
        return

    total = sum(p["page_count"] for p in pdfs)
    client = _client()
    counter = 0
    seen: set[str] = set()

    print(f"\n{'=' * 60}")
    print(f"  Maestro Ingest — {name}")
    print(f"  {len(pdfs)} PDFs, {total} pages")
    print(f"{'=' * 60}\n")

    for pdf in pdfs:
        for pg in range(pdf["page_count"]):
            counter += 1
            pn = page_name(pdf["path"], pg)
            # Deduplicate names
            base = pn
            suffix = 2
            while pn in seen:
                pn = f"{base}_dup{suffix}"
                suffix += 1
            seen.add(pn)

            page_dir = store / "pages" / pn

            # Resume: skip completed pages
            if (page_dir / "pass1.json").exists():
                ptrs = page_dir / "pointers"
                if ptrs.exists() and any(ptrs.iterdir()):
                    print(f"[{counter}/{total}] Skipping {pn} (done)")
                    continue

            # Clean partial work
            if page_dir.exists():
                shutil.rmtree(page_dir)
            page_dir.mkdir(parents=True, exist_ok=True)

            # Extract single page as PDF bytes for Gemini
            print(f"[{counter}/{total}] Pass 1 {pn} (PDF direct)...", end=" ", flush=True)
            with fitz.open(pdf["path"]) as doc:
                single = fitz.open()
                single.insert_pdf(doc, from_page=pg, to_page=pg)
                pdf_bytes = single.tobytes()
                single.close()

            try:
                p1 = run_pass1(client, pdf_bytes, pn, pdf["discipline"])
            except Exception as e:
                print(f"\n  [ERROR] Pass 1 failed: {e}")
                p1 = {"page_name": pn, "page_type": "unknown", "discipline": pdf["discipline"],
                       "regions": [], "sheet_reflection": "", "index": {}, "cross_references": [],
                       "sheet_info": {}, "processing_time_ms": 0, "_images": [], "_trace": []}

            regions = p1.get("regions", [])
            images = p1.pop("_images", [])
            save_trace(p1.get("_trace", []), images, page_dir, prefix="pass1_img")

            with (page_dir / "pass1.json").open("w", encoding="utf-8") as f:
                json.dump(p1, f, indent=2)

            print(f"{len(regions)} regions ({p1.get('processing_time_ms', 0)}ms)")

            # Render PNG now (after Pass 1) for crops and storage
            print(f"[{counter}/{total}] Rendering PNG...", end=" ", flush=True)
            w, h = render_page(pdf["path"], pg, page_dir / "page.png", dpi=dpi)
            print(f"{w}x{h}")

            # Pass 2 for each region
            for i, region in enumerate(regions):
                rid = region.get("id", f"region_{i:03d}")
                ptr_dir = page_dir / "pointers" / rid
                ptr_dir.mkdir(parents=True, exist_ok=True)

                # Crop using PIL from bbox
                crop_region(page_dir / "page.png", region["bbox"], ptr_dir / "crop.png")

                label = region.get("label", rid)
                print(f"  Pass 2 [{i + 1}/{len(regions)}] {label}...", end=" ", flush=True)
                try:
                    p2 = run_pass2(client, ptr_dir / "crop.png", region, p1)
                except Exception as e:
                    print(f"ERROR: {e}")
                    p2 = {"content_markdown": "", "materials": [], "dimensions": [],
                           "processing_time_ms": 0, "_trace": [], "_trace_images": []}

                p2_images = p2.pop("_trace_images", [])
                save_trace(p2.get("_trace", []), p2_images, ptr_dir, prefix="trace_p2")

                with (ptr_dir / "pass2.json").open("w", encoding="utf-8") as f:
                    json.dump(p2, f, indent=2)

                print(f"done ({p2.get('processing_time_ms', 0)}ms)")

    # Build index
    print("\nBuilding index...", end=" ", flush=True)
    idx = build_index(store)
    print("done")

    # Project metadata
    meta = {
        "name": name,
        "source_path": str(folder),
        "total_pages": total,
        "disciplines": sorted(set(p["discipline"] for p in pdfs)),
        "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "index_summary": idx.get("summary", {}),
    }
    with (store / "project.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    s = idx["summary"]
    print(f"\n{'=' * 60}")
    print(f"  Done! {s['page_count']} pages, {s['pointer_count']} pointers")
    print(f"  {s['unique_material_count']} materials, {s['unique_keyword_count']} keywords")
    print(f"  Output: {store}")
    print(f"{'=' * 60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Maestro Ingest — Build knowledge_store from construction PDFs")
    parser.add_argument("folder", help="Path to folder containing PDFs")
    parser.add_argument("--project-name", "-n", help="Project name (defaults to folder name)")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    args = parser.parse_args()

    ingest(args.folder, args.project_name, args.dpi)
