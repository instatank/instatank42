# SECOND_BRAIN — strategy + roadmap (plan of record)

**Status: PROPOSED 2026-07-12 — awaiting founder confirmation.** Decision points are
marked ⚖️. Once confirmed, this doc is the plan of record that
`time-tracker/docs/second-brain-integration.md` already points to.

---

## 1. What the second brain is (and isn't)

Two components, deliberately separate:

- **The agent** (this repo's Telegram bot) — the mouth and ears. It talks, it remembers
  conversation facts, it enforces budget caps. Phase 1, code complete.
- **The second brain** — the memory layer *behind* the agent: read-only mirrors of the
  founder's real data (DayOS first), his accumulated principles (the shared playbook),
  and the bot's own distillations. Background plumbing, no UI of its own.

The agent without the brain is a chatbot with a diary of its own chats. The brain without
the agent is a folder nobody can talk to. They ship in that order: **mouth first, then
memory, then proactivity.**

## 2. Where things stand (reality check, 2026-07-12)

1. **The contract exists; the consumer doesn't.** `time-tracker/docs/second-brain-integration.md`
   defines exactly what this repo's sync job reads from DayOS's Firestore — but `dayos_sync.py`
   has not been written. This doc closes the other dangling pointer.
2. **The bot is not deployed.** Phase 1 is code-complete and smoke-tested, blocked only on
   founder-owned steps: Hetzner VPS, BotFather token, separate Anthropic API key.
3. **NORTH_STAR tiers this repo "4 — Parked (undeployed)."** Actively building the second
   brain contradicts that. Per the founder's own rules: revival needs a `BUILD_BRIEF` and a
   tier decision (⚖️ §8).
4. **The second-richest corpus is already free to ingest.** The playbook + LEARNINGS ledgers
   are plain markdown in git — mirroring them is a `git pull`, not a pipeline.

## 3. Design principles (each traces to a playbook rule/lesson)

1. **Read-only by construction, not by promise** (contract §"How the consumer connects").
   The service account never gets write scope. The bot never writes to DayOS or any other
   product's data — the duplicate-allergy lesson (L3) applied at the architecture level.
2. **Mirrors and thoughts never mix.** Synced mirrors are disposable, regenerable artifacts;
   everything the bot *authors* (digests, notes) lives in its own lane. One-way flow, no
   merge logic, no sync contract on the brain side.
3. **Fail loud, stale loudly** (Rule 4). Every source gets a heartbeat (last-sync timestamp).
   A `/brain` command reports sync ages; if a mirror is stale beyond threshold, answers that
   used it carry a one-line warning. A silently stale brain confidently answering from old
   memories is the worst failure mode this system has.
4. **Deterministic, date-keyed file names** (L3) — `brain/dayos/2026-07-12.md`. Re-running a
   sync overwrites the same file; duplicates are impossible rather than detected.
5. **IST everywhere** (L4 + contract invariant 2). String-comparable IST dates are what make
   cheap incremental pulls work. `memory.py` already does this; the sync job follows.
6. **Plumbing is free; thinking costs money.** Sync jobs make zero LLM calls. Tokens are
   spent only on digests and answers, inside the existing `DAILY_CAP_USD`.
7. **Every source earns its place through a gate** (§7). No speculative pipelines.
8. **Never fork the playbook — pull it** (playbook/README rule). The brain holds a git
   checkout, not a copy that rots.

## 4. Memory layout (proposed)

```
memory/
  profile.md              # identity + durable facts (exists)
  sessions/               # bot's own conversation logs (exists)
  usage/                  # spend tracking (exists)
  brain/
    _status.json          # heartbeat: {source: last_sync_iso} — read by /brain
    dayos/
      days/2026-07-12.md  # one file per day: blocks, journal, captures, DFT, ratings, EOD
      weeks/2026-W28.md   # weekly review + rollup
      months/2026-07.md   # monthly review
      learning.md         # learning entries (append-ordered)
      projects/<slug>.md  # per-project sessions + project notes
    playbook/             # read-only git checkout: time-tracker/playbook + LEARNINGS.md
    digests/              # bot-AUTHORED distillations — the only writable brain lane
```

Context loading: today + yesterday's day-files ride along by default (mirrors the existing
2-day session-notes window); everything older is reached by a grep/file-read tool on demand.
No embeddings — settled decision; revisit only after naming three real queries grep failed.

