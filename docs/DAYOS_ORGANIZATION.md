# DayOS in the second brain — the organization plan

*Written 2026-07-16 from the founder's ask: organize DayOS entries in the
second brain into an intelligent system that maximizes insight for minimal
effort. This is the plan of record for how the DayOS bank gets smarter.
`SECOND_BRAIN.md` stays the architecture for memory banks in general; this
doc is specifically about what shapes the DayOS data takes and why. Status:
proposed — nothing below is built yet.*

## The idea in one paragraph

Everything DayOS knows already reaches the brain — the problem is not
*access*, it is *shape*. Today the mirror organizes his life along two axes
(time: days/weeks/months, and projects) plus one AI-written weekly
synthesis. But several of the most valuable questions cut *across* those
axes — "show me all my insights this quarter", "what did I say I'd do and
never did?", "is deep work trending up?", "what keeps recurring in my
life?" — and today they cost either many file reads or come back as
scattered search snippets. The fix is a small set of **new views over the
same data**, almost all of them mechanical (zero AI cost, rebuilt on every
sync, deletable and regenerable from raw), plus one more rung on the AI
distillation ladder so insight compounds week → month → standing themes.
Nothing new to log, no schema changes, no new sources — more insight out of
data he already produces.

## The four layers (how to think about it)

| Layer | What | Cost | Status |
|---|---|---|---|
| 0 · Raw | `raw/*.json` — exact Firestore copy | $0 | ✅ exists |
| 1 · Lenses | mechanical views: by time ✅, by project ✅, **by tag, open loops, numbers table** | $0 (pure code in the existing sync) | rest = **Phase A** |
| 2 · Distillation | the AI's opinion lane in `memory/digests/`: weekly ✅, **monthly + standing themes** | ~$0.02 per call | rest = **Phase C** |
| 3 · Ambient | what rides in every prompt: today+yesterday ✅, **week pulse + open loops** | ~100 tokens/msg | **Phase B** |

Standing rules across all layers (unchanged from `SECOND_BRAIN.md`): every
Layer-1 file is a pure function of raw — delete it and the next sync
rebuilds it identically; Layer 2 is clearly labeled opinion and never
overwrites a mirror; the agent never writes to DayOS.

## What today's shape can't answer well

| Question he'd actually ask | Today | After this plan |
|---|---|---|
| "What did I do Tuesday?" / "How was my week?" / "Where's project X?" | ✅ already one tool call | unchanged |
| "Show me all my #insights / #wins from June" | search returns 3-line snippets across many hits | one read of `tags/insight.md`, full text |
| "What did I say I'd do that's still pending?" | scattered across day files and sessions | one read of `open-loops.md`, sorted oldest-first |
| "Is deep work trending up? Do good days follow training?" | walk many week files, mental math | one read of `metrics.csv` |
| "How did June go? What keeps recurring?" | weekly digests exist but nothing rolls them up | monthly synthesis + `themes.md` |

## Phase A — the missing lenses (mechanical, zero ongoing cost)

All three are new outputs of `dayos_digest.build_all()` — same sync, same
timers, no new services, no model calls.

**A1. Tag views — `tags/<tag>.md`.** One file per tag that matters: the
four special tags (`#win`, `#insight`, `#1%`, `#dft`) always, plus any tag
used ≥5 times (auto-detected, so his vocabulary grows the bank without
config). Each file holds every entry carrying that tag — full text, not a
snippet — newest first, each line dated and labeled by origin (journal /
capture / session / learning / block). Turns "all my insights from June"
into one read that arrives as a document, not a pile of fragments.

