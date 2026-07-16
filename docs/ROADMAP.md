# Second Brain — roadmap + founder decision log

*The phased plan and its live status. Update statuses here whenever a phase
moves. Division of labor between the three docs: `SECOND_BRAIN.md` = the
architecture (how memory banks work, the DayOS integration in detail);
`BACKLOG.md` = the per-source integration tracker; this doc = the phases,
their order and why, and the decisions the founder has made.*

*Written 2026-07-12 from the strategy session; statuses reconciled against
what was actually built and deployed.*

---

## The phases, ranked

| # | Phase | Status | Notes |
|---|---|---|---|
| 0 | Deploy the bot | ✅ **Done** (founder-confirmed 2026-07-12) | Live on the VPS, in daily use. |
| 1 | DayOS memory bank | ✅ **Live** (built 2026-07-07; founder-verified in use 2026-07-12) | One residual task below. |
| 2 | Principles layer — playbook + LEARNINGS | ✅ **Live** (founder-verified 2026-07-12) | Bot quotes actual playbook rules. |
| 3 | Distillation — AI weekly synthesis | 🔨 **Code built + tested** (2026-07-12) | `digests.py` + `weekly_digest` tool + `/digest`. Live after server `git pull` + `setup_vps.sh` re-run. |
| 4 | Proactive loops — Friday delivery | 🔨 **Code built + tested** (2026-07-12) | `weekly-digest.timer`, Fri 18:00 IST, failures messaged to Telegram. Friday-only per founder decision; morning/evening nudges stay unbuilt until Friday earns it. |
| 5 | New sources, by gate | 🔁 Ongoing | Tracked per-source in `BACKLOG.md`; gate below. First source through: **WhatsApp chat history** — 🔨 code built + tested 2026-07-12 (plus the shared file-drop ingestion pipeline, building block #2). Live after VPS `git pull` + first export upload. |

### Phase 1 residual — the staleness drill

The one verification-checklist item worth confirming explicitly (item 5 in
`SECOND_BRAIN.md`): deliberately stop the sync timer (or break the key) for a
day, ask a DayOS question, and confirm **the bot itself warns** that its data
is stale — then fix it and confirm the warning clears. This proves the
silent-failure defense actually fires. Ten minutes, one-time.

### Phase 2 — principles layer (playbook + LEARNINGS)

- Read-only `git clone` of `instatank/time-tracker` on the VPS; mirror
  `playbook/` + `LEARNINGS.md` into `memory/playbook/` following the standard
  memory-bank pattern (sync status file, staleness warnings, a read/search
  tool). Refresh via the same timer cadence (`git pull` — no API, no cost).
- Why it's next: cheapest possible source (already plain markdown in git) with
  outsized value — it turns the bot from a diary-reader into a coach that can
  quote the founder's own rules back at him and knows the technique-of-the-week
  from `CURRICULUM.md`.
- Later, other repos' `LEARNINGS.md` files join the same bank as they earn it.
- **Done means:** "what's my rule about renames?" quotes playbook L5;
  "what's this week's technique?" reads CURRICULUM correctly.

### Phase 3 — distillation + retrieval quality

- What exists: `dayos_digest.py` writes *mechanical* rollups (days/weeks/
  months/projects) — organized restatements of the data.
- What this phase adds: an **AI-authored weekly distillation** (one scheduled
  Sonnet call, cents) into `memory/digests/` — patterns, deltas, open loops,
  clearly labeled as the bot's opinion, never overwriting mirrors.
- Plus retrieval tuning: measure what actually gets loaded per question type;
  keep answers inside the token caps. No embeddings — the standing bar:
  revisit only after naming three real questions plain search failed on.
- **Done means:** "how did the last month go?" gets a grounded answer without
  blowing context or budget.
- **Extension proposed 2026-07-16:** `docs/DAYOS_ORGANIZATION.md` — the
  founder asked for smarter organization of the DayOS bank itself. Adds
  mechanical lenses (tag views, open-loops ledger, `metrics.csv`), a
  week-pulse ambient line, and a monthly-synthesis + standing-themes rung
  on top of this phase's weekly one. Awaiting founder review.

### Phase 4 — proactive loops (trust must precede this)

- Start: **Friday weekly synthesis only** (founder decision 2026-07-12) —
  the weekly review from `playbook/LEARNING_METHOD.md` §5 arriving *at* him
  on Telegram instead of waiting to be pasted. His own DayOS push-notification
  lesson, applied to himself.
- Morning brief / evening journal nudge come later, only if Friday earns its
  keep. Haiku-priced, count-capped, one command to silence.
- **Done means:** the Friday summary shows up unprompted and he acts on it.

## The gate for any new source (use it every time)

1. **The weekly-use test:** name a question the founder would actually ask
   about this data in a normal week. Can't name one → doesn't enter.
2. **A contract doc** in the producer repo (the
   `time-tracker/docs/second-brain-integration.md` pattern) if the source is
   another of his products: collections/fields/invariants, updated in the
   same commit as any schema change over there.
3. **Read-only access**, a sync-status file with loud staleness warnings,
   deterministic date-keyed file names.
4. **One source per session** — never two pipelines in one change.

## The feeder-products principle (founder steer, 2026-07-12)

Several of his products are themselves works-in-progress (**Cadence** —
workout system, very basic today; **Meal-Planner** — dated version;
**TradeGenie** and the other trading products). The steer: **mature the
product first, feed it in later.** These get built out over time and join the
brain once they're in better working condition — each through the gate above,
each with its own contract doc. Don't build speculative pipelines to
half-built sources; the brain grows source-by-source as the portfolio matures.

## Deliberately excluded (standing decisions)

1. **Other people's data** (PartySpark users, anything multi-user) — hard
   line, not a phase. The brain is one person's life.
2. **Write access to any product's data** — the bot's writable world is
   `memory/` only; it never writes to DayOS or any other source.
3. **Voice/photo binaries** — titles/filenames as searchable pointers only.
4. **Repo source code** — the brain wants decisions, lessons, and state;
   LEARNINGS + handoffs + docs carry that.
5. **Vector DB / embeddings** — settled; files + grep until three named
   real-world failures say otherwise.
6. **Dashboards / web UI** — Telegram is the interface until asked.

## Founder decision log

| Date | Decision | Detail |
|---|---|---|
| 2026-07-12 | **Tier: instatank42 → Tier 1 (stop-gap)** | Flagship while second-brain work is the active focus; he expects to work on it in bursts between maturing the feeder products (Cadence, Meal-Planner, TradeGenie...). Revisit at the first monthly review — NORTH_STAR's tier table (in time-tracker) still says Parked and needs updating there. |
| 2026-07-12 | **BUILD_BRIEF filled + approved** | Saved at repo root (`BUILD_BRIEF.md`); founder approved same day. |
| 2026-07-12 | **`main` branch created** | Founder-approved; all prior `claude/*` branches merged into it. Sessions merge to `main` before ending. Default-branch flip in GitHub settings still owed by founder (one click). |
| 2026-07-12 | **Proactive cadence: Friday-only first** | Daily briefs must be earned by the Friday loop proving useful. |
| 2026-07-12 | **DayOS mirror approach confirmed** | Founder: "the mirror idea for time tracker/dayos sounds good to me" — matches what was built. |
| 2026-07-16 | **YouTube links in the DayOS learning log auto-fetch SILENTLY, daily** | The one deliberate exception to confirm-first ingestion: logging a link in his own learning log is already the act of curation, so no Telegram confirmation and no success notification (option 2 of the fork offered; also his call that every-2h would be overkill — daily + on-`/sync` instead). Run crashes still hit the ⚠️ banner; per-video fetch failures retry 3× then park, visible in `/sync`. |

## Open items

- [ ] Run the Phase-1 staleness drill (checklist item 5) once — with the
      health banner it now shows on ANY message while a bank is broken.
- [x] Phase 2: playbook/LEARNINGS bank — LIVE, founder-verified 2026-07-12.
- [x] Phases 3+4 code: weekly synthesis + Friday delivery — built + tested
      2026-07-12.
- [ ] Founder: pull Phases 3+4 onto the server (`git pull` + re-run
      `setup_vps.sh` to install the new timer), then send `/digest` to see
      the first synthesis.
- [ ] Founder: after the same `git pull` + restart, try the first WhatsApp
      ingest — WhatsApp → chat → Export chat → **Without media** → share the
      file to the bot → press "Add to brain" (walkthrough:
      `deploy/DEPLOY.md` step 9). Phase 5's first source goes live with that
      button press.
- [ ] Founder: same `git pull` + `setup_vps.sh` re-run also enables YouTube
      tagging (built 2026-07-16; the re-run installs the daily auto-fetch
      timer) — share any YouTube link to the bot, or just log one in the
      DayOS learning page and `/sync` (walkthrough: `deploy/DEPLOY.md`
      § 9b). First real link also answers whether transcript fetch works
      from the VPS's IP or the paste fallbacks are the norm.
- [ ] Founder: review `docs/DAYOS_ORGANIZATION.md` (the DayOS organization
      plan — tag views, open-loops ledger, metrics table, monthly synthesis
      + themes) and answer its four questions; Phase A can be built as soon
      as the plan is approved.
- [ ] Update `NORTH_STAR.md` tier table in time-tracker at the next monthly
      review (instatank42: Parked → Tier 1 stop-gap; PartySpark → Tier 2 for
      the duration).
- [x] Create a `main` branch merging all prior work — done 2026-07-12.
- [ ] Founder: flip the repo's default branch to `main` (GitHub → Settings →
      General → Default branch). One click; until then, fresh clones still
      land on the stale first branch.
- [x] Auto-sync GitHub Action added (2026-07-12, founder-approved) —
      `claude/*` pushes now merge to `main` automatically, same as
      time-tracker.