## 5. Roadmap — ranked phases with timelines

| # | Phase | When | Effort | Why this position |
|---|---|---|---|---|
| 0 | **Deploy the mouth** + brief/tier decisions | this week | ~30 min founder + 1 session | Everything downstream is invisible without a live bot. Hard blocker, founder-owned. |
| 1 | **DayOS mirror** (`dayos_sync.py`) | week 1–2 | 1–2 sessions | Richest structured source; contract already written; the benchmark feature. |
| 2 | **Principles layer** (playbook + LEARNINGS via git) | week 2–3 | 1 session | Cheapest source, outsized value: turns a diary-reader into a coach that quotes the founder's own rules. |
| 3 | **Distillation + retrieval quality** | week 3–4 | 1–2 sessions | Digests + query-time retrieval tuning; only meaningful once real data flows. |
| 4 | **Proactive loops** | week 4–6 | 1–2 sessions | Morning brief / evening nudge / Friday synthesis via Telegram. Last, because proactive + wrong = uninstalled. |
| 5 | **Widen sources by gate** | month 2+ | on demand | Google Drive notes (original Phase 2), other repos' handoffs, other apps' data — each through §7's gate. |

### Phase 0 — deploy + decide (blocker)
- Founder: Hetzner signup, BotFather token, separate API key (`deploy/DEPLOY.md`).
- Session: run deploy, verify the Phase-1 benchmark (daily use, facts persist across days).
- Founder + session: fill `playbook/templates/BUILD_BRIEF.md` for the second brain
  (10 minutes, conversational) and settle the tier (⚖️ §8).
- **Done means:** bot answers on his phone; a fact told today is known tomorrow; `/spend` works.

### Phase 1 — DayOS mirror (smallest slice first)
- `dayos_sync.py` exactly per the contract: service-account JWT → Firestore REST,
  recent-window pull every ~2h + full re-pull daily, systemd timer on the same VPS.
- Slice 1: **days/ only, last 7 days** — prove the pipe end-to-end. Then widen to weeks/
  months/learning/projects.
- Heartbeat + fail-loud from the first commit, not retrofitted. `/sync` command for a manual
  pull ("I just logged something, refresh").
- **Done means:** "what did I do yesterday?" and "what's pending on <project>?" answered
  correctly from real data — and with the network deliberately cut, the bot *says* its
  memory is stale instead of silently answering from old files.

### Phase 2 — principles layer
- Read-only clone of `instatank/time-tracker` on the VPS; `brain/playbook/` points at
  `playbook/` + `LEARNINGS.md`; refreshed by the same timer (`git pull`).
- Later: other repos' `LEARNINGS.md` as they earn it.
- **Done means:** "what's my rule about renames?" quotes L5; "what's this week's technique?"
  reads CURRICULUM correctly.

### Phase 3 — distillation + retrieval
- Weekly digest: one scheduled Sonnet call (cents) writes `digests/2026-W28.md` — patterns,
  deltas, open loops. Digests are the bot's opinion and labeled as such.
- Retrieval order per question: today/yesterday in context → grep on demand → digests for
  month-scale questions. Measure context size; keep answers inside the 1000-token cap.
- **Done means:** "how did the last month go?" gets a grounded answer without blowing
  context or budget.

### Phase 4 — proactive loops (trust must precede this)
- Morning brief (DFT, today's default blocks, pending tasks), evening nudge (journal
  unfilled by ~10pm), Friday weekly-synthesis delivery — LEARNING_METHOD §5 arriving *at*
  the founder instead of waiting to be pasted (his own push-notification lesson, applied
  to himself). Haiku-priced, count-capped, one-command mutable (`/quiet`).
