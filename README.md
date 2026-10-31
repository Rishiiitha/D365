# NEXUS AIOps

> **Autonomous Incident Investigation, Root Cause Analysis and Intelligent Recovery.**

[![Hackathon](https://img.shields.io/badge/Hackathon-AI%20for%20Tech-blue?style=flat-square)](.)
[![Domain](https://img.shields.io/badge/Domain-AIOps%20%7C%20SRE%20%7C%20Observability-6c57f5?style=flat-square)](.)
[![Stack](https://img.shields.io/badge/Stack-React%2019%20%2B%20Vite%208%20%2B%20Tailwind%20CSS%20v4-1db954?style=flat-square)](.)
[![Status](https://img.shields.io/badge/Status-Frontend%20Demo%20%E2%80%94%20No%20Backend-orange?style=flat-square)](.)

---

**NEXUS AIOps** is a frontend demonstration of an **Autonomous Incident Investigation and Recovery** platform built for the **AI for Tech** hackathon track. It simulates how a multi-agent AI system investigates production incidents — reconstructing timelines, detecting anomalies, generating root-cause hypotheses, evaluating evidence, planning investigation steps, invoking read-only diagnostic tools, assessing blast radius, recommending ranked remediations and requiring explicit human approval before any recovery action.

**Keywords:** AIOps · SRE · Autonomous IT · Incident Management · Root Cause Analysis · Multi-Agent System · Observability · Agentic AI · Evidence-Driven Investigation · Human-in-the-Loop · Site Reliability Engineering · Intelligent Recovery

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Problem Statement](#2-problem-statement)
3. [Solution](#3-solution)
4. [Key Features](#4-key-features)
5. [Multi-Agent Architecture](#5-multi-agent-architecture)
6. [System Architecture](#6-system-architecture)
7. [Incident Investigation Workflow](#7-incident-investigation-workflow)
8. [Technology Stack](#8-technology-stack)
9. [Frontend Workspace Documentation](#9-frontend-workspace-documentation)
10. [Data Architecture](#10-data-architecture)
11. [Human-in-the-Loop Safety](#11-human-in-the-loop-safety)
12. [Installation and Setup](#12-installation-and-setup)
13. [Project Directory Structure](#13-project-directory-structure)
14. [Demo Scenarios](#14-demo-scenarios)
15. [Screenshots](#15-screenshots)
16. [Implementation Status](#16-implementation-status)
17. [Important Disclosures](#17-important-disclosures)

---

## 1. Project Overview

Modern production incidents are complex, multi-signal events that demand fast, systematic analysis across distributed systems. Traditional investigation relies on experienced engineers manually correlating logs, metrics, traces, alerts, deployment histories and service dependencies — a process that is slow, error-prone and stressful under pressure.

**NEXUS AIOps** demonstrates what autonomous AI-assisted incident investigation looks like. When an incident fires, the system:

- Reconstructs a chronological evidence timeline from all observable signals.
- Maps the service dependency graph and computes the blast radius.
- Detects anomalies and identifies the temporal window of degradation.
- Generates multiple competing root-cause hypotheses with supporting and contradicting evidence.
- Plans and simulates a sequence of diagnostic tool invocations.
- Updates hypothesis confidence scores as new evidence arrives.
- Assesses user and system impact.
- Presents ranked, risk-labelled remediation options.
- Requires explicit human approval before any recovery action.
- Records the investigation outcome in a persistent Knowledge Base.
- On subsequent incidents that match a known pattern, accelerates investigation by surfacing the prior resolution.

The frontend is built as an **offline demonstration** with realistic fixture data for five distinct incident scenarios. The data layer is cleanly separated behind a `DataSource` interface, enabling the mock implementation to be replaced with real API and SSE connections without touching any UI component.

---

## 2. Problem Statement

| Challenge | Impact |
|---|---|
| **Signal volume** | Hundreds of alerts, thousands of log lines and metric data points arrive simultaneously. |
| **Source fragmentation** | Evidence is spread across logs, metrics, traces, alerts, deployments, configs and tickets. |
| **Dependency opacity** | Cascading failures are hard to trace without a clear service dependency map. |
| **Hypothesis bias** | Human investigators may anchor prematurely on the most obvious explanation. |
| **Slow manual correlation** | A config change from hours earlier may not be correlated with a current degradation. |
| **Risky recovery** | Executing the wrong remediation in a hurry extends the incident. |
| **Knowledge loss** | Lessons from resolved incidents are rarely captured in a structured, queryable form. |

---

## 3. Solution

NEXUS AIOps addresses these challenges through a staged, evidence-driven investigation pipeline:

1. **Unified evidence ingestion** — All telemetry signals are normalised into a common evidence record format with stable IDs, UTC timestamps and source type labels.
2. **Structured timeline** — Events sorted by UTC timestamp with root-cause/decoy visual distinction and source/service filters.
3. **Interactive dependency graph** — Plain-SVG directed graph with health-coloured nodes, blast-radius highlighting and suspected origin marking.
4. **Anomaly detection display** — Sparkline trend charts, baseline vs. observed values, percentage deviation and plain-language "why abnormal" text.
5. **Competing hypotheses** — 3–4 root-cause hypotheses with animated confidence bars, supporting (green) and contradicting (red) evidence chips.
6. **Investigation planning** — Ordered checklist of steps showing which hypothesis each step tests.
7. **Tool invocation feed** — Terminal-style activity feed with tool signatures, results and linked evidence IDs.
8. **Confidence chart** — Recharts line chart tracking all hypothesis confidence scores across investigation steps.
9. **Impact assessment** — Stat tiles (users, error rate, latency, tickets, duration, blast radius) plus area chart.
10. **Ranked remediation** — Risk-labelled recovery options with rationale, prerequisites, rollback path and "Requires approval" tag.
11. **Human approval gate** — Approve/Reject with safety banner. Rejection proposes the next alternative.
12. **Replanning** — After new evidence, confidences update, revised plan and recommendation surface.
13. **Knowledge Base** — After resolution, a KB entry persists to localStorage. Second runs detect match and accelerate.

---

## 4. Key Features

### Implemented Features

| Feature | Description |
|---|---|
| **Incident Timeline Reconstruction** | Chronological vertical timeline, UTC timestamps, source type icons, clickable evidence chips, root-cause/decoy highlighting, source and service filters. |
| **Service Dependency Graph** | Interactive plain-SVG directed graph, health-coloured nodes, blast-radius highlighting, suspected origin marking, click-to-inspect node detail panel. |
| **Anomaly Detection Display** | Per-anomaly cards with severity, service, recharts sparkline, baseline vs. observed values, deviation % and "why abnormal" explanation. |
| **Multiple Root-Cause Hypotheses** | 3–4 competing hypothesis cards with animated confidence bars, supporting/contradicting evidence chips, status badges and expandable testable-prediction details. |
| **Investigation Planning** | 5-step ordered checklist, pending/running/done/skipped states, per-step hypothesis tested, expected output and completed evidence links. |
| **Tool / API Invocation Feed** | Terminal-style feed, tool signatures, fixture status, UTC timestamps, duration, record count, expandable evidence-chip results. |
| **Hypothesis Confidence Chart** | Recharts line chart tracking all hypothesis confidence scores across investigation steps. |
| **Impact Assessment** | Stat tiles (users, error rate, latency, tickets, duration, blast radius) plus dual-axis area chart. |
| **Remediation Recommendation** | Ranked options with risk level, recovery ETA, rationale, affected services, expected effect, prerequisites, rollback path and "Requires approval" tag. |
| **Human Approval Gate** | Approve/Reject buttons, safety banner, rejection-to-alternative flow, approval timestamp and actor label. |
| **Replanning Panel** | Triggered by new evidence. Shows new evidence, before/after confidence changes for all hypotheses, revised plan and revised recommendation. |
| **Evidence Drawer** | Right-side slide-over opening from any evidence chip anywhere in the UI. Shows ID, source type, UTC timestamp, service, raw content (monospace) and hypothesis relations. |
| **Evidence Explorer** | Searchable, filterable evidence table. Injected evidence hidden until demo arrival. |
| **Knowledge Base (localStorage)** | After resolution, KB entry persisted. Second-run acceleration and KB match banner implemented. Sidebar counter reflects KB count. |
| **Simulated Execution & Verification** | Progress bar animation followed by illustrative before/after area chart. |
| **9-State Investigation Machine** | idle → investigating → awaiting_approval → replanning → awaiting_revised_approval → executing → verifying → resolved → learned |
| **Searchable Incident Selector** | Sidebar dropdown of all five incident fixtures with severity, title, service and current stage. Selection persists to localStorage. |
| **Four AI Agent Cards (Simulated)** | Investigation, Detection, Remediation and Verification agent cards reflect the current demo stage. |
| **Dark and Light Themes** | Persistent theme toggle (nexus:theme). Applied before React renders to avoid flash. |
| **Responsive Layout** | Sidebar collapse/expand controlled by topbar. Narrow viewports start collapsed. Verified at 80%–125% zoom. |
| **Command Center** | /overview dashboard with incident summary, service health, metric tiles, approval panel and recent events. |
| **Reset Demo** | Clears Knowledge Base and resets all scenario states. |

### Simulated / Demo Features

| Feature | Status |
|---|---|
| AI agent confidence values | **Simulated** — Fixture values, no AI model invoked. |
| Tool / API invocations | **Simulated** — Derived from scenario evidence groups, no backend API called. |
| Anomaly detection | **Simulated** — Trend samples are scenario fixtures, not live statistical detection. |
| Execution and verification | **Simulated** — Local demo state only, no production request sent. |
| Audit records | **Session-local** — React state only, not in a durable audit log. |
| Knowledge Base persistence | **localStorage only** — Not server-side. |

### Not Yet Implemented (Planned / Backend-Dependent)

| Feature | Notes |
|---|---|
| Real LLM hypothesis generation | Requires backend with LLM API (Groq / OpenAI). |
| Live telemetry ingestion | Requires connectors to log aggregators, metrics systems, tracing platforms. |
| Real tool invocation | Requires backend agent orchestrator with read-only API access. |
| Durable audit trail | Requires backend audit service with authenticated write access. |
| Server-side Knowledge Base | Requires backend persistence layer. |
| Real recovery execution | Requires authorised backend workflows. |
| Automated test suite | No test runner configured in package.json. |

---

## 5. Multi-Agent Architecture

Four conceptual AI agent roles drive the investigation. In the current demo they are **simulated** — states are driven by the frontend state machine, not live AI inference. The architecture is designed so each role can be fulfilled by a real LLM-backed backend service when the data layer is connected.

### Investigation Agent

| Property | Detail |
|---|---|
| **Responsibility** | Evidence analysis and root-cause investigation |
| **Inputs** | All evidence records (logs, metrics, traces, alerts, deployments, configs, tickets, past incidents) |
| **Processing** | Reconstructs chronological timeline · generates competing falsifiable hypotheses · plans investigation steps · evaluates evidence against each hypothesis · updates confidence scores |
| **Outputs** | Timeline · hypothesis set with confidence scores and evidence links · investigation plan · step states · tool call results |
| **Demo status** | Active during `investigating` state · Completed when approval gate is reached |

### Detection Agent

| Property | Detail |
|---|---|
| **Responsibility** | Anomaly and metric monitoring |
| **Inputs** | Per-service metric time series and log streams |
| **Processing** | Identifies deviations from baseline · calculates percentage deviation · assigns severity labels · produces "why abnormal" explanations |
| **Outputs** | Anomaly list with sparkline trend data · baseline · observed value · deviation % · detected-at timestamp |
| **Demo status** | Active during `investigating` state alongside Investigation Agent |

### Remediation Agent

| Property | Detail |
|---|---|
| **Responsibility** | Recovery planning |
| **Inputs** | Confirmed or leading root-cause hypothesis · blast radius · Knowledge Base past incidents |
| **Processing** | Generates ranked recovery options · assigns risk level, ETA and rationale · identifies prerequisites and rollback paths · selects recommended option |
| **Outputs** | Ordered remediation list. Each option tagged "Requires human approval" |
| **Demo status** | Active during `executing` state after human approval |

### Verification Agent

| Property | Detail |
|---|---|
| **Responsibility** | Recovery and health validation |
| **Inputs** | Post-recovery metric samples · pre-incident baseline values |
| **Processing** | Compares post-action error rate and latency against baseline · determines resolution status · triggers replanning if verification fails |
| **Outputs** | Illustrative before/during/after verification chart · resolution determination |
| **Demo status** | Active during `verifying` state · Completed once scenario reaches `resolved` |

---

## 6. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      NEXUS AIOps Frontend                       │
│                 React 19 + Vite 8 + Tailwind CSS v4             │
├─────────────────┬───────────────────────────────────────────────┤
│ Sidebar         │              Main Workspace                   │
│ • NEXUS brand   │  /overview  →  Command Center (Dashboard.jsx) │
│ • Incident      │  /workspace →  ScenarioPage.jsx               │
│   selector      │    Sections: 01 Timeline  07 Confidence       │
│ • Nav links     │             02 Graph      08 Impact           │
│ • Agent cards   │             03 Anomalies  09 Remediation      │
│   (simulated)   │             04 Hypotheses 10 Approval Gate    │
│ • KB counter    │             05 Plan       11 Replan           │
│ • Footer        │             06 Tool Feed  KB Learned Panel    │
└─────────────────┴───────────────────────────────────────────────┘
         ↓                          ↓
 IncidentSelectionContext    useInvestigation.js (State Machine)
 • 5 fixtures                9 states: idle → … → learned
 • localStorage persist      Timer-driven section reveals
         ↓                          ↓
      DataSource Interface (src/services/dataSource.js)
          MockDataSource  ←→  localStorage (aiops:kb:v1)
         ↓
      Scenario Fixture Data Layer
      scenarios.js / scenarioSeed.js / scenarioSeedMore.js
      scenarioSeedLight.js / scenarioSignals.js
```

**Route map:**

| Route | Destination |
|---|---|
| `/` | Redirects to `/overview` |
| `/overview` | Command Center (Dashboard.jsx) |
| `/workspace?view=investigation` | Investigation Workspace |
| `/workspace?view=dependencies` | Dependency Graph |
| `/workspace?view=observability` | Observability |
| `/workspace?view=evidence` | Evidence Explorer |
| `/workspace?view=recovery` | Recovery & Approval |
| `/workspace?view=audit` | Audit History |
| `/scenarios/:scenarioId` | Selects fixture, redirects to workspace |
| `/incidents/:incidentId/*` | Legacy route, maps to matching fixture |

**No backend is connected.** The `DataSource` interface is the single swap point — replacing `MockDataSource` with an `APIDataSource` is the only change needed to connect a real backend.

---

## 7. Incident Investigation Workflow

| Step | Description | Status |
|---|---|---|
| 1. Incident selection | Searchable sidebar selector; selected incident becomes data context for all views. | ✅ Implemented |
| 2. Start investigation | Stopwatch starts; state → `investigating`. | ✅ Implemented |
| 3. Timeline reconstruction | Section 01 reveals first; events sorted by UTC timestamp. | ✅ Implemented (simulated) |
| 4. Dependency analysis | Section 02; nodes coloured by health; blast radius highlighted. | ✅ Implemented (fixture data) |
| 5. Anomaly detection | Section 03; sparklines, deviations, explanations. | ✅ Implemented (fixture data) |
| 6. Hypothesis generation | Section 04; 3–4 competing hypotheses with initial confidence values. | ✅ Implemented (fixture data) |
| 7. Investigation planning | Section 05; steps tick pending → running → done. | ✅ Implemented (simulated) |
| 8. Tool invocation | Section 06; tool calls stream in; evidence chips link to Drawer. | ✅ Implemented (simulated) |
| 9. Confidence chart | Section 07; hypothesis confidence trends over investigation steps. | ✅ Implemented (fixture data) |
| 10. Impact assessment | Section 08; error-rate/latency stats and area chart. | ✅ Implemented (fixture data) |
| 11. Remediation | Section 09; ranked options with risk, ETA and rationale. | ✅ Implemented (fixture data) |
| 12. Approval gate | Section 10; state → `awaiting_approval`; safety banner shown. | ✅ Implemented |
| 13. New evidence injection | Auto after 14 s (3 s on second run); manual button also available. | ✅ Implemented |
| 14. Replanning | Section 11; confidences update; revised plan shown; state → `awaiting_revised_approval`. | ✅ Implemented |
| 15. Human approval | Approve or Reject; rejection proposes next alternative. | ✅ Implemented |
| 16. Simulated execution | State → `executing`; progress bar animates to 100%. | ✅ Implemented (simulated) |
| 17. Simulated verification | State → `verifying`; before/after area chart shown. | ✅ Implemented (simulated, no backend) |
| 18. Resolution and learning | State → `resolved` → `learned`; KB entry saved to localStorage. | ✅ Implemented |
| 19. Second-run acceleration | KB match detected; banner shown; sections reveal instantly; confidence starts boosted. | ✅ Implemented |

---

## 8. Technology Stack

| Layer | Technology | Version | Role |
|---|---|---|---|
| **UI Framework** | React | ^19.3.1 | Component tree and rendering |
| **DOM Renderer** | React DOM | ^19.3.1 | Browser DOM management |
| **Routing** | React Router DOM | ^7.18.5 | Client-side routing |
| **Build Tool** | Vite | ^8.3.5 | Dev server and production bundler |
| **React Plugin** | @vitejs/plugin-react | ^6.1.2 | JSX transform |
| **Styling** | Tailwind CSS | ^4.3.3 | Utility CSS via @tailwindcss/vite plugin |
| **Design System** | src/index.css | — | CSS variables, dark/light theme, component classes |
| **Charts** | Recharts | ^3.10.1 | Line, area and sparkline charts |
| **Graph** | Plain SVG | — | Dependency graph (no D3) |
| **Icons** | Lucide React | ^1.64.0 | All UI icons |
| **Fonts** | Inter + JetBrains Mono | — | UI text and monospace/code |
| **Language** | JavaScript (JSX) | — | No TypeScript |
| **Storage** | localStorage | — | KB, theme, selected incident, demo stage |

---

## 9. Frontend Workspace Documentation

### Command Center (`/overview`)
Entry point. Shows active incident metric tiles (count, blast radius services, service health, approval gate type), featured incident panel (summary, sparkline, blast radius chips), recovery approval panel, service health list, investigation activity panel and recent events.

### Investigation Workspace (`/workspace?view=investigation`)
Primary view. ScenarioHeader (ID, severity, status, stopwatch, sources consulted, action buttons) + 11 progressive investigation sections + Evidence Drawer. Progress bar visible during `investigating` state. KB match banner on second run.

### Dependency Graph (`/workspace?view=dependencies`)
Section 02 in isolation. Plain SVG directed graph, health-coloured nodes, blast-radius highlighting, suspected origin marking, click-to-inspect node detail panel showing upstream/downstream connections.

### Observability (`/workspace?view=observability`)
Sections 03, 06 and 08 always fully revealed (not gated). Anomalies with sparklines, full tool call trace, impact stats and area chart.

### Evidence Explorer (`/workspace?view=evidence`)
Searchable, filterable evidence table. Search by title, service or evidence ID. Filter by source type and service. Any row click opens Evidence Drawer. Injected evidence hidden until demo arrival.

### Recovery and Approval (`/workspace?view=recovery`)
Sections 09 and 10 fully revealed. Full ranked remediation list with expandable details + Approve/Reject gate with safety banner.

### Audit History (`/workspace?view=audit`)
Section 06 (full tool trace) + Section 11 (replan panel if new evidence injected) + local approval/rejection record with actor label and timestamp.

---

## 10. Data Architecture

### Evidence Record Structure

```javascript
{
  id: string,           // Unique ID (e.g. "s1-DEP-02")
  type: string,         // log | metric | alert | deploy | config | trace | ticket | incident
  time: string,         // Human-readable time (e.g. "10:02")
  occurredAt: string,   // UTC ISO-8601 timestamp
  service: string,      // Originating service name
  title: string,        // Short description
  raw: string,          // Full raw content (monospace display)
  role: string,         // root | decoy | symptom | context | injected
  supports: string[],   // Hypothesis IDs this evidence supports
  contradicts: string[] // Hypothesis IDs this evidence contradicts
}
```

### Hypothesis Structure

```javascript
{
  id: string,                 // e.g. "H1"
  title: string,              // Plain-language hypothesis statement
  confidence: number,         // Current score 0.0–1.0 (fixture value)
  finalConfidence: number,    // Score after new evidence injection
  status: string,             // open | confirmed | rejected
  evidenceFor: string[],      // Supporting evidence IDs
  evidenceAgainst: string[],  // Contradicting evidence IDs
  explanation: string,
  testablePrediction: string,
  missingEvidence: string,
  nextAction: string
}
```

### DataSource Interface

```javascript
class DataSource {
  getScenarios()                       // Scenario[] (summary list)
  getScenario(id)                      // Full Scenario by ID
  getEvidence(scenarioId, evidenceId)  // Evidence by ID
  getKnowledgeBase()                   // KBEntry[] from localStorage
  addKBEntry(entry)                    // Persist new KBEntry
  clearKnowledgeBase()                 // Remove all KB entries
}
```

`MockDataSource` implements this interface synchronously from fixture data. A future `APIDataSource` would implement the same interface using `fetch` / `EventSource` / WebSocket without touching any component.

---

## 11. Human-in-the-Loop Safety

**Why approval is required:** Production recovery actions can have significant and irreversible consequences. No automated system should execute production mutations without an authorised human confirming the exact action, target and parameters.

**How the gate works:**
1. Remediation Agent proposes ranked options. Each is tagged "Requires human approval".
2. Approval Gate shows the selected option with risk, ETA, expected effect, affected services and rollback path.
3. Persistent safety banner: **"No action will run without your approval."**
4. Operator chooses Approve or Reject.
5. **Reject** → state shows "alternative proposed"; next option becomes candidate.
6. **Approve** → decision recorded locally (actor: "Local demo operator", timestamp: now). Simulated execution and verification sequence triggers. **No production request is sent.**
7. Approval timestamp and actor displayed in Approval Gate and Audit History.

**Demo limitations:** Decisions are session-local React state. The frontend cannot execute production recovery. Verification charts show fixture data only.

---

## 12. Installation and Setup

### Prerequisites

| Requirement | Version |
|---|---|
| Node.js | 18.x or later |
| npm | 8.x or later (bundled with Node.js) |

No backend, no API key, no `.env` file needed.

### Steps

```bash
# 1. Navigate to project directory
cd "C:\Users\DELL\OneDrive\Desktop\AIOps"

# 2. Install dependencies
npm install

# 3. Start development server
npm run dev
# Opens at http://localhost:5173 (or nearest available port)

# 4. Build for production
npm run build

# 5. Preview production build
npm run preview
```

---

## 13. Project Directory Structure

```
AIOps/
├── index.html                    Entry HTML
├── vite.config.js                Vite + React + Tailwind CSS v4
├── package.json                  Dependencies and scripts
├── target.md                     Original specification (unchanged)
├── context.md                    Full project context and notes
├── progress.md                   Iteration progress and verification log
│
├── public/
│   └── favicon.svg
│
└── src/
    ├── main.jsx                  Entry point; applies saved theme before render
    ├── App.jsx                   Router; IncidentSelectionProvider; all routes
    ├── index.css                 Dark design system (151 KB)
    │
    ├── context/
    │   └── IncidentSelectionContext.jsx   Global selected-incident state + persistence
    │
    ├── data/
    │   ├── scenarios.js              createScenario() builder; all 5 scenarios
    │   ├── scenarioSeed.js           Scenario 1 — Memory Leak (INC-2047) + UI labels
    │   ├── scenarioSeedMore.js       Scenarios 2 & 3 — DB Pool, Cache TTL
    │   ├── scenarioSeedLight.js      Scenarios 4 & 5 — TLS Expiry, Provider Outage
    │   ├── scenarioSignals.js        Anomaly sparkline data, impact series, verify data
    │   ├── scenarioToolExtras.js     Injected tool call entries
    │   └── mockIncident.js           Legacy INC-2847 fixture
    │
    ├── services/
    │   └── dataSource.js             DataSource interface + MockDataSource singleton
    │
    ├── hooks/
    │   └── useInvestigation.js       9-state machine; timer reveals; approve/reject; KB
    │
    ├── pages/
    │   ├── Dashboard.jsx             Command Center (/overview)
    │   ├── ScenarioPage.jsx          Investigation workspace (/workspace)
    │   └── IncidentPage.jsx          Legacy redirect
    │
    └── components/
        ├── Layout.jsx                App shell
        ├── Sidebar.jsx               Brand, incident selector, nav, agents, KB, footer
        ├── Topbar.jsx                Breadcrumb, theme toggle, search, collapse control
        ├── ScenarioHeader.jsx        Incident header, stopwatch, action buttons
        ├── ScenarioSections.jsx      All 11 investigation sections + Learned panel
        ├── EvidenceDrawer.jsx        Right-side slide-over evidence inspector
        ├── EvidenceExplorer.jsx      Searchable / filterable evidence table
        ├── Stopwatch.jsx             Live elapsed-time display
        ├── CommandPalette.jsx        Keyboard command palette
        └── ErrorBoundary.jsx         React error boundary
```

---

## 14. Demo Scenarios

### Scenario 1 — Memory Leak in inventory-service (INC-2047 · Critical)
**Root cause:** Unbounded `productCache` introduced in inventory-service v2.1.0  
**Evidence:** 14 records (1 injected heap dump log)  
**Hypotheses:** H1 Memory leak (confirmed 0.40→0.95), H2 Traffic spike (rejected), H3 Node pressure (rejected), H4 order-service regression (rejected)  
**Recommended fix:** Roll back inventory-service to v2.0.4

### Scenario 2 — DB Connection Pool Exhaustion (INC-2046 · Critical)
**Root cause:** payment-service v3.1.0 reduced `db.pool.maxSize` from 50 to 5  
**Evidence:** 12 records (1 injected config diff log)  
**Hypotheses:** H5 Pool misconfiguration (confirmed 0.35→0.93), H6 Postgres overloaded (rejected — DB CPU only 12%), H7 External gateway (rejected), H8 Transaction surge (rejected)  
**Recommended fix:** Restore `db.pool.maxSize` to 50

### Scenario 3 — Cache TTL Misconfiguration Drives DB Overload (INC-2045 · High)
**Root cause:** Redis product cache TTL changed from 3600 s to 5 s — cache miss storm  
**Evidence:** 11 records (1 injected config diff)  
**Hypotheses:** H9 Redis TTL misconfig (confirmed 0.30→0.92), H10 DB hardware failure (rejected), H11 Traffic spike (rejected), H12 Application regression (rejected)  
**Recommended fix:** Restore Redis TTL to 3600 seconds

### Scenario 4 — Expired TLS Certificate Blocks Authentication (INC-2044 · High)
**Root cause:** TLS certificate expired on auth-service at midnight  
**Evidence:** 5 records (lighter data set)  
**Recommended fix:** Renew and deploy TLS certificate

### Scenario 5 — Third-Party Payment Provider Outage (INC-2043 · Medium)
**Root cause:** External payment provider (Stripe) experiencing degradation  
**Evidence:** 5 records (lighter data set)  
**Recommended fix:** Enable fallback payment provider

### Running a Demo

```
1. npm run dev
2. Open browser at http://localhost:5173
3. Select incident from sidebar (default: INC-2047)
4. Click "Start investigation"
5. Watch sections reveal — click any evidence chip to open Drawer
6. When Approval Gate appears → "Approve (simulate)"
7. After new evidence injected → Replan Panel appears → "Approve (simulate)"
8. Scenario reaches Resolved → Learned; KB counter increments
9. Click "Re-run" to see second-run acceleration with KB match banner
10. Click "Reset demo" in header to clear KB and start fresh
```

---

## 15. Screenshots

No screenshots are currently committed to the repository.

To add them:
1. Run `npm run dev` and capture the following views:
   - Command Center — dark and light themes
   - Investigation Workspace — during `investigating` state
   - Service Dependency Graph
   - Evidence Drawer open over the Hypothesis section
   - Approval Gate with remediation panel
   - Replan Panel with confidence changes
   - Learned panel after resolution
2. Save to `docs/screenshots/`
3. Embed with `![Caption](docs/screenshots/filename.png)`

---

## 16. Implementation Status

*Verified 2026-10-31. Production Vite build passes — 2,634 modules transformed.*

| Area | Status | Notes |
|---|---|---|
| Vite dev server | ✅ Working | `npm run dev` starts successfully |
| Production build | ✅ Passing | 2,634 modules; `npm run build` verified |
| All 5 scenario fixtures | ✅ Complete | Full data for 1–3; lighter for 4–5 |
| 9-state investigation machine | ✅ Complete | All states implemented |
| Sidebar: brand, nav, selector | ✅ Complete | Search, select, persist |
| Sidebar: 4 agent cards | ✅ Simulated | State-driven display labels only |
| Command Center | ✅ Complete | All panels driven by selected fixture |
| Section 01 — Timeline | ✅ Complete | Filters, root/decoy/injected styling |
| Section 02 — Dependency Graph | ✅ Complete | SVG, health colours, interactive nodes |
| Section 03 — Anomaly Detection | ✅ Complete | Sparklines, deviations, explanations |
| Section 04 — Hypotheses | ✅ Complete | Animated bars, evidence chips, details |
| Section 05 — Investigation Plan | ✅ Complete | Step states, evidence links |
| Section 06 — Tool Feed | ✅ Complete | Terminal style, expandable evidence |
| Section 07 — Confidence Chart | ✅ Complete | Recharts line chart |
| Section 08 — Impact Assessment | ✅ Complete | Stats, area chart |
| Section 09 — Remediation | ✅ Complete | Ranked, expandable, risk labels |
| Section 10 — Approval Gate | ✅ Complete | Approve/Reject, banner, audit |
| Section 11 — Replan Panel | ✅ Complete | Confidence before/after, revised plan |
| Evidence Drawer | ✅ Complete | All fields, hypothesis relations |
| Evidence Explorer | ✅ Complete | Search, source/service filters |
| Recovery & Approval view | ✅ Complete | Full remediation + approval gate |
| Audit History view | ✅ Complete | Tool trace + local approval record |
| Knowledge Base (localStorage) | ✅ Complete | Persist, accelerate, count |
| Light and dark themes | ✅ Complete | Persistent, no flash on load |
| Responsive layout | ✅ Improved | Collapse, scrolling, zoom verified |
| Automated test suite | ❌ Not present | No test runner in package.json |
| Backend connectivity | ❌ Not connected | All data is local fixtures |
| Real LLM inference | ❌ Not implemented | No AI API calls in this build |
| Durable audit trail | ❌ Not implemented | Session-local state only |
| Real tool invocations | ❌ Not implemented | Simulated from fixture data |
| Backend recovery execution | ❌ Not implemented | Approval records demo decision only |

---

## 17. Important Disclosures

> **Offline demo.** No connection to any telemetry system, incident management platform, log aggregator, metrics database, tracing backend, deployment pipeline or cloud provider. All data is fixture data.

> **No real AI inference.** Hypothesis confidence values, tool call results, anomaly values, impact numbers and chart data are manually defined fixture values. No LLM, ML model or AI API is invoked.

> **Approval is not durable.** Approval decisions are session-local React state. Not authenticated, role-checked or written to a backend audit log.

> **No production action executes.** The frontend cannot send any command to a production system. All "Execute" or "Verify" behaviour is a local UI animation only.

> **Illustrative verification.** The before/after verification chart uses scenario fixture values, not real post-recovery telemetry.

> **Knowledge Base is not shared.** KB entries are stored per-browser in localStorage and are not available to other users or browsers.

---

## Contributing

1. Read `context.md` for full architectural context.
2. Read `target.md` for the original specification.
3. Implement a new `DataSource` subclass in `src/services/dataSource.js`.
4. Replace the `MockDataSource` export — no component changes required.
5. Add request loading states, abort/stale-response protection and server-error handling to the data source boundary.
6. Do not infer backend status from the local demo stage (`nexus:demo:stage`).

---

*NEXUS AIOps · Autonomous Incident Investigation, Root Cause Analysis and Intelligent Recovery.*
*Hackathon theme: AI for Tech · Domain: AIOps / SRE / Autonomous IT / Agentic AI / Observability.*