**A2. Open-loops ledger — `open-loops.md`.** Everything he said he'd do
that isn't done, in one file, grouped by age (this week / last 30 days /
older): unchecked Daily-Journal tasks, `pending[]` items from each
project's *latest* session, today's DFT if still pending (older pending
DFTs auto-skip in the app, so they're history, not loops). Every line
carries the date it was written; the oldest stares back first. Items
vanish automatically at rebuild once done in the app. Probably the highest
insight-per-effort file in the whole plan — it's the "what am I dropping?"
view, and it becomes a better input to the weekly synthesis than the
per-day scraps it reads today.

*Honest caveat:* a journal task he did but never ticked stays "open" —
the data can't know. The age buckets make that tolerable: an old open item
deserves a look either way (do it or delete it).

**A3. The numbers table — `metrics.csv`.** One row per day: hours by
category, total logged, day rating, each check-in metric, DFT status, wins
count. A machine-readable spine for every trend and correlation question —
"is deep work trending up?", "do ratings follow training days?" become one
file read plus arithmetic instead of walking N rollups. Also the exact
input Layers 2 and 3 need for honest deltas.

**Wiring:** the new files join the existing search corpus, and one new
read tool — working name `dayos_view` — exposes them: `dayos_view("open
loops")`, `dayos_view("#win")`, `dayos_view("metrics")`. One tool, many
views, so the bot's tool list stays small.

## Phase B — ambient awareness (the prompt pulse)

Two lines added to the system-prompt snapshot (which already carries
today + yesterday):

- **Week pulse:** `This week so far 14.5h (Deep Work 6.0 · Learning 3.5)
  vs last week 18.2h` — computed from `metrics.csv` at snapshot time.
- **Open loops:** `5 open loops, oldest 12 days: "renew lease"` — the top
  of the ledger.

Roughly 100 extra tokens per message, placed after the prompt-cache
breakpoint with the rest of the volatile context. This is what makes the
bot feel *aware* without being asked — it can notice "you're 4h behind
your usual deep work and that lease task is 12 days old" in ordinary
conversation instead of waiting for the right question.

## Phase C — the distillation ladder grows one rung

- **Monthly synthesis** — `memory/digests/months/YYYY-MM.md`. Once a
  month, one Sonnet call reads the month's 4–5 weekly syntheses + the
  month rollup + the previous monthly, and writes the month's story:
  trajectory, real deltas, patterns-of-patterns, the biggest open loop.
  Delivered on Telegram like the Friday digest. ~$0.02/month, same budget
  guards as `digests.py` (cap-checked, loud on failure).
- **Standing themes — `memory/digests/themes.md`.** The same monthly run
  maintains a compact list of recurring patterns ("leak days follow short
  sleep", "ships in bursts after planning resets") with first-seen /
  last-seen dates — a theme enters after showing up in two monthlies,
  retires when it stops appearing. This file is the closest thing the
  brain gets to *knowing him from data*, and it's what "what are my
  patterns?" reads.

Why the ladder stops at week/month grain: distilling every entry or every
day with AI would cost real money, mostly restate the mechanical lenses,
and bury signal in noise. Patterns live at week-and-up; that's where the
model spends. Total AI cost of this whole plan: ≈ $1.50/year.

## The app (front-end) side — deliberately almost nothing

The strongest property of this plan: **every phase derives from fields
DayOS already stores** (tags, tasks, pending lists, ratings, categories,
reviews). No new logging habits, no schema change, no contract-doc churn.

- Tags are load-bearing for A1 — and the app already makes them cheap
  (pills, tag history, the #win panel). His existing habits are enough.
- The review processes stay exactly as they are. Reviews and their
  `aiSummary` already flow into the mirror; Layer 2 reads them rather
  than replacing them.
- One hygiene note for *later, over in time-tracker, not part of this
  plan*: the app's two tag tokenizers diverge on some inputs
  (`docs/tag-search-notes.md` there). Tags becoming more load-bearing
  raises the value of unifying them — worth folding in whenever tag code
  is next touched.

## Deliberately not doing (standing decisions apply)

- No embeddings / vector DB — the bar stays where Phase 1 set it.
- No AI pass over every entry (auto-categorize, sentiment, etc.) — cost
  and noise; the mechanical lenses answer those questions for free.
- No new capture burden on the founder — if a view would need him to log
  something new, it doesn't belong in this plan.
- No writes to DayOS, no new Firestore collections, no app redesign.
- No new sources here — that's `BACKLOG.md`'s lane.

## Order, effort, done-means

| Phase | Build effort | Ongoing cost | Done means |
|---|---|---|---|
| A — lenses | one session | $0 | "all my insights from June" = one tool call with full text; "what's still pending?" answers with ages |
| B — pulse | half a session (can ship with A) | ~100 tokens/msg | the bot brings up the week pulse or a stale loop unprompted, when relevant |
| C — ladder | one session | ~$0.25/yr | "how did June go?" answered from the monthly; "what are my patterns?" from `themes.md` |

A → B → C, in that order: `metrics.csv` powers the pulse, and the weekly
syntheses power the monthly. Each phase is independently useful; stopping
after A is a fine outcome.

## Founder questions (answer whenever — none block Phase A)

1. **Tags:** beyond the four specials, any tags that should always get a
   view? (The ≥5-uses auto-threshold covers the rest.)
2. **Open loops:** how far back should unchecked journal tasks count as
   open — 30 days? 60?
3. **Monthly delivery:** 1st of the month, or first Friday (bundled with
   that week's digest)?
4. **Later rung:** want a quarterly synthesis once two or three monthlies
   exist, or is monthly + themes enough?
