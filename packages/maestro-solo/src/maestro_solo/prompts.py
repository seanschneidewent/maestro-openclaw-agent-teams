"""
Maestro prompts — all Gemini prompts in one place.

Centralized so they can be versioned, tested, and iterated on independently.
"""

# ── Pass 1: Sheet-Level Analysis ──────────────────────────────────────────────

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


# ── Pass 2: Deep Region Analysis ─────────────────────────────────────────────

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


# ── Highlight: Gemini Vision Search ───────────────────────────────────────────

HIGHLIGHT_PROMPT = """\
You are analyzing a construction plan sheet for a superintendent.

Find and draw bounding boxes around: {query}

For each match, provide:
- box_2d: [ymin, xmin, ymax, xmax] normalized to 0-1000 coordinate space
- label: short description of what this highlight contains
- confidence: 0.0 to 1.0

Return a JSON object:
```json
{{
  "highlights": [
    {{
      "label": "DRIVE-THRU SILL DETAIL",
      "box_2d": [100, 50, 400, 300],
      "confidence": 0.95
    }}
  ]
}}
```

GUIDELINES:
- Bounding boxes should tightly contain each matched element
- box_2d uses Gemini spatial format: [ymin, xmin, ymax, xmax] in 0-1000 space
- Be precise. If nothing matches, return {{"highlights": []}}
"""
