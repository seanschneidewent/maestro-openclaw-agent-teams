# Maestro Product Specification

*Generated from Maestro ↔ Sean design session, Feb 18-19, 2026*

> Historical product design document. For current implemented architecture and commands, use `README.md` first.

---

## Table of Contents

1. [OpenClaw Package Configuration](#openclaw-package-configuration)
2. [Workspace Structure](#workspace-structure)
3. [Skills Architecture](#skills-architecture)
4. [Channel Configuration](#channel-configuration)
5. [Integrations](#integrations)
6. [Out-of-Box Experience](#out-of-box-experience)
7. [Capability Stack](#capability-stack)
8. [Tools Reference](#tools-reference)

---

## OpenClaw Package Configuration

### Agent Configuration

```json
{
  "agents": {
    "list": [
      {
        "id": "maestro",
        "name": "Maestro",
        "default": true,
        "model": "anthropic/claude-sonnet-4-5",
        "workspace": "~/.maestro/workspace"
      }
    ]
  }
}
```

One agent per project. If the company has three projects, they get three Maestro instances — each with its own workspace, its own plans, its own learned context. The company-level stuff (org knowledge pool, cross-project observations) is a shared workspace that all instances can query.

Model starts at Sonnet for speed and cost. Super can bump to Opus for deep analysis sessions. Haiku for voice interactions where latency matters.

---

## Workspace Structure

```
~/.maestro/workspace/
├── SOUL.md                          # Who Maestro is (ships with package)
├── AGENTS.md                        # How to operate (ships with package)
├── TOOLS.md                         # Active project config (generated on setup)
├── USER.md                          # Learned - about the super
├── IDENTITY.md                      # This Maestro's identity
├── MEMORY.md                        # Persistent memory
├── memory/                          # Daily memory files
│
├── knowledge_store/                 # Plan intelligence (from ingest)
│   └── <project>/
│       ├── pages/                   # Sheet analysis + crops
│       └── workspaces/              # Focused work areas
│
├── specs/                           # Project manual / spec sections
│   └── <project>/
│       ├── divisions/               # Parsed by CSI division
│       └── index.json               # Cross-ref to plan details
│
├── schedule/                        # Schedule intelligence
│   └── <project>/
│       ├── baseline.json            # CPM baseline (imported)
│       ├── current_update.json      # Latest schedule update
│       ├── lookahead.json           # 3-week lookahead (auto-generated)
│       └── calendar_sync.json       # Google Calendar mapping
│
├── submittals/                      # Submittal tracking
│   └── <project>/
│       ├── log.json                 # Submittal register
│       ├── items/                   # Individual submittal docs
│       └── cross_ref.json           # Map to specs + plan details
│
├── rfis/                            # RFI tracking
│   └── <project>/
│       ├── log.json                 # RFI register
│       ├── responses/               # Response documents
│       └── plan_overlays.json       # Which details are modified
│
├── field/                           # Field documentation
│   └── <project>/
│       ├── daily_reports/           # Generated from conversations
│       │   └── 2026-02-19/
│       │       ├── report.md        # The daily report
│       │       └── photos/          # Field photos + metadata
│       ├── inspections/             # Inspection results
│       └── as_built_log.json        # Tracked deviations from plans
│
├── contracts/                       # Scope documents
│   └── <project>/
│       ├── subs/                    # Subcontract scope exhibits
│       └── scope_matrix.json        # Who does what, parsed
│
└── comms/                           # Communication log
    └── <project>/
        ├── meeting_minutes/         # OAC minutes, coordination mtgs
        └── decisions.json           # Extracted decisions mapped to items
```

Everything under `knowledge_store/` is the existing plan intelligence. Everything else is new capability. The structure is ready from day one — folders exist and fill up as the super feeds Maestro documents and as Maestro learns from conversations.

---

## Skills Architecture

Each capability gets its own skill, same pattern as the current maestro skill:

```
skills/
├── maestro/                    # Plans (built)
│   └── scripts/tools.py
├── maestro-specs/              # Spec book analysis
│   └── scripts/tools.py
├── maestro-schedule/           # Schedule + calendar
│   └── scripts/tools.py
├── maestro-submittals/         # Submittal tracking
│   └── scripts/tools.py
├── maestro-rfis/               # RFI tracking + plan overlay
│   └── scripts/tools.py
├── maestro-field/              # Daily reports + photos
│   └── scripts/tools.py
├── maestro-contracts/          # Scope parsing
│   └── scripts/tools.py
└── maestro-comms/              # Meeting minutes + decisions
    └── scripts/tools.py
```

Each skill has its own tools, its own ingest pipeline, and its own cross-reference logic. They all share the same project context and can query each other.

---

## Channel Configuration

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "accounts": {
        "maestro": {
          "botToken": "<project-specific-bot>",
          "dmPolicy": "pairing"
        }
      }
    }
  }
}
```

Telegram is the primary interface. One bot per Maestro instance. The super adds the bot on their phone and that's their connection. No app to download, no login to remember.

Voice messages come through Telegram natively — super sends a voice note, OpenClaw transcribes it, Maestro responds. Photos come through the same way.

---

## Integrations

```json
{
  "integrations": {
    "google": {
      "enabled": true,
      "scopes": ["calendar", "drive"],
      "auth": "oauth"
    },
    "procore": {
      "enabled": false,
      "apiKey": null
    },
    "autodesk": {
      "enabled": false,
      "apiKey": null
    }
  }
}
```

Google ships enabled by default — calendar for schedule, Drive for document storage and photo backup. Procore and Autodesk are opt-in for companies that use them.

The Google OAuth flow happens during setup: super signs in with their Google account, authorizes calendar and Drive access, done. From that point forward, Maestro can read their calendar, write schedule events, and store/retrieve documents in Drive.

---

## Out-of-Box Experience

Day one for a new Maestro deployment:

1. **Super gets a Telegram bot link.** They tap it, it opens Telegram, they hit Start.

2. **Maestro introduces itself.** "I'm Maestro. Send me your plans and I'll learn the project." Not a setup wizard. Not a form. Just a conversation.

3. **Super sends plan PDFs through Telegram** (or drops them in a Google Drive folder). Maestro ingests. "Got it. 198 pages across architectural, structural, civil, and electrical. Here's what I'm seeing — want me to walk you through it?"

4. **Super connects Google Calendar.** Maestro sends an auth link. Super taps, authorizes, done. Maestro reads their calendar and starts learning their rhythm.

5. **Super starts asking questions.** From this moment, Maestro is learning the person — communication style, what they care about, how they think about the project.

6. **Over the next week**, the super feeds Maestro more: spec book PDF, submittal log, subcontract scopes. Each one deepens what Maestro knows. Nothing is required — each document is additive.

7. **By week two**, Maestro is texting first. Proactive findings based on what's in the plans cross-referenced with what's on the calendar.

No training. No dashboard. No onboarding session. Just a Telegram bot that gets smarter the more you feed it.

### Auto-Generated TOOLS.md

```markdown
# TOOLS.md — Maestro Project Config

## Active Project
- Name: [from plan title sheet]
- Slug: [auto-generated]
- Knowledge Store: knowledge_store/

## Capabilities Active
- [x] Plans (198 pages, 1428 pointers)
- [x] Specs (uploaded Division 03, 07, 08)
- [ ] Schedule (Google Calendar not connected)
- [x] Submittals (Excel log imported, 47 items)
- [ ] RFIs (not connected)
- [x] Field Photos (workspace storage)
- [ ] Contracts (not uploaded)
- [ ] Communications (not uploaded)

## Integrations
- Telegram: connected (bot @MaestroCFA_bot)
- Google Calendar: not connected (run /connect_calendar)
- Google Drive: not connected
- Procore: not available
```

---

## Capability Stack

### Deployment Order (each adds a layer of cross-reference)

| Priority | Capability | Integration | Value |
|----------|-----------|-------------|-------|
| 1 | Plans | PDF ingest (built) | Foundation — every sheet, detail, cross-ref |
| 2 | Schedule | Google Calendar OAuth | Timing — when things happen, what's critical |
| 3 | Specs | PDF ingest (same pipeline) | Depth — how to build it, what products |
| 4 | Field/Photos | Telegram + workspace storage | Reality — what actually happened |
| 5 | Submittals | Procore API / Google Drive / Excel | Approval chain — what's approved to install |
| 6 | RFIs | Procore API / Excel | Modifications — where plans have changed |
| 7 | Contracts | PDF ingest | Responsibility — who does what |
| 8 | Communications | Meeting minutes upload | Decisions — what was agreed |

### How They Cross-Reference

Plans alone are a snapshot — what the architect INTENDED. Each additional capability bridges the gap between what's drawn and what's real:

- **Plans + Specs** = What's designed AND how to build it
- **Plans + Schedule** = What's designed AND when it happens
- **Plans + Submittals** = What's specified AND what's approved to install
- **Plans + RFIs** = What's drawn AND what's been modified since
- **Plans + Field** = What's designed AND what actually got built
- **Plans + Contracts** = What needs to happen AND who's responsible
- **Plans + Comms** = What's on paper AND what was decided verbally

All eight together = **"Are we ready to pour Thursday?"** answered from every angle simultaneously.

### The Cross-Reference Example

**Super asks: "Are we ready to pour the Building B podium Thursday?"**

- **Plans** tell me: here's what's in the podium — rebar, PT tendons, embeds, sleeves, waterproofing
- **Schedule** tells me: pour is on the lookahead for Thursday, it's on critical path
- **Specs** tell me: Division 03 requires minimum 40°F pour temperature, cold weather plan below 40°F
- **Submittals** tell me: rebar approved, PT approved, embed plates approved as noted yesterday — note says verify edge distance
- **RFIs** tell me: RFI #31 changed the PT tendon profile at grid B-3, response received last week, plans haven't been updated
- **Field/Daily Reports** tell me: plumbing sleeves placed Monday, electrical conduit Tuesday, rebar inspection passed Wednesday
- **Weather** tells me: forecast Thursday is 28°F

**Maestro's answer:** "Plans are set, submittals are approved, rebar passed inspection, BUT — RFI #31 changed the PT profile at B-3, make sure the PT sub has the updated layout. And Thursday's forecast is 28°F. You need the cold weather plan or you need to push to Friday when it's 45°F. Also the embed plate submittal had a note about edge distance — verify in field before the pour."

---

## Tools Reference

### maestro/ — Plans (BUILT)

The template for all other skills.

```
Ingest: PDF → Gemini vision → page analysis → region detection → deep detail pass
Query: search, get_sheet_summary, get_sheet_index, list_regions, get_region_detail
Workspace: create/manage workspaces, select pointers, highlight, generate images
```

---

### maestro-specs/ — Specifications

```python
# Ingest
ingest_specs <pdf_path>              # Parse project manual PDF
                                      # Split by CSI division
                                      # Extract: section numbers, product requirements,
                                      # performance criteria, referenced standards,
                                      # installation requirements, QC requirements

# Query
list_divisions                        # What spec divisions are loaded
get_section <section_number>          # Pull full spec section (e.g., "07 1300")
search_specs <query>                  # Search across all spec sections
get_product_requirements <section>    # Just the product/material requirements
get_installation_requirements <section>  # Just the installation procedures
find_spec_for_detail <page> <region>  # Given a plan detail, find the governing spec
                                      # Uses cross-refs from keynotes and general notes

# Cross-reference
check_spec_conflicts                  # Find where plan details and specs disagree
                                      # e.g., plan says "waterproofing membrane"
                                      # but doesn't specify which spec section,
                                      # or two spec sections reference different products
```

**Key command: `find_spec_for_detail`** — the bridge between plans and specs. When the super asks about a plan detail, Maestro automatically pulls the governing spec. "Detail 2/A101 shows Composeal Gold membrane. That's spec section 07 1300 — requires surface to be clean, dry, free of laitance, prime with manufacturer's primer, minimum 40°F application temperature."

---

### maestro-schedule/ — Schedule + Calendar

```python
# Ingest
import_schedule <file>               # Accept: .xer (Primavera), .mpp (MS Project),
                                      # .xlsx (Excel), .csv
                                      # Parse: activities, durations, predecessors,
                                      # successors, float, critical path
                                      # Map activities to plan areas where possible
                                      # (match activity descriptions to sheet names,
                                      # building areas, trade names)

sync_calendar                         # Read Google Calendar, map events to activities
update_lookahead                      # Generate 3-week lookahead from current schedule

# Query
get_lookahead [--weeks N]             # Next N weeks of activities
get_critical_path                     # Activities on critical path
get_activity <activity_id>            # Full detail on one activity
check_predecessors <activity_id>      # What needs to finish before this starts
check_float <activity_id>             # How much float, what eats it
whats_next <trade>                    # Next activities for a specific trade
                                      # e.g., "whats_next plumbing"

# Cross-reference
check_readiness <activity_id>         # Is this activity ready to start?
                                      # Checks: predecessors complete?
                                      # Submittals approved? RFIs answered?
                                      # Materials on site? Inspections passed?
                                      # Weather OK for this work type?
                                      # Returns: ready / not ready + blockers

# Calendar
push_to_calendar <activity_id>        # Push activity to Google Calendar with
                                      # plan details, spec refs, open items attached
push_lookahead_to_calendar            # Push full 3-week lookahead
set_reminder <activity_id> <days_before> <message>
```

**Key command: `check_readiness`** — reaches across every other skill (plans, specs, submittals, RFIs, field docs) and gives a single answer: can this activity start or not, and if not, what's blocking it.

---

### maestro-submittals/ — Submittal Tracking

```python
# Ingest
import_submittal_log <file>           # Excel, CSV, or JSON from Procore/Autodesk export
                                      # Parse: item number, spec section, description,
                                      # status, dates, reviewer, comments
import_submittal_doc <item_id> <pdf>  # The actual submittal document (product data,
                                      # shop drawing, etc.)
watch_drive_folder <folder_id>        # Watch a Google Drive folder for new submittals
                                      # Auto-import when files appear
sync_procore                          # Pull from Procore API if connected

# Query
list_submittals [--status X]          # List all, filter by status
get_submittal <item_id>               # Full detail on one submittal
check_status <spec_section>           # What's the submittal status for this spec?
overdue_submittals                    # Items past due date without response
pending_submittals                    # Items submitted, awaiting response
not_submitted                         # Items required but not yet submitted

# Cross-reference
map_to_schedule                       # Which schedule activities need which submittals?
                                      # Flag: activity starting in 2 weeks,
                                      # submittal not approved yet
lead_time_check                       # Submittal approved, but does the lead time
                                      # fit the schedule? 16-week lead time +
                                      # approval date = delivery date vs. need date
```

**Key commands: `map_to_schedule` + `lead_time_check`** — Submittals alone are just a log. Cross-referenced to the schedule they reveal: "The curtain wall shop drawings were just approved. 16-week lead time puts delivery at June 1. Schedule shows installation starting May 15. You're two weeks short."

---

### maestro-rfis/ — RFI Tracking + Plan Overlay

```python
# Ingest
import_rfi_log <file>                # Excel, CSV, or platform export
import_rfi_response <rfi_id> <pdf>   # The actual response document
sync_procore                          # Pull from Procore API

# Query
list_rfis [--status open|closed]      # List all, filter
get_rfi <rfi_id>                      # Full detail including response
open_rfis                             # All unanswered RFIs
overdue_rfis [--days N]               # Open longer than N days
rfis_for_sheet <page>                 # All RFIs affecting a specific sheet

# Cross-reference
check_plan_modifications <page>       # Given a sheet, show all RFI modifications
                                      # "Detail 4/A401 modified by RFI #47:
                                      # stud spacing changed from 16 to 12 O.C."
rfis_blocking_schedule                # Open RFIs that affect activities on
                                      # the lookahead. Most critical first.
draft_rfi <subject> <question>        # Draft an RFI from a finding
                                      # Pre-fills: affected sheets, details,
                                      # spec sections, related submittals
```

**Key command: `check_plan_modifications`** — Instead of RFI modifications being buried in a log, they surface in context when the super is looking at the affected detail. `draft_rfi` turns findings into action: "I found a conflict at B-3. Want me to draft the RFI?"

---

### maestro-field/ — Daily Reports + Photos + Inspections

```python
# Ingest
log_daily <text>                      # Super talks or texts, Maestro structures it
                                      # Extracts: activities, locations, quantities,
                                      # deviations, issues, weather
add_photo <image> [--caption text]    # Store photo, analyze with vision,
                                      # auto-tag: location, trade, condition
                                      # Cross-ref to plan area if identifiable
add_inspection <type> <result> [--notes text]
                                      # Log inspection result
                                      # Types: concrete, framing, MEP rough,
                                      # fire stopping, waterproofing, etc.
sync_procore_daily                    # Pull from Procore daily log
sync_raken                            # Pull from Raken

# Query
get_daily_report <date>               # Generated report for a date
get_photos [--date X] [--location Y] [--trade Z]
                                      # Search photos by metadata
get_as_built_log                      # All tracked deviations from plans
get_inspections [--status pass|fail|pending]
what_happened <location>              # Everything that happened at a location
                                      # "What happened at Building A grid B-3?"
                                      # Returns: all daily entries, photos,
                                      # inspections, deviations for that area

# Cross-reference
deviations_from_plans                 # Where does as-built differ from plans?
                                      # "Anchor bolt at B-3 moved 2 inches east
                                      # per daily report 2/19. Plans show original
                                      # location on S1.1."
inspection_blockers                   # Failed inspections blocking schedule activities
photo_timeline <location>             # All photos of a location in chronological order
                                      # "Show me everything at B-3 from pour prep
                                      # through completion"

# Generate
generate_daily_report                 # Compile today's log entries, photos,
                                      # inspections into a formatted daily report
                                      # Output: markdown + PDF
export_to_procore                     # Push generated report to Procore
```

**Key commands: `what_happened` + `photo_timeline`** — The project memory for a specific location. Pulls everything — daily entries, photos, inspections, deviations — in chronological order. `generate_daily_report` from conversational input saves the super 20 minutes every day.

**Adoption driver:** Supers hate filling out daily reports. If Maestro does it from a conversation, that's the feature that sells it. And Maestro gets field intelligence as a byproduct.

---

### maestro-contracts/ — Scope Parsing

```python
# Ingest
import_contract <sub_name> <pdf>      # Parse subcontract scope exhibit
                                       # Extract: scope items, exclusions,
                                       # allowances, unit prices, key terms
import_responsibility_matrix <file>    # If the GC has one (larger companies)

# Query
get_scope <sub_name>                   # Full scope for a sub
whose_scope <description>              # "Who installs TV backing?"
                                       # Searches all scope exhibits
                                       # Returns: sub name + section reference
check_exclusions <sub_name>            # What's explicitly NOT in their scope
get_responsibility <area> <trade>      # For a given plan area and trade,
                                       # what's the sub responsible for?

# Cross-reference
scope_gaps                             # Find work items in plans that don't
                                       # appear in ANY sub's scope — unfunded work
scope_overlaps                         # Find work claimed by multiple subs
coordination_responsibilities          # Who coordinates with whom at each
                                       # interface? Parsed from contract language
```

**Key command: `scope_gaps`** — Reads the plans, identifies all work, checks against every subcontract scope. Anything not covered is a gap — work nobody's been hired to do. Every super has discovered a scope gap mid-construction. This finds them before they become a problem.

---

### maestro-comms/ — Meeting Minutes + Decisions

```python
# Ingest
import_meeting_minutes <pdf>           # Parse OAC or coordination meeting minutes
                                       # Extract: decisions, action items,
                                       # responsible parties, due dates
import_email <file_or_text>            # Selective — super forwards specific emails
                                       # Extract: decisions, commitments, dates
log_decision <text> [--source meeting|email|verbal]
                                       # Super tells Maestro about a decision
                                       # "Architect approved the alternate door
                                       # hardware at today's OAC"

# Query
get_decisions [--topic X]              # All logged decisions, filterable
get_action_items [--status open]       # Open action items from meetings
get_decision_for <item>                # "What was decided about the door hardware?"
                                       # Traces through meeting minutes and emails

# Cross-reference
decisions_without_cos                  # Owner-directed changes that don't have
                                       # a signed change order yet — exposure risk
open_action_items_on_schedule          # Action items from meetings that affect
                                       # activities on the lookahead
undocumented_changes                   # Work happening in the field (from daily
                                       # reports) that doesn't trace to a decision,
                                       # CO, or RFI — potential liability
```

**Key command: `decisions_without_cos`** — Owner says "go ahead" in a meeting. Super does the work. Three months later, owner says "I never approved that." Maestro has the meeting minutes, the decision, and the date. Not just project management — lawsuit prevention.

---

### Master Cross-Reference Commands

These sit above all individual skills, pulling from everything:

```python
# In the main maestro tools.py

project_status <area_or_activity>      # Everything about a location or activity
                                       # Plans: what's designed
                                       # Specs: what's specified
                                       # Schedule: when it's happening
                                       # Submittals: what's approved
                                       # RFIs: what's been modified
                                       # Field: what's been built + photos
                                       # Contracts: who's responsible
                                       # Comms: what's been decided

ready_to_build <activity>              # Can this activity start?
                                       # Single answer with all blockers
                                       # Pulls from ALL capabilities

daily_briefing                         # Morning briefing for the super
                                       # Today's activities from schedule
                                       # Open items affecting today
                                       # Weather impact on today's work
                                       # Yesterday's unresolved items
```

**`ready_to_build`** is the super's dream command. One question, one answer, pulling from eight data sources. "Ready to pour Thursday?" → "No. Two blockers: PT shop drawing RFI open 18 days, and forecast is 28°F. Push to Friday — RFI response expected Wednesday, Friday forecast is 45°F."

---

## Build Order

| Phase | Capability | Status |
|-------|-----------|--------|
| 1 | Plans (ingest + query + workspace) | ✅ Built |
| 2 | Schedule (Google Calendar OAuth) | 🔜 Next |
| 3 | Specs (PDF ingest, CSI parsing) | Planned |
| 4 | Field/Photos (conversational daily reports) | Planned |
| 5 | Submittals (Procore API / Drive / Excel) | Planned |
| 6 | RFIs (plan overlay, schedule blocking) | Planned |
| 7 | Contracts (scope parsing, gap analysis) | Planned |
| 8 | Communications (meeting minutes, decisions) | Planned |

Plans + Schedule + Specs gets 80% of the value. Submittals and RFIs are the next unlock. Daily reports as conversational input is the adoption driver. Contracts and communications are power-user features.
