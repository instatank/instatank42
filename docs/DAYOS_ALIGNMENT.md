# DayOS ⇄ 2nd brain alignment

**Why this doc exists.** The founder asked (2026-07-16): what can we
modify/build/add/remove in DayOS — especially the **Trends page, Reviews,
dashboard, and data-analysis** parts — so that *both* products get better and
more efficient: DayOS itself **and** the second brain that reads it? Plus an
aside: *where does all the second brain's data actually live? I don't see it.*

This is the plan of record for that alignment: the storage answer, what shipped
this session, and the decision menu (all approved — see the log at the bottom).

---

## The storage answer (the aside — answered first, because it matters most)

Everything the second brain knows lives as **plain files on the Hetzner VPS**,
under one directory:

```
/opt/instatank-agent/memory/
├── profile.md                  facts the bot has learned about you
├── sessions/                   the bot's own conversation logs (last 2 days fed back in)
├── usage/                      daily spend (JSON)
├── dayos/                      the DayOS mirror (rebuilt from Firestore every 2h)
│   ├── days/ weeks/ months/ projects/ tags/
│   ├── metrics.csv  open-loops.md  never-closed.md  learning.md  index.md
│   └── raw/                    exact Firestore snapshot (rebuild source)
├── playbook/repo/              a git checkout of the time-tracker repo
├── whatsapp/chats/…            uploaded WhatsApp exports
├── youtube/videos/…            saved YouTube transcripts
└── digests/                    the bot's OWN weekly/monthly syntheses + themes
```

You don't *see* it because it's **deliberately gitignored** — the code repo
(`instatank42`) ships the *program*, the server holds the *data*. Two different
things on purpose: the data is personal and some of it is huge.

**Where the source of truth is** (this is the key mental model):

