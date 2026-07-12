# Second Brain — integrations backlog

*Living tracking doc for every "hook this data source into the agent" idea —
built, planned, or half-formed. Read this at the start of any session that
touches the agent's memory architecture. Update status + date whenever
something moves. This is the task list; `docs/SECOND_BRAIN.md` is the
architecture (how memory banks work in general, why files-not-embeddings, the
DayOS integration in full detail).*

## How to use this doc

- Every new integration idea gets an entry here, even before it's scoped —
  capturing "we'll want trading journals eventually" costs one line and saves
  it from being forgotten.
- Statuses: 💡 Idea (mentioned, not scoped) · 📋 Planned (scoped, waiting on
  priority or owner input) · 🔨 Building · ✅ Live · ⏸️ Parked (considered and
  set aside, with why).
- Before starting a new integration, check **Shared building blocks** below —
  if two entries need the same plumbing (e.g. both are manual file exports),
  build the shared piece once and club the work, per the founder's steer.
- When something ships, move it to ✅ Live with the date and a one-line
  pointer to where the detail lives (usually `docs/SECOND_BRAIN.md` for
  architecture-level integrations).

## Shared building blocks (reuse across integrations)

Infrastructure that more than one integration needs. Build once, reuse.

1. **Memory-bank pattern** (established by DayOS, `docs/SECOND_BRAIN.md`) —
   read-only mirror into `memory/<source>/`: organized markdown + raw copy,
   a `sync_status.json` with loud staleness warnings, search/day/period-style
   read tools. The default shape for any *recurring, syncable* data source
   (has an API, a database, or a feed).
2. **Telegram file-drop ingestion** (not yet built) — the bot accepts a
   document upload from Ankit, saves it, runs a source-specific parser, and
   merges the result into a `memory/<bank>/` directory. The default shape for
   any *manual export* data source (no API, just periodic file dumps).
   Needed by: WhatsApp exports now; likely trading journal exports too if
   they turn out to be file-based (CSV/broker statement/PDF) — worth
   building the generic upload→parse→merge pipeline once, then adding a thin
   per-source parser for each.
3. **Cross-bank search** — one tool that greps every memory bank at once.
   Trivial once 2+ banks exist; deferred until then to keep the tool list
   small (noted in `docs/SECOND_BRAIN.md`).

## Integrations

### DayOS (time tracking + journaling) — ✅ Live (2026-07-07; founder-verified in production 2026-07-12)

