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

## The full source map (2026-07-16)

One table of everything that could feed the brain — live, planned, or merely
possible — so nothing is forgotten and priorities are visible at a glance.
Every row still passes the gate in `docs/ROADMAP.md` (weekly-use test first)
before any code is written. Pipelines: **BB#1** = synced memory-bank mirror,
**BB#2** = Telegram file-drop ingest (see Shared building blocks above).

| Source | What it holds | Pipeline | Status |
|---|---|---|---|
| Profile + facts | who he is, durable facts | native (`remember_fact`) | ✅ Live |
| Bot conversation log | every chat with the agent | native | ✅ Live |
| DayOS | journals, time blocks, notes, sessions, reviews | BB#1 (Firestore) | ✅ Live |
| Playbook + LEARNINGS | his rules, North Star, curriculum, lessons | BB#1 (git) | ✅ Live |
| Agent weekly digests | the AI's own weekly synthesis | native | 🔨 Built |
| WhatsApp chats | chosen conversations, snapshot-based | BB#2 | 🔨 Built |
| Wispr Flow dictations | everything voice-typed | Mac export → BB#2 | 🔨 Blocked on local Mac run |
| Claude Code conversations | insights/decisions distilled from his sessions across all projects | on-demand skill writes AI-condensed digest → git push → BB#1 mirror (new repo) | 💡 Idea, plan refined (entry below) |
| YouTube — tagged videos | transcripts/summaries of videos he *chooses* to keep (send link to bot = the tag) | link-drop pipeline (BB#2 sibling) | 🔨 Code built + tested offline (2026-07-16) |
| Google Drive notes | his Drive-synced notes | BB#1 (Drive API) | 📋 Planned (original Phase 2) |
| Gmail | email history — agreements, bookings, receipts, threads | BB#2 (Takeout .mbox) first; BB#1 (API) only if refresh cadence demands it | 💡 Idea (entry below) |
| Google Calendar | commitments, appointments, recurring blocks | BB#1 (ICS/API) | 💡 Idea (entry below) |
| Telegram personal chats | same value as WhatsApp, other half of his chat life | BB#2 (Telegram Desktop JSON export) | 💡 Idea (entry below) |
| Book/Kindle highlights | what he's read + marked | BB#2 (My Clippings.txt / Readwise CSV) | 💡 Idea (entry below) |
| Finance | bank/card statements, subscriptions, spending patterns | BB#2 (CSV/PDF statements) | 💡 Idea (entry below; privacy-heavy) |
| Health / sleep / workouts (raw) | Apple Health / fitness-app exports | BB#2 (Takeout/Health export) | 💡 Idea — overlaps Cadence; probably wait for Cadence |
| People file (CRM-lite) | who's who: context on friends, family, collaborators | hand-curated file, no pipeline | 💡 Idea (entry below) |
| Bookmarks / read-later | saved articles/links | BB#2 (browser/Pocket export) | 💡 Idea — weekly-use test doubtful, unranked |
| Trading journal(s) | trades, sizing, mistakes, P&L | BB#2 (CSV/broker export) | 💡 Idea, gated on product maturity (entry below) |
| Cadence (workouts) | training consistency vs. energy/focus | BB#1 + contract doc | 💡 Gated on product maturity |
| Meal-Planner | nutrition | BB#1 + contract doc | 💡 Gated on product maturity |
| Poker archive | hand histories, old poker journals | BB#2 | 💡 Legacy — only if he starts asking poker questions |
| YouTube / watch history (everything) | consumption patterns | BB#2 (Takeout) | ⏸️ Fails the weekly-use test — superseded by the *tagged videos* entry above |
| Location history | Google Timeline | BB#2 (Takeout) | ⏸️ Fails the weekly-use test; privacy cost > value |
| X/Twitter bookmarks | saved posts | BB#2 (data export) | ⏸️ Fails the weekly-use test today |
| Photos / voice binaries | media | — | 🚫 Excluded by standing decision (pointers only) |
| Other people's data | anything multi-user | — | 🚫 Excluded, hard line |

**Suggested order of attack** (after the already-built items go live on the
VPS): Gmail → Drive notes → Calendar → Telegram export → the rest as they
pass the gate. Rationale: Gmail and Drive answer the most real weekly
questions; Calendar is cheap; everything below is opportunistic.

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
5. Routine/scheduled pulls (the original ask) — built:
   `deploy/com.instatank.wispr-export.plist`, a macOS launchd LaunchAgent
   (the Mac-local equivalent of the VPS's systemd timers, since the DB never
   leaves the Mac). Defaults to every 6 hours; the plist's own header
   comment has the one-time setup commands and how to switch to a fixed
   daily time instead. Install this only after step 1-3 above confirm the
   script works against the real database.

### Gmail (email history) — 💡 Idea (added 2026-07-16)

**What:** searchable email archive — "when is the flight?", "what did the
landlord's last mail say?", "find the invoice from X". Likely the
highest-value unbuilt source: email is where agreements, bookings, and
receipts actually live.

**Likely approach:** start with **Google Takeout** (.mbox export of chosen
labels) through building block #2 — one `gmail_ingest.py` parser, zero new
auth, snapshot semantics like WhatsApp (re-export to refresh). Upgrade to a
BB#1 API mirror (read-only Gmail scope, OAuth) only if refresh frequency
proves annoying — that adds a Google Cloud project + token refresh machinery,
so earn it first.

**Needs before building:** which labels/senders matter (whole inbox is
noise + privacy risk — be selective like WhatsApp); one sample export to
design the parser against.

### Google Calendar — 💡 Idea (added 2026-07-16)

**What:** commitments and appointments, past and upcoming — pairs naturally
with DayOS ("what's my week look like?", "when did I last meet X?").

**Likely approach:** cheapest possible BB#1 mirror — Google Calendar's
private **ICS URL** (a secret link, no OAuth) pulled by the existing 2h
timer into `memory/calendar/`. Snapshot the next ~90 days + trailing year.

**Gate note:** passes the weekly-use test almost trivially, but check overlap
first — if DayOS already captures his schedule, this may add little.

### Telegram personal chats — 💡 Idea (added 2026-07-16)

**What:** the other half of his chat life (WhatsApp bank covers only
WhatsApp). Telegram Desktop → Settings → Advanced → Export chat data →
machine-readable JSON, per-chat.

**Likely approach:** building block #2, one `telegram_ingest.py` parser,
same snapshot-replaces semantics as WhatsApp. Note the pleasant irony: the
bot lives on Telegram but has no access to his other chats — export is the
only clean path, same privacy selectivity applies.

### Book / Kindle highlights — 💡 Idea (added 2026-07-16)

**What:** what he's read and marked — lets the agent connect his own
principles to what he's learning ("what did that book say about X?").

**Likely approach:** BB#2. Kindle's `My Clippings.txt` (plug in the Kindle,
copy one file) or a Readwise CSV export if he uses it. One parser module.

