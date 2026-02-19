"""
Maestro Knowledge Tools — query engine for ingested construction plans.

Provides search, sheet summaries, region details, cross-references,
workspace management, Gemini highlighting, and image generation.

Usage (CLI):
    maestro tools <command> [args]

Usage (Python):
    from maestro.tools import MaestroTools
    tools = MaestroTools(store_path="knowledge_store")
    results = tools.search("waterproofing")
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    HIGHLIGHT_MODEL,
    IMAGE_GEN_MODEL,
    get_store_path,
    load_dotenv,
)
from .loader import load_project, resolve_page
from .prompts import HIGHLIGHT_PROMPT
from .utils import (
    collect_text_only,
    load_json,
    normalize_bbox,
    parse_json_list,
    save_json,
    slugify_underscore,
)


class MaestroTools:
    """
    Stateful tool interface for querying a Maestro knowledge store.

    Loads a project once and provides all query/workspace/highlight methods.
    """

    def __init__(
        self,
        store_path: str | Path | None = None,
        project_name: str | None = None,
        workspace_root: Path | None = None,
    ):
        self._store_path = Path(store_path) if store_path else get_store_path()
        self._project_name = project_name
        self._workspace_root = workspace_root
        self._project: dict[str, Any] | None = None

    @property
    def project(self) -> dict[str, Any]:
        if self._project is None:
            self._project = load_project(
                store_path=self._store_path,
                project_name=self._project_name,
            )
            if self._project is None:
                raise RuntimeError("No project loaded. Run: maestro ingest <folder>")
        return self._project

    def _resolve_page(self, page_name: str) -> dict[str, Any] | None:
        return resolve_page(self.project, page_name)

    # ── Knowledge Queries ─────────────────────────────────────────────────────

    def list_disciplines(self) -> list[str]:
        return self.project.get("disciplines", [])

    def list_pages(self, discipline: str | None = None) -> list[dict[str, Any]]:
        pages = []
        for name, page in self.project.get("pages", {}).items():
            page_disc = str(page.get("discipline", ""))
            if discipline and page_disc.lower() != discipline.lower():
                continue
            pages.append({
                "name": name,
                "type": page.get("page_type", "unknown"),
                "discipline": page_disc,
                "region_count": len(page.get("regions", [])),
            })
        return sorted(pages, key=lambda p: p["name"].lower())

    def get_sheet_summary(self, page_name: str) -> str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found. Use list_pages to see available pages."
        return page.get("sheet_reflection", "No summary available")

    def get_sheet_index(self, page_name: str) -> dict[str, Any] | str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        return page.get("index", {})

    def list_regions(self, page_name: str) -> list[dict[str, Any]] | str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        pointers = page.get("pointers", {})
        return [{
            "id": r.get("id", ""),
            "type": r.get("type"),
            "label": r.get("label"),
            "detail_number": r.get("detail_number"),
            "has_pass2": bool(r.get("id") and r.get("id") in pointers),
        } for r in page.get("regions", []) if isinstance(r, dict)]

    def get_region_detail(self, page_name: str, region_id: str) -> str:
        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        pointer = page.get("pointers", {}).get(region_id)
        if not pointer:
            return f"Region '{region_id}' not found on '{page.get('name', page_name)}'."
        return pointer.get("content_markdown", "No detail available")

    def search(self, query: str) -> list[dict[str, Any]] | str:
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        idx = self.project.get("index", {})

        if isinstance(idx, dict):
            for material, sources in idx.get("materials", {}).items():
                if query_lower in str(material).lower():
                    results.append({"type": "material", "match": material, "found_in": sources})
            for keyword, sources in idx.get("keywords", {}).items():
                if query_lower in str(keyword).lower():
                    results.append({"type": "keyword", "match": keyword, "found_in": sources})

        for page_name, page in self.project.get("pages", {}).items():
            if query_lower in str(page.get("sheet_reflection", "")).lower():
                results.append({"type": "page", "match": page_name, "context": "sheet_reflection"})
            for pointer_id, pointer in page.get("pointers", {}).items():
                if query_lower in str(pointer.get("content_markdown", "")).lower():
                    results.append({"type": "pointer", "match": f"{page_name}/{pointer_id}", "context": "content_markdown"})

        return results if results else f"No results for '{query}'"

    def find_cross_references(self, page_name: str) -> dict[str, Any] | str:
        page = self.project.get("pages", {}).get(page_name)
        if not page:
            return f"Page '{page_name}' not found."
        idx = self.project.get("index", {})
        cross_refs = idx.get("cross_refs", {}) if isinstance(idx, dict) else {}
        return {
            "references_from_this_page": page.get("cross_references", []),
            "pages_that_reference_this": cross_refs.get(page_name, []),
        }

    def list_modifications(self) -> list[dict[str, Any]]:
        idx = self.project.get("index", {})
        return idx.get("modifications", []) if isinstance(idx, dict) else []

    def check_gaps(self) -> list[dict[str, Any]] | str:
        gaps: list[dict[str, Any]] = []
        idx = self.project.get("index", {})
        if isinstance(idx, dict):
            for ref in idx.get("broken_refs", []):
                gaps.append({"type": "broken_ref", "detail": ref})
        for page_name, page in self.project.get("pages", {}).items():
            pointers = page.get("pointers", {})
            for region in page.get("regions", []):
                if not isinstance(region, dict):
                    continue
                rid = region.get("id", "")
                if rid and rid not in pointers:
                    gaps.append({
                        "type": "missing_pass2",
                        "page": page_name,
                        "region": rid,
                        "label": region.get("label", ""),
                    })
        return gaps if gaps else "No gaps found"

    # ── Workspace Management ──────────────────────────────────────────────────

    def _workspaces_dir(self) -> Path:
        project_path = self.project.get("_dir")
        if project_path:
            ws_dir = Path(project_path) / "workspaces"
        else:
            ws_dir = self._store_path / self.project.get("name", "default") / "workspaces"
        ws_dir.mkdir(exist_ok=True)
        return ws_dir

    def _load_workspace(self, slug: str) -> dict[str, Any] | None:
        ws_path = self._workspaces_dir() / slug / "workspace.json"
        return load_json(ws_path) if ws_path.exists() else None

    def _save_workspace(self, ws: dict[str, Any]):
        slug = ws["slug"]
        ws_dir = self._workspaces_dir() / slug
        ws_dir.mkdir(exist_ok=True)
        save_json(ws_dir / "workspace.json", ws)

    def _all_workspaces(self) -> list[dict[str, Any]]:
        ws_dir = self._workspaces_dir()
        workspaces = []
        for d in sorted(ws_dir.iterdir()):
            if d.is_dir():
                ws = self._load_workspace(d.name)
                if ws:
                    workspaces.append(ws)
        return workspaces

    def _save_index(self):
        workspaces = self._all_workspaces()
        index = [{
            "slug": ws["slug"],
            "title": ws.get("title", ""),
            "description": ws.get("description", ""),
            "page_count": len(ws.get("pages", [])),
            "note_count": len(ws.get("notes", [])),
        } for ws in workspaces]
        save_json(self._workspaces_dir() / "_index.json", index)

    def create_workspace(self, title: str, description: str) -> dict[str, Any] | str:
        if not title.strip():
            return "Workspace title is required."
        if not description.strip():
            return "Workspace description is required."

        slug = slugify_underscore(title)
        if self._load_workspace(slug):
            return f"Workspace '{slug}' already exists."

        ws = {
            "slug": slug,
            "title": title.strip(),
            "description": description.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pages": [],
            "notes": [],
        }
        self._save_workspace(ws)
        self._save_index()
        return {"status": "created", "slug": slug, "title": ws["title"]}

    def list_workspaces(self) -> list[dict[str, Any]]:
        return [{
            "slug": ws["slug"],
            "title": ws.get("title", ""),
            "description": ws.get("description", ""),
            "page_count": len(ws.get("pages", [])),
            "note_count": len(ws.get("notes", [])),
        } for ws in self._all_workspaces()]

    def get_workspace(self, slug: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."
        return ws

    def add_workspace_page(self, slug: str, page_name: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found in knowledge store."
        resolved_name = page.get("name", page_name)

        for p in ws.get("pages", []):
            if p.get("page_name") == resolved_name:
                return f"Page '{resolved_name}' is already in workspace '{slug}'."

        ws.setdefault("pages", []).append({
            "page_name": resolved_name,
            "description": "",
            "selected_pointers": [],
            "highlights": [],
        })
        self._save_workspace(ws)
        self._save_index()
        return {"status": "added", "workspace": slug, "page": resolved_name}

    def remove_workspace_page(self, slug: str, page_name: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        pages = ws.get("pages", [])
        new_pages = [p for p in pages if p.get("page_name") != page_name]
        if len(new_pages) == len(pages):
            return f"Page '{page_name}' is not in workspace '{slug}'."

        ws["pages"] = new_pages
        self._save_workspace(ws)
        self._save_index()
        return {"status": "removed", "workspace": slug, "page": page_name}

    def select_pointers(self, slug: str, page_name: str, pointer_ids: list[str]) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        target_page = None
        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                target_page = p
                break

        if not target_page:
            page_data = self._resolve_page(page_name)
            if page_data:
                resolved_name = page_data.get("name", page_name)
                for p in ws.get("pages", []):
                    if p.get("page_name") == resolved_name:
                        target_page = p
                        page_name = resolved_name
                        break

        if not target_page:
            return f"Page '{page_name}' is not in workspace '{slug}'. Add it first with add_page."

        ks_page = self.project.get("pages", {}).get(page_name, {})
        valid_ids = {r.get("id") for r in ks_page.get("regions", []) if isinstance(r, dict)}

        invalid = [pid for pid in pointer_ids if pid not in valid_ids]
        if invalid:
            return f"Invalid pointer IDs: {invalid}. Use list_regions to see available pointers."

        existing = set(target_page.get("selected_pointers", []))
        existing.update(pointer_ids)
        target_page["selected_pointers"] = sorted(existing)

        self._save_workspace(ws)
        return {
            "status": "selected",
            "workspace": slug,
            "page": page_name,
            "selected_pointers": target_page["selected_pointers"],
        }

    def deselect_pointers(self, slug: str, page_name: str, pointer_ids: list[str]) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        target_page = None
        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                target_page = p
                break

        if not target_page:
            return f"Page '{page_name}' is not in workspace '{slug}'."

        existing = set(target_page.get("selected_pointers", []))
        existing -= set(pointer_ids)
        target_page["selected_pointers"] = sorted(existing)

        self._save_workspace(ws)
        return {
            "status": "deselected",
            "workspace": slug,
            "page": page_name,
            "selected_pointers": target_page["selected_pointers"],
        }

    def add_note(self, slug: str, text: str, source_page: str | None = None) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."
        if not text.strip():
            return "Note text is required."

        note = {
            "text": text.strip(),
            "source_page": source_page,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ws.setdefault("notes", []).append(note)
        self._save_workspace(ws)
        return {"status": "added", "workspace": slug, "note": note}

    def add_page_description(self, slug: str, page_name: str, description: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                p["description"] = description.strip()
                self._save_workspace(ws)
                return {"status": "updated", "workspace": slug, "page": page_name}

        return f"Page '{page_name}' is not in workspace '{slug}'."

    # ── Highlight (Gemini Vision) ─────────────────────────────────────────────

    def highlight(self, slug: str, page_name: str, query: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        page = self._resolve_page(page_name)
        if not page:
            return f"Page '{page_name}' not found in knowledge store."
        resolved_name = page.get("name", page_name)

        page_path = page.get("path")
        if not page_path:
            return f"No path found for page '{resolved_name}'."
        png_path = Path(page_path) / "page.png"
        if not png_path.exists():
            return f"No PNG found at {png_path}."

        # Ensure page is in workspace
        ws_page = None
        for p in ws.get("pages", []):
            if p.get("page_name") == resolved_name:
                ws_page = p
                break
        if not ws_page:
            ws.setdefault("pages", []).append({
                "page_name": resolved_name,
                "description": "",
                "selected_pointers": [],
                "custom_highlights": [],
            })
            ws_page = ws["pages"][-1]

        if self._workspace_root:
            load_dotenv(self._workspace_root)
        else:
            load_dotenv()

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "GEMINI_API_KEY not set. Set it in .env or environment."

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        png_bytes = png_path.read_bytes()
        prompt = HIGHLIGHT_PROMPT.format(query=query)

        response = client.models.generate_content(
            model=HIGHLIGHT_MODEL,
            contents=[types.Content(parts=[
                types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
                types.Part.from_text(text=prompt),
            ])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
                tools=[types.Tool(code_execution=types.ToolCodeExecution)],
            ),
        )

        raw = collect_text_only(response)
        if not raw:
            return "Empty response from Gemini."

        highlights = parse_json_list(raw, list_key="highlights")
        if highlights is None:
            return f"Failed to parse Gemini response: {raw[:500]}"

        custom_highlights = []
        for h in highlights:
            raw_box = h.get("box_2d") or h.get("bbox", [])
            bbox = normalize_bbox(raw_box)
            if bbox["x1"] <= bbox["x0"] or bbox["y1"] <= bbox["y0"]:
                continue
            custom_highlights.append({
                "label": h.get("label", ""),
                "bbox": bbox,
                "query": query,
                "confidence": h.get("confidence", 0.0),
            })

        ws_page.setdefault("custom_highlights", []).extend(custom_highlights)
        self._save_workspace(ws)
        self._save_index()

        return {
            "status": "highlighted",
            "workspace": slug,
            "page": resolved_name,
            "highlights_added": len(custom_highlights),
            "total_highlights": len(ws_page.get("custom_highlights", [])),
            "labels": [h["label"] for h in custom_highlights],
        }

    def clear_highlights(self, slug: str, page_name: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        for p in ws.get("pages", []):
            if p.get("page_name") == page_name:
                p["custom_highlights"] = []
                self._save_workspace(ws)
                return {"status": "cleared", "workspace": slug, "page": page_name}

        return f"Page '{page_name}' is not in workspace '{slug}'."

    # ── Image Generation ──────────────────────────────────────────────────────

    def generate_image(
        self,
        slug: str,
        prompt: str,
        reference_pages: list[str] | None = None,
        reference_image_path: str | None = None,
        aspect_ratio: str = "1:1",
        image_size: str = "2K",
    ) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        if self._workspace_root:
            load_dotenv(self._workspace_root)
        else:
            load_dotenv()

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "GEMINI_API_KEY not set. Set it in .env or environment."

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        parts = []

        for pn in (reference_pages or []):
            page = self._resolve_page(pn)
            if page:
                png_path = Path(page["path"]) / "page.png"
                if png_path.exists():
                    parts.append(types.Part.from_bytes(
                        data=png_path.read_bytes(), mime_type="image/png"
                    ))

        if reference_image_path:
            ref_path = Path(reference_image_path)
            if ref_path.exists():
                suffix = ref_path.suffix.lower()
                mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
                parts.append(types.Part.from_bytes(data=ref_path.read_bytes(), mime_type=mime))
            else:
                return f"Reference image not found: {reference_image_path}"

        parts.append(types.Part.from_text(text=prompt))

        try:
            response = client.models.generate_content(
                model=IMAGE_GEN_MODEL,
                contents=[types.Content(parts=parts)],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                    ),
                ),
            )
        except Exception as e:
            return f"Gemini API error: {e}"

        image_data = None
        description_parts = []
        candidates = getattr(response, "candidates", []) or []
        for candidate in candidates:
            content_parts = getattr(getattr(candidate, "content", None), "parts", []) or []
            for part in content_parts:
                if getattr(part, "text", None):
                    description_parts.append(part.text)
                elif getattr(part, "inline_data", None):
                    image_data = part.inline_data.data

        if not image_data:
            desc = " ".join(description_parts).strip()
            return f"No image generated. Response: {desc[:500]}" if desc else "No image generated — empty response."

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        image_filename = f"gen_{timestamp}.png"

        img_dir = self._workspaces_dir() / slug / "generated_images"
        img_dir.mkdir(parents=True, exist_ok=True)
        image_path = img_dir / image_filename

        if isinstance(image_data, (bytes, bytearray)):
            image_path.write_bytes(image_data)
        else:
            import base64
            image_path.write_bytes(base64.b64decode(image_data))

        description = " ".join(description_parts).strip()
        gen_entry = {
            "type": "generated",
            "filename": image_filename,
            "prompt": prompt,
            "reference_pages": reference_pages or [],
            "description": description,
            "aspect_ratio": aspect_ratio,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ws.setdefault("generated_images", []).append(gen_entry)
        self._save_workspace(ws)
        self._save_index()

        return {
            "status": "generated",
            "workspace": slug,
            "filename": image_filename,
            "description": description,
            "total_generated": len(ws.get("generated_images", [])),
        }

    def delete_image(self, slug: str, filename: str) -> dict[str, Any] | str:
        ws = self._load_workspace(slug)
        if not ws:
            return f"Workspace '{slug}' not found."

        images = ws.get("generated_images", [])
        found = None
        for i, img in enumerate(images):
            if img.get("filename") == filename:
                found = i
                break

        if found is None:
            return f"Image '{filename}' not found in workspace '{slug}'."

        removed = images.pop(found)
        self._save_workspace(ws)
        self._save_index()

        img_path = self._workspaces_dir() / slug / "generated_images" / filename
        if img_path.exists():
            img_path.unlink()

        return {
            "status": "deleted",
            "workspace": slug,
            "filename": filename,
            "prompt": removed.get("prompt", ""),
        }
