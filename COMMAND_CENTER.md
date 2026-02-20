# COMMAND_CENTER.md — Maestro Command Center Specification

> The agent is the interface. The web view is the display.

---

## 1. Overview

The Command Center is Company Maestro's visual interface — a live web dashboard that the agent controls. It gives a general contractor at-a-glance visibility across every project agent running on their server.

**Core principle:** Telegram is the primary interface. The human talks to Company Maestro through chat. The Command Center only exists to show what chat can't — multi-project visual state.

No forms. No buttons. No mutations from the UI. Everything goes through conversation.

---

## 2. Product Flow

```
viewm4d.com
  └─ Terminal command front and center
       └─ pip install maestro-conagent-teams && maestro-setup
            └─ Setup CLI runs on customer's server
                 ├─ Creates free company license key
                 ├─ Picks model (Gemini/Claude/GPT)
                 ├─ Configures OpenClaw + Telegram bot
                 └─ "Built for Builders" 🎬
                      └─ Customer opens Telegram
                           └─ Company Maestro is waiting
                                ├─ Chat = primary interface
                                └─ Command Center = visual display
```

### First-Time Experience

1. Customer runs `maestro-setup` on their server
2. CLI walks through model, API key, Telegram bot, company name
3. Setup completes → OpenClaw starts → Company Maestro goes live
4. Customer messages the bot on Telegram
5. Company Maestro introduces itself, explains what it can do
6. "Want to set up your first project?" → walks them through it
7. Command Center URL is provided: `http://<tailnet-ip>:3000/command-center`

---

## 3. Two-Tier Agent Architecture

### Company Maestro (Free Tier)
- Created during `maestro-setup`
- One per server/company
- Orchestrator — manages all project agents
- Handles: licensing, billing, project provisioning, cross-project reports
- Controls the Command Center web view
- Can communicate with any project agent via transmittal

### Project Maestro (Paid Tier)
- One per project (e.g., "CFA Love Field", "123 Main St")
- Created by Company Maestro when the human says "spin up a project"
- Has the full plan intelligence stack (search, highlights, workspaces, etc.)
- Reports status/alerts back to Company Maestro
- Has its own plan viewer at `/project/:slug`

### Communication Flow
```
Human ←→ Company Maestro ←→ Project Maestro A
                          ←→ Project Maestro B
                          ←→ Project Maestro C

Human can also talk directly to any Project Maestro via Telegram.
```

---

## 4. Command Center Layout

```
┌──────────────────────────────────────────────────────────────┐
│  MAESTRO COMMAND CENTER                    [Company Name]     │
│  ● 3 projects active  •  $47.20 this month                  │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ CFA LOVE FIELD   │  │ 123 MAIN ST     │  │ MEMORIAL     │ │
│  │                  │  │                  │  │ HOSPITAL     │ │
│  │ ● Active         │  │ ● Active         │  │ ○ Setup      │ │
│  │ 198 pages        │  │ 84 pages         │  │ Awaiting     │ │
│  │ 1,428 pointers   │  │ 612 pointers     │  │ plan ingest  │ │
│  │                  │  │                  │  │              │ │
│  │ Last: 2m ago     │  │ Last: 1h ago     │  │ Created: now │ │
│  │ ⚠ 3 alerts       │  │ No alerts        │  │              │ │
│  │                  │  │                  │  │              │ │
│  │ [Open Viewer →]  │  │ [Open Viewer →]  │  │              │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                               │
│  ┌─ ACTIVITY FEED ──────────────────────────────────────────┐│
│  │                                                           ││
│  │ 2:03 PM  CFA agent flagged MEP coordination conflict     ││
│  │          Mechanical duct routing vs structural beam S-4.1 ││
│  │                                                           ││
│  │ 1:45 PM  123 Main daily report generated                 ││
│  │          12 conversations, 3 workspace updates            ││
│  │                                                           ││
│  │ 1:30 PM  Memorial Hospital project created               ││
│  │          Awaiting plan upload                             ││
│  │                                                           ││
│  │ 11:00 AM Company Maestro weekly rollup sent              ││
│  │          3 projects, $47.20 usage, 2 open alerts          ││
│  │                                                           ││
│  └───────────────────────────────────────────────────────────┘│
│                                                               │
│  ┌─ BILLING ────────────────────────────────────────────────┐│
│  │ Plan: Pay-as-you-go  •  3 active projects                ││
│  │                                                           ││
│  │ This month:  $47.20  ████████████░░░░░░░░                ││
│  │   CFA Love Field:     $22.10  (47%)                      ││
│  │   123 Main St:        $18.40  (39%)                      ││
│  │   Memorial Hospital:   $6.70  (14%)                      ││
│  │                                                           ││
│  │ Payment: Visa •••• 4242  •  Next invoice: Mar 1          ││
│  └───────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

### Components

| Component | What it shows | Update trigger |
|-----------|--------------|----------------|
| **Header** | Company name, project count, month spend | On any state change |
| **Project Cards** | Status, stats, last activity, alerts, viewer link | Project agent heartbeat or event |
| **Activity Feed** | Chronological log of events across all agents | Any agent event |
| **Billing Panel** | Plan, per-project usage, payment method, next invoice | Daily or on billing event |

### Interactions (minimal)
- Click project card → deep-link to that project's plan viewer
- Click alert → expands detail (or links to Telegram conversation)
- That's it. Everything else goes through chat.

---

## 5. State Architecture

### State Blob

Company Maestro maintains a single JSON state file that the frontend reads:

```json
{
  "company": {
    "name": "Turner Construction",
    "plan": "pay-as-you-go",
    "created": "2026-02-15T00:00:00Z"
  },
  "projects": [
    {
      "id": "PRJ001",
      "name": "CFA Love Field",
      "slug": "chick_fil_a_love_field_fsu_03904_cps",
      "status": "active",
      "agent_session": "agent:maestro-cfa:main",
      "stats": {
        "pages": 198,
        "pointers": 1428,
        "disciplines": 4
      },
      "last_activity": "2026-02-20T02:03:00Z",
      "last_activity_summary": "Flagged MEP coordination conflict",
      "alerts": [
        {
          "severity": "warning",
          "message": "Mechanical duct routing conflicts with beam on S-4.1",
          "timestamp": "2026-02-20T02:03:00Z"
        }
      ],
      "usage_this_month": 22.10,
      "viewer_url": "/project/chick_fil_a_love_field_fsu_03904_cps"
    }
  ],
  "activity_feed": [
    {
      "timestamp": "2026-02-20T02:03:00Z",
      "project": "CFA Love Field",
      "event": "alert",
      "summary": "Flagged MEP coordination conflict"
    }
  ],
  "billing": {
    "month_total": 47.20,
    "payment_method": "Visa •••• 4242",
    "next_invoice": "2026-03-01"
  },
  "updated_at": "2026-02-20T02:05:00Z"
}
```

### Data Flow

```
Project Agent A ──heartbeat/alert──→ Company Maestro ──writes──→ state.json
Project Agent B ──heartbeat/alert──→                              │
Project Agent C ──heartbeat/alert──→                              │
                                                                   ↓
                                                            WebSocket push
                                                                   ↓
                                                         Command Center UI
