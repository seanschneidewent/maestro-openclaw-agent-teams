"""
Maestro Ingest — Build a knowledge_store from construction plan PDFs.

Two-pass Gemini vision pipeline:
  Pass 1: Sheet-level analysis — regions, details, cross-references, disciplines
  Pass 2: Deep dive on every region — materials, dimensions, specs, coordination

Usage (CLI):
    maestro ingest <path-to-pdf-folder> [--project-name "My Project"] [--dpi 200]

Usage (Python):
    from maestro.ingest import ingest
    ingest("/path/to/pdfs", project_name="My Project")
"""

from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from google import genai
from google.genai import types

from .config import (
    DEFAULT_DPI,
    DEFAULT_THINKING_LEVEL,
    INGEST_MODEL,
    get_gemini_api_key,
    get_store_path,
    load_dotenv,
)
from .prompts import PASS1_PROMPT, PASS2_PROMPT
from .utils import (
    bbox_to_region_id,
    collect_response,
    crop_region,
    load_json,
    normalize_bbox,
    parse_json,
    save_json,
)
from .index import build_index


# ── Gemini Client ─────────────────────────────────────────────────────────────

def _client() -> genai.Client:
    key = get_gemini_api_key()
    if not key:
        print("ERROR: Set GEMINI_API_KEY in .env or environment.")
        sys.exit(1)
    return genai.Client(api_key=key)


# ── PDF Helpers ───────────────────────────────────────────────────────────────

def discover_pdfs(folder: Path) -> list[dict]:
    """Find all PDFs in a folder and return metadata about each."""
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
            "discipline": infer_discipline(pdf),
        })
    return result


def infer_discipline(path: Path) -> str:
    """Infer construction discipline from PDF filename/path."""
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


