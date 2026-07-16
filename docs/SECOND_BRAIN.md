# The Second Brain — memory architecture for the personal agent

*Written 2026-07-07. This is the plan of record for how the agent's backend
memory works and how external data systems (starting with DayOS) plug into it.
Plain-English first; implementation notes where they matter.*

## The idea in one paragraph

The agent's "second brain" is not one database — it is a small set of
**memory banks**, each one a folder of plain text files under `memory/` on the
server. The bot reads them with simple tools (open a file, search for words).
Anything can become a memory bank if it can be turned into organized text
files. DayOS is the first external system wired in; Google Drive notes are
next (that was already Phase 2); more can follow. No vector database, no
embeddings — plain files and search, upgraded only if that demonstrably fails.

## Memory bank inventory

| Bank | Where | Status | What it holds |
|---|---|---|---|
| Profile + facts | `memory/profile.md` | live (Phase 1) | Who he is; durable facts the agent saves via `remember_fact` |
| Conversation log | `memory/sessions/*.md` | live (Phase 1) | Dated log of every bot conversation; last 2 days fed as context |
| **DayOS** | `memory/dayos/` | **live** (2026-07) | Journals, activity blocks, captures/notes, project sessions, learning log, ratings, reviews — his whole logged life |
| **Playbook** | `memory/playbook/` | **live** (2026-07-12) | Read-only git mirror of his cross-project rules, lessons, North Star, curriculum, LEARNINGS ledger (tools: `search_playbook`, `playbook_doc`) |
| **Agent digests** | `memory/digests/` | **built** (2026-07-12; monthly + themes added 2026-07-16) | AI-written weekly syntheses, monthly syntheses (the 5th), and a standing themes file — the agent's own opinion lane; written Fridays / the 5th (or `/digest`, `/digest month`), never overwrites mirrors; read via the `digest` tool |
| **WhatsApp** | `memory/whatsapp/` | **built** (2026-07-12) | Manual chat-export snapshots, ingested via Telegram file upload with confirm-first buttons (tools: `search_whatsapp`, `whatsapp_chat`); each re-export replaces that chat's snapshot |
| **YouTube** | `memory/youtube/` | **built** (2026-07-16) | Tagged videos only (send a link to the bot = the tag): transcript or pasted summary per video, confirm-first (tools: `search_youtube`, `youtube_video`); re-sending a link replaces the entry |
| Drive notes | `memory/drive/` (future) | planned | His Google-Drive-synced notes, mirrored read-only the same way |
| Spend | `memory/usage/*.json` | live (Phase 1) | Cost accounting (not model-visible) |

The pattern every future bank must follow (this is the contract):

1. **Read-only pull** — the agent never writes back into the source system.
2. **Local plain-text mirror** — organized markdown the model can read raw;
   an exact `raw/` copy kept alongside so digests can always be rebuilt.
3. **A sync process with a status file** — and loud staleness warnings when
   the mirror is old or the last sync failed. Silent staleness is the enemy.
4. **Tools, not context-stuffing** — a compact ambient snapshot in the system
   prompt; everything else fetched on demand so cost stays capped.

Manual-export banks (WhatsApp is the first) follow the same contract with one
substitution: there is no sync process to go stale, so instead of timer-based
staleness warnings, **every tool result carries each snapshot's coverage
date** ("covers to 2026-06-30") — the equivalent loud defense against stale
data passing as current. Ingest failures still ride the health banner via the
same `sync_status.json` shape.

## Where the second brain is stored (the Obsidian / Google Drive question)

**Canonical copy: on the agent's VPS, as plain files.** The brain has to live
where the thinking happens — the bot greps local files in milliseconds, with
zero API cost, zero network dependency in the read path, and zero new failure
modes. This is also just Phase 1's settled Karpathy-style-files decision
extended to more data.

Three things make this safe and flexible:

- **Firestore stays the source of truth for DayOS data.** The VPS mirror is
  derived and disposable — delete `memory/dayos/` and the next sync rebuilds
  it identically. Losing the server loses no data.
- **The files are already Obsidian-compatible.** Digests are plain markdown
  with `#tags`; point Obsidian at a copy of `memory/dayos/` and it just works
  as a vault. Nothing to convert later.
- **A human-browsable mirror is a bolt-on, not a decision we owe now.** When
  wanted: a one-line cron (`rclone` to Google Drive, or a nightly push to a
  private GitHub repo) exports the whole brain for browsing/backup. Deferred
  until asked for — it adds a place for things to silently diverge, so it
  should exist only once there's a real use.

What we deliberately did **not** do: store the canonical brain *in* Google
Drive or an Obsidian sync service. That would put a third-party API between
the agent and its own memory (slower, rate-limited, new auth to break) and
buy nothing — the phone already has DayOS itself as the beautiful view of
this data.

## How the DayOS integration works