```

1. **Project agents** send periodic heartbeats + event-driven alerts to Company Maestro via transmittal
2. **Company Maestro** aggregates everything, updates `state.json`
3. **FastAPI** watches `state.json`, pushes updates via WebSocket
4. **React frontend** subscribes, re-renders affected components

### Why a file, not in-memory?
- Survives server restarts
- Agent can read/write it with standard tools (no custom API needed)
- Easy to inspect/debug
- FastAPI just watches + relays — minimal server logic

---

## 6. Agent Conversations

### Company Maestro Capabilities (via chat)

**Project Management:**
- "Set up a new project" → walks through project name, plan upload, license key generation
- "Show me all projects" → text summary + updates command center
- "Archive the hospital project" → deactivates agent, updates state
- "What's happening on CFA?" → queries that project agent, returns summary

**Billing:**
- "Add my card" → sends Stripe Checkout link
- "What's my usage?" → text breakdown + updates billing panel
- "What am I spending on 123 Main?" → per-project detail

**Licensing:**
- "Generate a project key" → creates MAESTRO-PROJECT-V1 key
- "How many licenses do I have?" → summary

**Reports:**
- "Give me a daily rollup" → aggregates reports from all project agents
- "What alerts are open?" → cross-project alert summary
- "Compare activity across projects this week" → analysis

**Agent Communication:**
- "Ask the CFA agent about the roof detail" → transmittal to project agent, returns answer
- "Tell all agents to flag anything related to fire rating" → broadcast

### Company Maestro Proactive Behavior
- Morning rollup: "Here's what happened across your projects overnight"
- Alert forwarding: "CFA agent found a coordination issue — [details]"
- Usage warnings: "You're at 80% of last month's spend with 10 days left"
- Ingest completion: "Hospital project plans are done — 156 pages, 892 pointers. Ready to go."

---

## 7. Stripe Integration

### Flow
1. During setup or via chat, customer says "add payment"
2. Company Maestro generates a Stripe Checkout Session URL
3. Sends it via Telegram: "Here's your payment link: [url]"
4. Customer completes checkout in browser
5. Stripe webhook hits viewm4d.com → confirms payment
6. viewm4d.com notifies Company Maestro (or Company Maestro polls)
7. Company Maestro updates billing state

### What lives where
| Component | Location | Purpose |
|-----------|----------|---------|
| Stripe Checkout | viewm4d.com (Vercel) | Hosted payment page |
| Webhooks | viewm4d.com API | Receive payment confirmations |
| Usage tracking | Company Maestro (local) | Token counting per project |
| Usage reporting | viewm4d.com API | Monthly invoice generation |
| Billing display | Command Center (local) | Visual summary |

### Pricing Model (TBD)
- Per-project monthly fee? Per-token usage? Hybrid?
- Company Maestro is free — always
- Project Maestro has a cost — licensing + usage
- Sean to decide pricing structure

---

## 8. Technical Architecture

### Routes
```
/command-center          → Command Center (Company Maestro)
/project/:slug           → Plan Viewer (Project Maestro)
/project/:slug?workspace=:ws  → Plan Viewer with workspace
```

### FastAPI Endpoints
```
GET  /api/state              → Current command center state
WS   /ws/command-center      → Real-time state updates
POST /api/projects            → Create project (called by agent)
POST /api/projects/:id/alert  → Project agent posts alert
GET  /api/billing/usage       → Usage summary
```

### React Components
```
CommandCenter/
  ├── CommandCenterLayout.tsx    → Top-level grid
  ├── ProjectCard.tsx            → Individual project card
  ├── ProjectCardGrid.tsx        → Responsive grid of cards
  ├── ActivityFeed.tsx           → Chronological event log
  ├── BillingPanel.tsx           → Usage and payment summary
  ├── Header.tsx                 → Company name, quick stats
  └── hooks/
      └── useCommandCenterState.ts  → WebSocket subscription