Journals, activity blocks, notes, project sessions, learning log, trends,
weekly/monthly reviews. Read-only Firestore mirror (building block #1).
Full detail: `docs/SECOND_BRAIN.md`, contract doc
`time-tracker/docs/second-brain-integration.md`.

### Shared playbook + LEARNINGS (the principles layer) — 🔨 Code built + tested (2026-07-12); awaiting VPS setup (`deploy/DEPLOY.md` step 8)

**What:** the founder's accumulated working rules and lessons — the
`playbook/` folder in `instatank/time-tracker` (PLAYBOOK, NORTH_STAR,
CURRICULUM, LEARNING_METHOD, SOPs) plus each repo's `LEARNINGS.md` ledger —
mirrored read-only into `memory/playbook/`, so the agent can quote his own
rules back at him, knows the technique-of-the-week, and can coach against
his own principles.

**Pattern:** the simplest bank yet — a `git clone` + periodic `git pull` on
the VPS (the playbook is already plain markdown in git; no API, no parser,
no cost). Standard sync-status file + staleness warnings + a read/search
tool. Never fork a copy — pull it (playbook README rule).

**Needs (all that's left):** the founder's 5-minute VPS setup — a
fine-grained GitHub token (Contents:read on time-tracker only) + two `.env`
lines + first sync. Walkthrough: `deploy/DEPLOY.md` step 8.

### WhatsApp chat history — 📋 Planned

**What:** a searchable archive of important WhatsApp conversations, so the
agent can answer "what did we agree with X about Y" from real chat history.

**Decided approach:** manual chat exports (WhatsApp's own *Export chat*
feature → `.txt` file, no media), sent to the bot as a Telegram file upload
and ingested automatically. This is a snapshot, not live — re-export a chat
when you want it refreshed (e.g. monthly, or before asking about something
recent).

**Rejected approaches:**
- *Live/automatic sync via unofficial libraries* — impersonates WhatsApp
  Web; violates WhatsApp's ToS and risks a ban on the personal number.
  Bad EV: saves manual exports, risks losing WhatsApp entirely. Rejected
  2026-07-07.
- *WhatsApp Business API* — only captures messages through a business
  number going forward; can't reach personal chat history. Doesn't fit.

**Needs:**
- Building block #2 (Telegram file-drop ingestion) — not yet built.
- A WhatsApp export parser: the exported `.txt` format is a fixed, well-known
  line shape (`[DD/MM/YY, HH:MM:SS] Sender: message`, multi-line messages
  continue without a new timestamp) — should be a small, mostly-mechanical
  parser once ingestion exists.
- Per-contact/group memory files under `memory/whatsapp/`, split by
  month like DayOS's `days/`, reusing the same search tool shape.

**Open question (resolve before building):** should the bot auto-ingest any
`.txt` file it receives as a WhatsApp export, or confirm first ("looks like
a WhatsApp export for 'X' — add it to the brain?")? Leaning toward
confirm-first — safer default, and it's the first file-upload feature so
worth being conservative.

**Privacy note:** exports contain the other party's messages too. Be
selective about which chats get fed in.

### Trading journal(s) — 💡 Idea

**What:** not yet scoped — flagged as a future integration during the
WhatsApp discussion, no detail captured yet.

**Founder steer (2026-07-12):** the trading products (TradeGenie etc.) are
themselves works-in-progress — mature the product first, feed it in later
(the feeder-products principle in `docs/ROADMAP.md`).

**Needs before this can move to 📋 Planned** (ask the founder when we pick
this up):
- What system/format the journal(s) live in today (spreadsheet, broker
  export, a trading app's own export, hand-written notes)?
- What questions should the agent be able to answer from it (win rate over a
  period, biggest mistakes, position sizing patterns, correlation with
  DayOS energy/focus data)?
- One sample export/file to design the parser against.

**Likely shared plumbing:** if the journal turns out to be file-based
exports (CSV, broker statement PDF, spreadsheet download), this probably
reuses building block #2 (Telegram file-drop ingestion) — same pattern as
WhatsApp, different parser. Worth building the ingestion pipeline with both
in mind rather than bespoke to WhatsApp only.

### Google Drive notes — 📋 Planned (original Phase 2 scope)

**What:** read access to Ankit's Drive-synced notes via grep/file search —
this was scripted from the start as "Phase 2" in `CLAUDE.md`'s architecture
decisions, before the DayOS/WhatsApp/trading-journal ideas existed.

**Pattern:** building block #1 (memory-bank pattern) — read-only mirror,
no embeddings unless plain search demonstrably fails.

**Status:** unstarted, no blockers besides prioritization against the other
entries here.

### Cadence (workouts) — 💡 Idea, gated on product maturity

**What:** workout/consistency data pairing naturally with DayOS energy and
day ratings ("does training correlate with my focus hours?").

**Founder steer (2026-07-12):** Cadence is "very basic and a work in
progress" — build the product out first, feed it in once it's in better
working condition. When it matures: memory-bank pattern (building block #1),
plus a contract doc in the Cadence repo like DayOS's.

### Meal-Planner — 💡 Idea, gated on product maturity

**What:** not yet scoped. Same founder steer as Cadence (2026-07-12): the
current version is dated; mature it first, then evaluate through the gate in
`docs/ROADMAP.md` (weekly-use test before anything else).

## Parked

*(Nothing parked yet beyond the rejected sub-approaches noted inline above.)*