**Gate note:** only enters if he actually highlights while reading — ask
before building.

### Finance (statements + subscriptions) — 💡 Idea (added 2026-07-16)

**What:** bank/card statement CSVs and a subscription list — "what am I
paying for monthly?", "how much did June cost?", spend patterns vs. the
poker-brain instinct for EV.

**Likely approach:** BB#2 (statement CSV/PDF exports). **Privacy-heaviest
source on this list** — needs an explicit founder decision that financial
data may live on the VPS at all (even though the box is his and hardened).
Consider digest-only ingestion (monthly totals per category, not raw
transactions) as the lower-risk first version.

### People file (CRM-lite) — 💡 Idea (added 2026-07-16)

**What:** a hand-curated `memory/people.md` — who's who, context on family,
friends, collaborators ("remind me what Rahul does", "what did I promise
Priya?"). Cross-references WhatsApp/DayOS mentions.

**Likely approach:** no pipeline at all — either grow it via the existing
`remember_fact` tool (a `## People` section in profile.md) or a dedicated
file the founder edits. Cheapest possible source; the question is curation
habit, not code.

### Claude Code conversations — 💡 Idea, plan refined 2026-07-16

**What:** the founder's LLM session history — a lot of thinking, decisions,
and derived insights live only inside Claude Code conversations (he uses
the desktop app for Code sessions + plain chat + Cowork, not the terminal).
Goal: "what did we figure out about X in that session last month?"
answerable from the brain.

**Where the data actually lives — two axes, not one:** *product* (Code vs.
plain chat vs. Cowork) crossed with *execution location* (session running
against the founder's own Mac filesystem, vs. a cloud/remote sandbox —
this very drafting session is an example of the latter: an ephemeral
container, nothing touches his Mac). Only local-execution Claude Code
sessions leave a file on his Mac (`~/.claude/projects/**/*.jsonl`); plain
chat and Cowork are cloud-stored regardless, and remote/cloud Code sessions
leave nothing local either. **Which mode his desktop-app sessions run in is
something only he can check** (does the app show picking "this Mac" vs. a
sandbox/environment?) — not assumed, not yet verified.

**Rejected approach:** a Mac-local `claude_export.py` walking raw JSONL
(the Wispr Flow pattern) — raw transcripts are ~90%+ tool-call/file-dump
noise; the signal is a handful of decisions and insights in the prose, and
mechanical filtering can't reliably separate them. Also Mac-only, so it
would miss every remote/cloud-executed session (including sessions like
this one).

**Chosen approach — condense at the source via a skill, ship over git
(works local or remote, sidesteps the execution-location question
entirely):**
1. A Claude Code **skill** (`.claude/skills/save-to-brain/SKILL.md`) run
   on-demand (`/save-to-brain`) at the end of a session worth keeping.
   Claude itself — with full session context already in hand — writes a
   tight markdown digest: topic, key decisions, insights derived, open
   threads. Same philosophy as `digests.py`'s AI-authored weekly synthesis,
   applied per-session instead of per-week.
2. The skill's last step: commit the digest and `git push` to one
   dedicated collection repo (new, lightweight — e.g.
   `instatank/session-digests` — not coupled to any one project's
   lifecycle, since sessions span many repos). This works identically
   whether the session executed on his Mac or in a cloud sandbox, since
   both have git access — no export step, no Telegram upload, no Mac-only
   constraint.
3. VPS side: reuse `playbook_sync.py`'s git-mirror mechanism verbatim,
   pointed at the new repo instead of time-tracker — same 2h timer, same
   staleness pattern. New bot tools: `search_session_digests`,
   `session_digest`.
4. **Trigger stays on-demand, not automatic, for now** — confirm-first,
   matching WhatsApp/YouTube: the founder decides what's worth keeping,
   so the digest repo stays high-signal instead of filling with dead-end
   debugging sessions. Upgrade path if wanted later: a Stop hook checked
   into a repo's `.claude/settings.json` auto-fires the same skill in
   every session against that repo, local or remote — an add-on, not a
   redesign.

**The distilled layer already flowing:** per the playbook's own rules,
the *highest-value* fraction of session insights already lands in
LEARNINGS.md / docs / CLAUDE.md, which already reach the brain via the
playbook bank. This integration adds a searchable per-session layer
underneath, at finer grain and without waiting for something to earn a
LEARNINGS entry.

**Open items before building:**
- [ ] Founder: check the desktop app to determine local vs. remote
      execution mode for his Code sessions (informs whether an automatic
      Stop-hook upgrade could ever reach 100% local coverage; doesn't
      block the on-demand skill either way).
- [ ] Founder: name/create the destination repo for digests.
- [ ] One-time: verify whether claude.ai's data-export includes plain
      chat / Cowork history, if those are ever wanted too (lower priority
      — Code sessions carry the technical insight density).

### YouTube — tagged videos — 🔨 Code built + tested offline (2026-07-16); awaiting VPS `git pull` + first real link

**What:** NOT watch history (that stays ⏸️ — fails the weekly-use test).
This is *deliberate capture*: the founder tags a specific video and its
transcript (or at minimum a summary) enters the brain. "What was that
video about position sizing I saved?"

**Built (2026-07-16, offline-tested + handler flows driven with fake
Telegram objects):**
- `youtube_ingest.py` — link detection (watch/youtu.be/shorts/live/embed/
  music URL shapes), oEmbed metadata fetch (robust path), caption-track
  scrape off the watch page + json3 → timestamped markdown paragraphs
  (best-effort path, every failure mode mapped to a plain-language reason),
  snapshot writer `memory/youtube/videos/<video-id>.md` + raw caption JSON
  under `memory/youtube/raw/` + `sync_status.json`. Re-sending a link
  replaces the entry. Text around the link = the founder's note, saved
  with the video. Zero Anthropic cost (no model call in the pipeline).
- Bot flow: YouTube link in any message → intercepted before Claude (the
  link IS the tag; costs no tokens) → fetch → preview + confirm-first
  buttons. Transcript fetched → **Add to brain**/Discard; fetch failed →
  **"I'll paste a summary"**/Discard, next message stored as the summary
  (marked `manual summary`, never passable as a transcript).
- `youtube_store.py` + tools `search_youtube` / `youtube_video`; save
  failures ride the health banner; prompt note lists recent saves.
- `tests/test_youtube.py` — offline (HTTP seam faked): link shapes, track
  preference (manual>ASR, en>hi>other), rolling-caption dedup, degrade
  paths, replace semantics, store reads/search, banner, tool gating.

**Added same day (founder asks, 2026-07-16):**
- **Paste-the-full-transcript fallback** alongside paste-a-summary (video
  page → ⋯ → Show transcript → copy); entries are labeled by how the text
  arrived (`transcript` / `pasted_transcript` / `summary`) so a summary can
  never masquerade as a transcript.
- **Batch messages:** several links in one Telegram message → one combined
  fetch + a single "Add N to brain" button; unfetchable ones are listed for
  individual re-send.
- **DayOS learning-log auto-fetch** (`youtube_autofetch.py` + daily
  `youtube-autofetch.timer` 06:30 IST + a scan on every `/sync`): links
  logged in DayOS's learning sessions page are fetched and saved with NO
  confirmation and NO notification — the founder's explicit decision
  (ROADMAP decision log 2026-07-16); logging the link is the tag. Failure
  policy: per-video fetch failures retry across 3 runs then park
  (visible in `/sync` and `--status`, deliberately not on the ⚠️ banner);
  a crashed run does hit the banner. Watched location: the mirror's
  `learning.md` only — widening it is a one-line change (`WATCHED`).

**Honest caveat:** the transcript scrape is validated against the known
watch-page format, NOT against live YouTube — this repo's sandbox proxy
blocks youtube.com, so the first real fetch happens on the VPS. If YouTube
blocks the VPS's IP too, the failure is loud and the summary fallback is
the designed path (deploy/DEPLOY.md § 9b).

**Still needs:** VPS `git pull` + restart (no new config, no new timer),
then share any YouTube link to the bot and press the button.

**Design notes (as built):** the tag = sharing the URL to the bot (Share →
Telegram → bot, two taps from the YouTube app) — no playlists, no YouTube
account plumbing. Transcript fetch is a hand-rolled stdlib scrape (oEmbed
for metadata + watch-page caption tracks; deliberately no
youtube-transcript-api/yt-dlp dependency — same raw-HTTP ethos as
`dayos_client.py`, and those libraries break against IP blocks just the
same). Optional future polish: a one-call Haiku TL;DR atop each stored
transcript (~a cent) so search hits read better.

**Gate check:** passes — the tag action itself proves intent; nothing
enters without him choosing it, so every stored video is by definition
something he expected to ask about.

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
