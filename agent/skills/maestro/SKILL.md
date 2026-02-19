---
name: maestro
description: Construction plan analysis tools. Search materials, get sheet summaries, find cross-references, list modifications. Run after plans have been ingested with the ingest CLI.
---

# Maestro Knowledge Tools

Your project plans have been ingested and analyzed. Use these tools to answer questions about the plans.

Run via: `python skills/maestro/scripts/tools.py <command> [args]`

The tools load from `knowledge_store/` in your workspace. If no project is specified, the first project found is used.

## Available Commands

| Command | Description |
|---------|-------------|
| `list_disciplines` | List all disciplines (Architectural, Structural, MEP, etc.) |
| `list_pages [--discipline X]` | List all pages, optionally filtered by discipline |
| `search <query>` | Search all pages and pointers for a keyword, material, or term |
| `get_sheet_summary <page>` | Get the superintendent briefing for a page |
| `get_sheet_index <page>` | Get the searchable index (keywords, materials, cross-refs) |
| `list_regions <page>` | List all detail regions on a page |
| `get_region_detail <page> <region_id>` | Get the deep technical brief for a specific detail/region |
| `find_cross_references <page>` | Find what sheets reference a page and what it references |
| `list_modifications` | List all install/demolish/protect items across the project |
| `check_gaps` | Find broken cross-references and regions missing deep analysis |

## Page Name Resolution

You don't need exact page names. These all work:
- `A101` → matches `A101_Floor_Plan_p001`
- `Floor_Finish` → matches `A111_Floor_Finish_Plan_p001`
- `A101_Floor_Plan_p001` → exact match

## Examples

```bash
# What disciplines are in this project?
python skills/maestro/scripts/tools.py list_disciplines

# Show me all architectural pages
python skills/maestro/scripts/tools.py list_pages --discipline Architectural

# Where's the waterproofing spec?
python skills/maestro/scripts/tools.py search "waterproofing membrane"

# Give me the superintendent briefing for A101
python skills/maestro/scripts/tools.py get_sheet_summary A101

# Deep dive on a specific detail
python skills/maestro/scripts/tools.py get_region_detail A101 r_545_290_685_475

# What sheets reference A101?
python skills/maestro/scripts/tools.py find_cross_references A101_Floor_Plan_p001
```

## Workspace Commands

Workspaces are how you organize findings for the super. Each workspace is a collection of pages, selected pointers, highlights, and notes around a topic.

| Command | Description |
|---------|-------------|
| `create_workspace <title> <description>` | Create a new workspace |
| `list_workspaces` | List all workspaces |
| `get_workspace <slug>` | Get full workspace details |
| `add_page <slug> <page>` | Add a page to a workspace |
| `remove_page <slug> <page>` | Remove a page from a workspace |
| `select_pointers <slug> <page> <id1> [id2...]` | Select specific pass1 regions to highlight |
| `deselect_pointers <slug> <page> <id1> [id2...]` | Remove selected pointers |
| `add_note <slug> <text> [--source_page X]` | Add a note to the workspace |
| `add_description <slug> <page> <description>` | Add a description to a workspace page |

### Workspace Workflow

1. **Create a workspace** for the topic: `create_workspace "Refuse Enclosure" "All details related to the refuse enclosure area"`
2. **Add relevant pages**: `add_page refuse_enclosure A101`
3. **Select specific pointers** (pass1 regions): `select_pointers refuse_enclosure A101_Floor_Plan_p001 r_545_290_685_475`
4. **Highlight with Gemini vision** for anything pass1 didn't catch: `highlight refuse_enclosure A101 "refuse enclosure and dumpster pad"`
5. **Send the deep link** so the super can see it on their phone

### Deep Links

After creating or updating a workspace, send the super a deep link. Read TOOLS.md for the base URL format:
```
{base_url}?workspace={slug}
```

## Highlight Tool (Gemini Vision) 🔥

The highlight tool uses Gemini vision to find and draw bounding boxes around anything on a plan sheet. It's like having a second set of eyes on the plans.

```bash
# Highlight specific items on a sheet
python skills/maestro/scripts/tools.py highlight <workspace_slug> <page_name> "<query>"

# Clear all highlights from a page  
python skills/maestro/scripts/tools.py clear_highlights <workspace_slug> <page_name>
```

### Examples
```bash
# Find all fire dampers on the floor plan
python skills/maestro/scripts/tools.py highlight hvac_review A101 "fire dampers and fire-rated penetrations"

# Highlight electrical panels and disconnects
python skills/maestro/scripts/tools.py highlight electrical A101 "electrical panels, disconnects, and junction boxes"

# Find all ADA-related items
python skills/maestro/scripts/tools.py highlight ada_review A101 "ADA signage, grab bars, accessible routes, and clearances"

# Clear and re-highlight with a different query
python skills/maestro/scripts/tools.py clear_highlights hvac_review A101_Floor_Plan_p001
python skills/maestro/scripts/tools.py highlight hvac_review A101 "ductwork routing and diffuser locations"
```

