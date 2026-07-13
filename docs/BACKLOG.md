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
2. **Telegram file-drop ingestion** — ✅ **Built** (2026-07-12, `ingest.py`):
   the bot accepts a document upload (.txt or .zip, 8 MB cap), asks every
   registered parser to recognize it, shows a preview, and only writes to the
   brain after an explicit "Add to brain" button press (confirm-first — the
   open question below, resolved). The default shape for any *manual export*
   data source (no API, just periodic file dumps). Adding a future source
   (trading-journal CSVs, broker statements) = one new parser module with the
   `PARSER` contract at the top of `ingest.py`, added to `ingest.PARSERS` —
   the pipeline itself shouldn't need to change. First consumer: WhatsApp.
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

### WhatsApp chat history — 🔨 Code built + tested (2026-07-12); awaiting VPS `git pull` + first export

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

**Built (2026-07-12, offline-tested):**
- Building block #2 (`ingest.py`) — see above.
- `whatsapp_ingest.py` — parser (both Android `12/06/26, 9:15 pm - X: msg`
  and iOS `[12/06/26, 21:15:33] X: msg` dialects, multi-line messages,
  system lines, day-first dates unless the file proves month-first) + bank
  writer: `memory/whatsapp/chats/<chat>/YYYY-MM.md`, one paragraph per day,
  raw export kept under `memory/whatsapp/raw/`. Each ingest is a **snapshot
  that fully replaces that chat's earlier one** — no merging, no dedup;
  re-export whenever a refresh is wanted.
- `whatsapp_store.py` + bot tools `search_whatsapp` / `whatsapp_chat` —
  every result carries each chat's coverage line ("covers to <date>") so a
  June export can never pass as live data; ingest failures ride the health
  banner like every other bank.

**Still needs:** the founder pulls the code onto the VPS (`git pull` +
restart, no new config), then WhatsApp → chat → Export chat → *Without
media* → share the .txt/.zip to the bot → press "Add to brain".

**Open question — resolved (2026-07-12):** confirm-first, as leaned. The bot
never ingests silently; it previews what it detected and waits for a button
press.

**Privacy note:** exports contain the other party's messages too. Be
selective about which chats get fed in.

### Wispr Flow dictation history — 🔨 Code built + offline-tested (2026-07-13); blocked on a local Mac run

**What:** a full-text archive of everything dictated through Wispr Flow
(voice-to-text), so the agent can search past dictations the way it searches
WhatsApp chats or the playbook.

**Why it's stuck at this status:** the session that scoped this ran in
`instatank42`'s cloud/remote Claude Code environment, which has no
filesystem link to the founder's actual Mac — Wispr Flow's SQLite database
only exists there. The session could not locate the DB, inspect its real
schema, or run the export against real data (all explicitly required before
the script can be trusted). It built and offline-tested the script's logic
against a synthetic fixture instead, and stopped short of claiming this is
done.

**Built (2026-07-13, offline-tested only):**
- `wispr_export.py` — standalone script (deliberately has zero dependency on
  `bot.py`/the venv — stdlib only) that: locates the DB (`~/Library/Application
  Support/*wispr*` first, broad `~` search as fallback), copies it via
  SQLite's online-backup API through a read-only source connection (never
  touches the live file itself, survives Wispr Flow having it open), prints
  the real schema, and guesses which table/columns hold dictation text vs.
  timestamp vs. app vs. word count vs. duration by keyword matching — saved
  to `.schema_map.json` for the founder (or a local session) to eyeball and
  correct. Output: `~/WisprFlowExports/full-history.json` (every column,
  nothing dropped) + `full-history.md` (grouped by date, newest first).
  Incremental via `.last_export.json`; `--full` forces a clean re-pull.
  Handles the Core-Data-vs-Unix-epoch timestamp ambiguity common in Swift
  apps by testing candidate epochs against "is this plausibly recent" rather
  than assuming one.
- `tests/test_wispr_export.py` — synthetic SQLite fixture (deliberately
  non-obvious column names, plus a decoy table) proves the schema-guessing
  logic and incremental/full-re-pull dedup work correctly. This validates
  the *mechanism*, not real Wispr Flow data — that still needs a real run.

**Still needs (a local Claude Code session on the actual Mac):**
1. Run `python3 wispr_export.py --inspect-only` to see Wispr Flow's real
   schema and confirm the guessed table/column mapping in
   `~/WisprFlowExports/.schema_map.json` is right (fix by hand if not).
2. Confirm the detected timestamp format (printed in the run summary) is
   correct — wrong epoch guess silently produces wrong dates.
3. Run a real export, sanity-check a handful of entries in `full-history.md`.
4. Decide how the export feeds the brain: reuses building block #2
   (Telegram file-drop `ingest.py`, like WhatsApp — upload `full-history.md`
   manually or on a schedule) is the natural fit since the DB is Mac-only
   and unreachable from the VPS; a new `wispr_ingest.py` parser module would
   be the only new code needed on the bot side.
5. If routine/scheduled pulls are wanted (the original ask): a `launchd`
   job on the Mac running `wispr_export.py` on a schedule, since there is no
   VPS-side equivalent (the DB never leaves the Mac).

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
exports (CSV, broker statement PDF, spreadsheet download), this reuses
building block #2 (Telegram file-drop ingestion) — now built (2026-07-12)
with exactly this in mind: a trading-journal source is one new parser
module implementing the `PARSER` contract, nothing more.

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