def render_page(pdf_path: str, page_num: int, output: Path, dpi: int = DEFAULT_DPI) -> tuple[int, int]:
    """Render a PDF page to PNG. Returns (width, height)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        pix.save(str(output))
        return pix.width, pix.height


def page_name(pdf_path: str, page_num: int) -> str:
    """Generate a filesystem-safe page name from PDF path and page number."""
    stem = Path(pdf_path).stem
    safe = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_") or "page"
    return f"{safe}_p{page_num + 1:03d}"


# ── Save Trace Images ─────────────────────────────────────────────────────────

def save_trace(trace: list[dict], images: list[bytes], directory: Path, prefix: str = "trace"):
    """Save trace images to disk and update trace entries with file paths."""
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
    """Run Pass 1 analysis: sheet-level overview with region detection."""
    prompt = f"{PASS1_PROMPT}\n\nPAGE NAME: {pg_name}\nDISCIPLINE: {discipline}"

    start = time.perf_counter()
    response = client.models.generate_content(
        model=INGEST_MODEL,
        contents=[types.Content(parts=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            types.Part.from_text(text=prompt),
        ])],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level=DEFAULT_THINKING_LEVEL),
            tools=[types.Tool(code_execution=types.ToolCodeExecution)],
        ),
    )
    elapsed = int((time.perf_counter() - start) * 1000)

    text, images, trace = collect_response(response)
    parsed = parse_json(text)

    raw_regions = parsed.get("regions", [])
    if not isinstance(raw_regions, list):
        raw_regions = []

    regions = []
    for r in raw_regions:
        if not isinstance(r, dict):
            continue
        raw_box = r.pop("box_2d", None) or r.get("bbox", {})
        r["bbox"] = normalize_bbox(raw_box)
        r["id"] = bbox_to_region_id(r["bbox"])
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
    """Run Pass 2 analysis: deep technical extraction on a cropped region."""
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
        kt = "\n".join(
            f"- {k.get('number', '?')}: {k.get('text', '')}"
            for k in keynotes if isinstance(k, dict)
        )
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
        model=INGEST_MODEL,
        contents=[types.Content(parts=[
            types.Part.from_bytes(data=crop_bytes, mime_type="image/png"),
            types.Part.from_text(text=prompt),
        ])],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level=DEFAULT_THINKING_LEVEL),
            tools=[types.Tool(code_execution=types.ToolCodeExecution)],
        ),
    )
    elapsed = int((time.perf_counter() - start) * 1000)

    text, images, trace = collect_response(response)
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


# ── Main Ingest ───────────────────────────────────────────────────────────────

def ingest(
    folder_path: str,
    project_name: str | None = None,
    dpi: int = DEFAULT_DPI,
    store_path: str | Path | None = None,
):
    """
    Ingest construction plan PDFs into a knowledge store.

    Args:
        folder_path: Path to folder containing PDFs
        project_name: Project name (defaults to folder name)
        dpi: Render DPI for page images (default: 200)
        store_path: Override path for knowledge_store output
    """
    load_dotenv()

    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        print(f"ERROR: Folder not found: {folder}")
        sys.exit(1)

    name = project_name or folder.name
    store = Path(store_path) if store_path else get_store_path()
    project_dir = store / name
    project_dir.mkdir(parents=True, exist_ok=True)

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

            page_dir = project_dir / "pages" / pn

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
                p1 = {
                    "page_name": pn, "page_type": "unknown", "discipline": pdf["discipline"],
                    "regions": [], "sheet_reflection": "", "index": {}, "cross_references": [],
                    "sheet_info": {}, "processing_time_ms": 0, "_images": [], "_trace": [],
                }

            regions = p1.get("regions", [])
            images = p1.pop("_images", [])
            save_trace(p1.get("_trace", []), images, page_dir, prefix="pass1_img")

            save_json(page_dir / "pass1.json", p1)
            print(f"{len(regions)} regions ({p1.get('processing_time_ms', 0)}ms)")

            # Render PNG for crops and storage
            print(f"[{counter}/{total}] Rendering PNG...", end=" ", flush=True)
            w, h = render_page(pdf["path"], pg, page_dir / "page.png", dpi=dpi)
            print(f"{w}x{h}")

            # Pass 2 for each region
            for i, region in enumerate(regions):
                rid = region.get("id", f"region_{i:03d}")
                ptr_dir = page_dir / "pointers" / rid
                ptr_dir.mkdir(parents=True, exist_ok=True)

                crop_region(page_dir / "page.png", region["bbox"], ptr_dir / "crop.png")

                label = region.get("label", rid)
                print(f"  Pass 2 [{i + 1}/{len(regions)}] {label}...", end=" ", flush=True)
                try:
                    p2 = run_pass2(client, ptr_dir / "crop.png", region, p1)
                except Exception as e:
                    print(f"ERROR: {e}")
                    p2 = {
                        "content_markdown": "", "materials": [], "dimensions": [],
                        "processing_time_ms": 0, "_trace": [], "_trace_images": [],
                    }

                p2_images = p2.pop("_trace_images", [])
                save_trace(p2.get("_trace", []), p2_images, ptr_dir, prefix="trace_p2")

                save_json(ptr_dir / "pass2.json", p2)
                print(f"done ({p2.get('processing_time_ms', 0)}ms)")

    # Build index
    print("\nBuilding index...", end=" ", flush=True)
    idx = build_index(project_dir)
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
    save_json(project_dir / "project.json", meta)

    # License stamping
    license_key = get_gemini_api_key()  # Will use environment var MAESTRO_LICENSE_KEY
    import os
    license_key = os.environ.get("MAESTRO_LICENSE_KEY")
    if license_key and license_key.startswith("MAESTRO-PROJECT-"):
        print("\nStamping knowledge store with license...", end=" ", flush=True)
        try:
            from .license import stamp_knowledge_store
            from .utils import slugify_underscore
            project_slug = slugify_underscore(name)
            stamp_knowledge_store(str(project_dir), license_key, project_slug)
            print("done")
        except Exception as e:
            print(f"warning: {e}")
    elif license_key:
        print(f"\n⚠️  License key found but not a project license (starts with: {license_key[:20]}...)")
        print(f"   Knowledge store not stamped. Use a project license for full functionality.")
    else:
        print(f"\n⚠️  No MAESTRO_LICENSE_KEY found in environment")
        print(f"   Knowledge store not stamped with license.")
        print(f"   Set a valid project license to enable tools.")

    s = idx["summary"]
    print(f"\n{'=' * 60}")
    print(f"  Done! {s['page_count']} pages, {s['pointer_count']} pointers")
    print(f"  {s['unique_material_count']} materials, {s['unique_keyword_count']} keywords")
    print(f"  Output: {project_dir}")
    print(f"{'=' * 60}\n")


# ── CLI Entry Point ───────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Maestro Ingest — Build knowledge_store from construction PDFs")
    parser.add_argument("folder", help="Path to folder containing PDFs")
    parser.add_argument("--project-name", "-n", help="Project name (defaults to folder name)")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"Render DPI (default: {DEFAULT_DPI})")
    parser.add_argument("--store", help="Override knowledge_store path")
    args = parser.parse_args()

    ingest(args.folder, args.project_name, args.dpi, args.store)


if __name__ == "__main__":
    main()