- **Done means:** the Friday summary shows up unprompted and he acts on it (CURRICULUM
  item 10's own test).

### Phase 5 — new sources, case-by-case
Ranked candidates when the time comes: **Cadence** (workouts pair with DayOS energy/ratings)
> **BillBud** (money questions are plausible weekly asks) > **TradeGenie** (trading rules —
`profile.md` may be enough) > SignalDesk / Meal-Planner (low) > **PartySpark: never**
(other people's data — see §6).

## 6. Deliberately excluded (ranked by how firmly)

1. **Other people's data** (PartySpark users, anything multi-user). The brain is one
   person's life. Hard line, not a phase.
2. **Write access to any product's data.** Read-only forever; the bot's writable world is
   `memory/` only (systemd hardening already enforces this).
3. **Voice/photo binaries.** Contract already excludes them — titles/filenames as searchable
   pointers only. Transcription stays in the founder's external tool → DayOS text.
4. **Source code of the repos.** The brain wants decisions, lessons, and state — LEARNINGS,
   handoffs, and docs carry that; `index.html` does not.
5. **Vector DB / embeddings / Mem0.** Settled decision. Files + grep at personal scale;
   the founder can open his own brain in a text editor and read it — that's a feature.
6. **Real-time sync.** A diary tolerates 2h staleness; live listeners buy complexity, not
   value. `/sync` covers the "just logged it" case.
7. **Dashboards / web UI.** Original Phase 3 stance stands: only when asked. Telegram is
   the interface.
8. **Full chat-history context.** 2-day window + digests. History is grep-able, not
   context-resident.

## 7. The gate for any new source (print this, use it every time)

1. **The weekly-use test:** name a question the founder would actually ask the bot about
   this data in a normal week. Can't name one → doesn't enter.
2. **A contract doc** in the producer repo (the `second-brain-integration.md` pattern):
   collections/fields/invariants, updated in the same commit as any schema change.
3. **Read-only credentials**, a heartbeat entry, deterministic file naming.
4. **One source per session** (Rule 1) — never two pipelines in one change.

## 8. ⚖️ Founder decision points

1. **Tier.** Options: **(a)** promote instatank42 to Tier-1 flagship for ~6 weeks,
   temporarily demoting PartySpark to Tier 2 (max-2-flagships rule stands) — honest if the
   second brain is now the main build focus, as this initiative implies; **(b)** Tier 3
   "special" like UoT — its own rules, no flagship displacement, but then CURRICULUM
   exercises don't run here. Recommendation: **(a)**, revisited at the first monthly review.
2. **BUILD_BRIEF.** Ten minutes, next session, conversational. This doc pre-fills most of it.
3. **Proactive cadence** (Phase 4): morning + evening + Friday, or Friday only to start?
   Recommendation: Friday-only first; earn the daily slots.
4. **Which track this trains** (for the brief): S — first real producer/consumer pipeline
   across two systems (the whiteboard-able system CURRICULUM item 12 wants); O — first VPS,
   systemd, timers, no Vercel guardrails; D — context engineering: deciding what memory
   enters the model, when, at what cost.

## 9. Don'ts (the failure modes this plan is designed against)

- Don't build any brain code before the bot is deployed and the benchmark passes.
- Don't re-litigate settled architecture (files over vector DB, model routing, hosting).
- Don't give the sync job write scope "temporarily."
- Don't copy playbook files into this repo — pull them.
- Don't let a sync failure be quiet — no heartbeat, no ship (Rule 4).
- Don't start proactive messaging before retrieval is trusted — annoying kills the habit
  faster than useless does.
- Don't add a source without its contract doc and gate answers (§7).
- Don't let digests edit mirrors — the bot's opinions never overwrite the founder's data.