### How It Works
- Sends the full-resolution page PNG to Gemini 3 Flash with code execution + thinking
- Gemini uses native spatial understanding (box_2d) for precise bounding boxes
- Results are saved as `custom_highlights` on the workspace page
- Frontend renders them as green overlay boxes in real time
- Highlights persist across sessions — they're saved to the workspace JSON

### When to Use Highlight vs Select Pointers
- **`select_pointers`**: Use existing pass1 regions (free, instant, already indexed)
- **`highlight`**: Find something NEW that pass1 didn't index, or get more precise boxes for a specific query (costs one Gemini API call, ~30s)

### Tips for Good Queries
- Be specific: "grease trap and associated piping" > "plumbing"
- Combine related items: "fire dampers and fire-rated penetrations"
- Use construction terminology the plans would use
- Multiple queries on the same page stack (append) — clear first if you want fresh results

## Image Generation Tool (Gemini 3 Pro Image / Nano Banana Pro) 🎨

Generate or edit images using Gemini 3 Pro Image and save them directly to a workspace. Generated images appear inline alongside plan pages with their own thumbnails and full-size modal.

```bash
# Generate an image from a text prompt
python skills/maestro/scripts/tools.py generate_image <workspace_slug> "<prompt>" [options]

# Generate with plan pages as visual reference
python skills/maestro/scripts/tools.py generate_image <workspace_slug> "<prompt>" --reference_pages A101 S201

# Generate from / edit an external image (site photo, etc.)
python skills/maestro/scripts/tools.py generate_image <workspace_slug> "<prompt>" --reference_image /path/to/photo.jpg

# Control aspect ratio and resolution
python skills/maestro/scripts/tools.py generate_image <workspace_slug> "<prompt>" --aspect_ratio 16:9 --image_size 4K

# Delete a generated image
python skills/maestro/scripts/tools.py delete_image <workspace_slug> <filename>
```

### Options
| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--reference_pages` | page names | none | Plan page PNGs sent as visual context to Gemini |
| `--reference_image` | file path | none | External image to edit or use as reference |
| `--aspect_ratio` | `1:1`, `16:9`, `9:16`, `4:3`, `3:4` | `1:1` | Output aspect ratio |
| `--image_size` | `2K`, `4K` | `2K` | Output resolution |

### Examples
```bash
# Visualize a steel connection detail from the plans
python skills/maestro/scripts/tools.py generate_image refuse_enclosure "3D visualization of the steel moment connection at the refuse enclosure gate, showing SHS framing and welded mesh panels" --reference_pages AS4_2

# Generate a process diagram
python skills/maestro/scripts/tools.py generate_image concrete_pour "Step-by-step diagram showing the concrete pour sequence for foundation zones A through C, with arrows indicating pour direction"

# Edit a site photo to mark deficiencies
python skills/maestro/scripts/tools.py generate_image punch_list "Mark all visible deficiencies in red circles with labels" --reference_image /path/to/site-photo.jpg

# Generate a material visualization
python skills/maestro/scripts/tools.py generate_image waterproofing "Cross-section diagram showing the waterproofing membrane assembly: substrate, primer, membrane layers, protection board, and drainage mat" --reference_pages A501
```

### What It Can Do
- **Detail visualization** — Turn tiny plan callouts into clear, readable renderings
- **Process diagrams** — Sequence diagrams, flowcharts, installation steps
- **Realistic renders** — 3D-style visualizations of assemblies and connections
- **Image editing** — Annotate site photos, mark deficiencies, overlay missing elements
- **Material diagrams** — Cross-sections, assembly details, layering diagrams
- **Multi-image fusion** — Combine plan pages + site photos into annotated composites

### How It Works
- Calls Gemini 3 Pro Image (`gemini-3-pro-image-preview`) with text + optional reference images
- Generated images are saved as PNGs in the workspace's `generated_images/` folder
- Frontend renders them inline with plan pages (green "AI Generated" badge)
- Click to open full-size in the zoom/pan modal, same as plan pages
- Tracked in `workspace.json` under `generated_images` array

### When to Use
- Super asks "what should this look like?" → generate a visualization
- Super sends a photo and asks "is this right?" → edit with annotations
- Complex detail that's hard to describe in text → show it visually
- Need a process diagram for a sequence of work → generate it
- Want to compare plan intent vs. site conditions → side by side in workspace

## General Workflow

1. Start broad: `list_disciplines` → `list_pages` to orient yourself
2. Search for specific terms: `search "FRP"` to find where something appears
3. Drill down: `get_sheet_summary` → `list_regions` → `get_region_detail`
4. Cross-reference: `find_cross_references` to trace connections between sheets
5. **Create a workspace** when the super asks about a topic
6. **Add pages + highlight** to build a visual reference
7. **Send the deep link** so they can see it on their phone
8. QA: `check_gaps` to find anything missing

## Ingesting New Plans

To ingest a new set of plans:
```bash
python skills/maestro/scripts/ingest.py "<path-to-pdf-folder>"
```

Requires `GEMINI_API_KEY` in `.env` or environment. Uses Gemini 3 Flash with agentic vision.