```
DayOS app (phone/laptop)
   └─ writes → Firebase Firestore  (source of truth, already exists)
                   │  read-only service account, REST
                   ▼
   dayos_sync.py on the VPS  (systemd timer: every 2h; full re-pull daily;
                   │           /sync in Telegram forces it)
                   ▼
   memory/dayos/
     raw/*.json          exact Firestore mirror (rebuild source)
     days/2026-07-03.md  one digest per day: timeline w/ hours by category,
                         journal, captures, sessions, learning, EOD, ratings
     weeks/<sunday>.md   weekly rollup + his Weekly Review + AI summary
     months/YYYY-MM.md   monthly rollup + Monthly Review
     projects/<slug>.md  per-project: sessions, notes, learning, hours
     learning.md         full learning log
     index.md            overview the bot can skim
     sync_status.json    last success / last error — powers staleness warnings
                   │
                   ▼
   bot.py tools: search_dayos · dayos_day · dayos_period · dayos_project
   + a compact "today + yesterday" snapshot in every system prompt
```

Key decisions (and why):

- **Sync to files rather than query Firestore live.** Answers are instant and
  free at question time; the bot keeps working through Firebase outages; and
  it keeps the whole memory architecture one thing (files) instead of two.
- **Same auth pattern DayOS already uses.** `dayos_client.py` mirrors
  `time-tracker/api/cron-reminders.mjs`: sign a service-account JWT, call the
  Firestore REST API. No heavy Firebase SDK; two small libraries; every call
  is inspectable HTTPS.
- **Digests + raw, both.** Digests are what the model reads (organized,
  token-efficient, greppable). Raw JSON means a digest-format improvement
  next month is a code change + rebuild, not a re-download.
- **Search semantics copied from DayOS itself** so results match his
  intuition: `#win` matches the exact tag only (not `#winner`); any other
  query is case-insensitive AND over all words.
- **Soft-deleted entries are excluded** everywhere, matching what the DayOS
  UI shows. Hard-deletes converge within a day via the daily full re-pull.
- **Voice notes and attachments sync as titles/filenames** (searchable
  pointers). No transcription — he uses an external tool for that; if
  transcripts ever land in DayOS as text, they flow through automatically.

## The silent-failure question (Rule 4), answered

*"If this goes wrong silently, how would he ever find out?"*

- Sync failure → recorded in `sync_status.json`; **every** DayOS tool result
  and the system-prompt snapshot then carries a loud `WARNING: last sync
  FAILED / data is N days stale` line, so the agent itself tells him and
  suggests `/sync`. Also visible in `journalctl -u dayos-sync`.
- Not-yet-configured → sync exits cleanly with a "not configured" note (no
  fake red alarms before the key exists); the bot's tools simply don't appear.
- Bad key / wrong project / multiple users → explicit config errors with the
  fix in the message (`DayosConfigError`), exit code 2.

## Cost & safety

- **Anthropic cost:** tool results are capped (≈3.5k chars ≈ 900 tokens);
  the ambient snapshot ≈ 600 tokens. Even heavy DayOS use stays a few cents
  per day on Haiku, inside the existing `DAILY_CAP_USD` guard, which is
  enforced regardless.
- **Firestore cost:** reads only. Recent-window sync (12×/day) + daily full
  re-pull ≈ well under the 50k/day free tier even at multi-year data scale.
  $0.
- **Safety:** the service account is used exclusively for reads by design of
  the code we control; the agent has no write path to DayOS, so it cannot
  corrupt or duplicate his data. The key file lives only on the VPS
  (`chmod 600`, gitignored).
- **Schema drift:** the Firestore schema is documented as a contract in
  `time-tracker/docs/second-brain-integration.md`; DayOS schema changes are
  supposed to update that doc (it's in DayOS's sync checklist). Unknown
  fields here are ignored, unknown review fields still render generically —
  drift degrades gracefully instead of breaking.

## What still needs the owner (in order)

1. **Deploy Phase 1** (unchanged prerequisite): Hetzner VPS + BotFather token
   + Anthropic API key → `deploy/DEPLOY.md` steps 1–5.
2. **The Firebase service-account key** for the DayOS project: Firebase
   console → Project settings → Service accounts → *Generate new private
   key* → follow `deploy/DEPLOY.md` step 7. (Generate a fresh key rather
   than reusing Vercel's — same access, but each can be revoked without
   breaking the other.)
3. Nothing else. The user id auto-detects; the timer installs itself via
   `setup_vps.sh`; `/sync` handles refreshes from the phone.

## Verification checklist (after deploy)

1. `sudo -u agent venv/bin/python dayos_sync.py --full` → prints per-collection
   counts, exit 0; `memory/dayos/days/` contains one file per logged day.
2. Ask the bot *"what did I do yesterday?"* → answer matches DayOS's Today
   view for yesterday.
3. Ask *"how was my week?"* → numbers match the Trends → week view.
4. Log a new block in DayOS, `/sync`, ask again → the new block appears.
5. Stop the timer for a day (or break the key), ask a DayOS question → the
   bot itself warns the data is stale. Then fix and confirm the warning clears.

## Roadmap after this

Tracked as a living backlog in **`docs/BACKLOG.md`** — read that for the full
list of planned integrations (Drive notes, WhatsApp chat history, trading
journals, ...), their status, and shared plumbing across them. Two
standing principles that apply to all of them, not repeated per-entry there:

- **Proactive use** — morning/evening briefings composed from bank snapshots
  (Phase 3 "automations, only when asked") is a cross-cutting feature to add
  once 2+ banks exist, not tied to any one integration.
- **Semantic search / embeddings** — only if plain search demonstrably fails
  on real questions, for any bank. The bar stays where Phase 1 set it.