| Bank | Lives on the VPS as | Rebuildable if the VPS dies? |
|---|---|---|
| DayOS | mirror of **Firestore** (Google's cloud) | ✅ yes — re-syncs from Firestore |
| Playbook | git checkout of **time-tracker** | ✅ yes — re-clones |
| WhatsApp / YouTube / pasted notes | the only copy | ❌ **no — gone forever** |

That last row is why the **backup** below matters, and it's the honest answer to
"I don't see it": until now, the non-rebuildable banks existed in exactly one
place you couldn't look at.

**Future sources** land beside these as new folders on the same VPS —
`memory/gmail/`, `memory/drive/`, `memory/calendar/`. Wispr dictations live on
your Mac (`~/WisprFlowExports/`) until uploaded. Claude Code session digests
live in the `instatank/2ndbrain` repo (the `sessions/` lane) and mirror in like
the playbook.

---

## What we found looking at both sides

- **All the Trends analytics are computed on the fly and never saved.** Deep-work
  hours, adherence %, leak rate, skipped hours, streaks, week-over-week deltas —
  DayOS recomputes them every time you open the Trends page and throws them away.
  The brain was re-deriving only a *thinner* slice (hours / rating / check-in /
  DFT / wins) and couldn't answer "is my adherence trending up?"
- **Reviews already save the good stuff** — a saved Weekly Review carries its six
  tile totals, star averages, surfaced patterns, and your next-week intention;
  the brain mirrored those but rendered them as a flat key:value dump, and they
  only reached the AI synthesis buried inside a size-capped blob.
- **A real bug:** Weekly Reviews were written to the cloud but never read back —
  a review made on your phone never appeared on your laptop, and vanished on a
  fresh device. (Monthly reviews were fine; weekly was missing its loader.)
- **No backup + no visibility** for the non-rebuildable banks — the aside above.

---

## What shipped this session

### In DayOS (`instatank/time-tracker`, SW v137)
1. **Fixed the weekly-review sync bug** — reviews now sync both ways across
   devices (added the missing loader + wired it into every sync path).
2. **Open Loops on the Weekly Review** — a live "everything I said I'd do that
   isn't done" list (unchecked journal tasks + a project's latest pending items +
   today's focus task), the same ledger the brain builds, now shown *at the
   source* so you can actually close loops there.
3. **Unified the two tag parsers** — typing `#side-project` and picking
   "side-project" from the menu now store the *same* tag. Tags drive the brain's
   per-tag views and win counts, so this quietly fixes both products.
4. **Fixed trashed entries** lingering under a project for up to 7 days.

### In the second brain (`instatank/instatank42`)
5. **Trends-grade `metrics.csv`** — the per-day numbers file now also carries
   **adherence %, task completion, leak %, and skipped hours**, computed the same
   way DayOS computes them (the brain replicates DayOS's adherence engine on the
   mirrored data — zero DayOS change needed, since the rules were already synced).
   The bot can now answer the same trend questions the Trends page shows.
6. **Reviews read as first-class data** — weekly/monthly reviews render as
   labelled sections (intention, snapshot, patterns, portfolio calls…) instead of
   a dump, and the AI weekly/monthly syntheses now get last period's stated
   intention **explicitly**, so a digest can say *whether last week's plan
   actually happened*.
7. **Honest week pulse** — the ambient "this week vs last week" line compares
   *the same days* of last week (Sun–Tue vs Sun–Tue), not a partial week against
   a full one, so early-week pulses stop reading as a fake drop.
8. **Nightly backup + visibility mirror** — see below.

---

## The backup (your "I don't see it" fix)

**Decision: a nightly push of the whole `memory/` tree to your new private repo
`instatank/2ndbrain`.** It solves both problems at once:

- **Backup:** the WhatsApp/YouTube/pasted banks now survive a VPS loss.
- **Visibility:** you can browse your brain's actual files on GitHub — or, since
  you mentioned Obsidian, **clone the repo into an Obsidian vault** and read the
  whole thing as linked notes on any device.

How it's built (`memory_backup.py` + `memory-backup.{service,timer}`, 03:30 IST):
it copies `memory/` into a `memory/` subfolder of the repo, leaving the repo's
existing `sessions/` lane (your Claude Code session digests) untouched. It skips
rebuildable git-mirror checkouts (no point backing up a copy of another repo),
commits only when something changed, and messages you on Telegram if a backup
ever fails. The GitHub token is read from `.env` and never written to disk.

> Obsidian note: point a vault at a local clone of `2ndbrain` and pull when you
> want to read. Treat it as **read-only** — the VPS overwrites `memory/` each
> night, so notes you *add* belong in DayOS or a different vault folder, not
> inside the mirrored `memory/`.

---

## The rest of the menu (all approved 2026-07-16)

Tiers 1 + 2 + 3A were approved and everything above is Tier 0/1/3A **shipped**.
Tier 2 (DayOS product changes) items 2–4 above are the ones already done; the
remaining Tier-2/3 candidates, for when you want them:

- **Tier 2 — remaining:** none outstanding from the original list (open loops,
  tag unification, and the trash fix all shipped this session).
- **Tier 3B — voice-note transcription in DayOS** (not built; needs its own
  scoping). Today the brain only sees voice-note *titles*. If DayOS transcribed
  voice notes to text on the entry, that text would flow to the brain
  automatically (the contract already treats added fields as safe). Real
  cost/effort — revisit deliberately.

**Deliberately NOT doing** (respects the settled decision log): quarterly
rollups (monthly + themes is enough), embeddings/vector search (plain search
works), persisting Trends' derived analytics as new Firestore collections
(recomputable data + sync-checklist risk — the reviews already snapshot what
matters at save time), and a separate web dashboard for the brain (Telegram
until asked).

---

## Decision log

- **2026-07-16** — Founder approved **Tier 1 + Tier 2 + Tier 3A**. For 3A, chose
  a **private GitHub repo** over Google Drive/rclone, and created
  **`instatank/2ndbrain`** as the target (also noting he may read it via an
  **Obsidian** vault). Backup mirrors into that repo's `memory/` subfolder,
  coexisting with its `sessions/` (session-digest) lane.
- The DayOS-side Firestore contract was updated the same session
  (`time-tracker/docs/second-brain-integration.md`): weekly/monthly review
  fields enumerated; `meta/adherence` marked as now-consumed by the metrics lens.