```

### State Management
- No Redux, no complex state management
- Single WebSocket connection → `useCommandCenterState` hook
- Hook returns the state blob, components destructure what they need
- On reconnect, fetch full state via GET `/api/state`

---

## 9. viewm4d.com (Public Website)

### Landing Page
The website is NOT a traditional SaaS landing page. It's minimal:

```
┌────────────────────────────────────────────┐
│                                            │
│           M A E S T R O                    │
│         Built for Builders                 │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ $ pip install maestro-conagent-teams │  │
│  │ $ maestro-setup                      │  │
│  └──────────────────────────────────────┘  │
│                                            │
│     One command. Your plans. Your AI.      │
│                                            │
│          [What is Maestro?]                │
│                                            │
└────────────────────────────────────────────┘
```

Below the fold (optional):
- What Maestro does (3-4 bullet points, not a feature matrix)
- Pricing: "Company Maestro is free. Project agents are $X/month."
- "Questions? Ask Maestro." → links to a demo bot

### Backend (viewm4d.com API)
- Company key generation (free, on signup)
- Stripe checkout sessions
- Stripe webhooks
- License validation endpoint
- Usage reporting endpoint

---

## 10. Setup CLI Changes

The setup CLI (`maestro-setup`) needs to create Company Maestro, not just configure a single agent:

### Current Flow
1. Welcome → Model → API Key → Gemini Key → Company → Project → License → Config → Done

### New Flow
1. Welcome screen ("Built for Builders")
2. Company name
3. Model selection (Gemini/Claude/GPT)
4. API key
5. Gemini vision key (if needed)
6. Telegram bot setup (create bot via BotFather, paste token)
7. Company license key (generated free, or entered if they got one from viewm4d.com)
8. Configure OpenClaw with Company Maestro as default agent
9. Start gateway
10. "Your Command Center is ready at http://localhost:3000/command-center"
11. "Message @YourBot on Telegram to get started"

Project setup happens AFTER — through conversation with Company Maestro.

---

## 11. Migration Path

### Phase 1 (Now → v0.2)
- Ship current product: single agent, single project, plan viewer
- Setup CLI creates one project agent
- No command center yet

### Phase 2 (v0.3)
- Add Company Maestro agent
- Setup CLI creates Company Maestro as default
- Project creation moves to conversation
- Basic command center: project cards + activity feed
- Stripe integration (checkout link via chat)

### Phase 3 (v0.4)
- Full command center with billing panel
- Project agent → Company Maestro heartbeats
- Cross-project reports and alerts
- Multi-user support (multiple Telegram users per company)

### Phase 4 (v0.5+)
- viewm4d.com public site
- Self-service signup flow
- Demo bot on the website
- Advanced analytics in command center

---

## 12. Open Questions

1. **Pricing model** — per project flat fee? Usage-based? Hybrid?
2. **Multi-user** — can multiple people at a company use the command center / talk to agents?
3. **Plan upload** — how does the customer get plans into the system? Upload via chat? SFTP? Web upload?
4. **Demo experience** — should viewm4d.com have a live demo bot people can try?
5. **Mobile** — is the command center responsive, or desktop-only?
6. **Auth** — how does the command center authenticate? Tailnet-only (no auth needed)? Token?
7. **Notifications** — does Company Maestro push alerts to Telegram proactively, or only when asked?
8. **Agent limits** — max projects per server? Based on hardware?

---

*Last updated: 2026-02-20*
*Author: Maestro*
