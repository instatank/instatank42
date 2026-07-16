# Project: Personal AI Agent (Telegram + Claude)

Read this first every session. It is the cross-session memory for building this project.

## What this is

Personal AI agent for a solo builder (ex-poker pro, New Delhi, non-technical — he
steers, Claude Code writes all code). Telegram bot → Anthropic API → file-based
memory. Budget ceiling ~$20/month all-in, target $8–15.

## Current status (2026-07-12)

- **DEPLOYED AND IN DAILY USE** (founder-confirmed 2026-07-12): the Telegram bot
  is live and the DayOS memory bank is feeding it real data — he has tested that
  it remembers facts and answers from DayOS. If anything seems off, re-run the
  verification checklist at the end of `docs/SECOND_BRAIN.md`.
- Plan of record: `docs/SECOND_BRAIN.md` (memory-bank architecture + the DayOS
  integration in detail). Firestore schema contract lives in
  `time-tracker/docs/second-brain-integration.md`.
- **Roadmap + founder decisions: `docs/ROADMAP.md`** — the phased plan for the
  rest of the second brain (principles layer, distillation, proactive loops,
  source gate). Read it for any "what's next" conversation.
- **Read `docs/BACKLOG.md` every session** — the living tracker for planned
  memory-bank integrations (WhatsApp chat history, Wispr Flow dictation
  history, trading journals, Drive notes, playbook, ...), their status, and
  shared plumbing to club across them.
- **Wispr Flow export script built + offline-tested, blocked on a local Mac
  run** (2026-07-13): `wispr_export.py` exports dictation history from
  Wispr Flow's local SQLite DB — but that DB only exists on the founder's
  Mac, unreachable from this repo's cloud sessions, so it's untested against
  real data. Detail + next steps: `docs/BACKLOG.md`.
- **Playbook memory bank (Phase 2) LIVE** (founder-verified 2026-07-12): the
  bot quotes actual playbook rules. `playbook_sync.py` git-mirrors
  time-tracker's `playbook/` + `LEARNINGS.md`; bot tools `search_playbook` +
  `playbook_doc`.
- **Weekly synthesis (Phases 3+4) code complete + tested offline** (2026-07-12):
  `digests.py` writes an AI-authored weekly distillation to `memory/digests/`
  (agent's own lane, never overwrites mirrors) and delivers it via Telegram —
  Friday 18:00 IST timer (`weekly-digest.timer`) + on-demand `/digest` +
  read tool `weekly_digest`. Goes live on the VPS after `git pull` + re-running
  `setup_vps.sh` (installs the new timer). ~$0.02/week on Sonnet, inside the
  daily cap; failures are messaged to the founder ON Telegram (Rule 4).
- **WhatsApp bank + file-drop ingestion (Phase 5, first source) code complete
  + tested offline** (2026-07-12): `ingest.py` is the generic Telegram
  upload→detect→confirm→ingest pipeline (backlog building block #2;
  confirm-first via inline buttons — nothing enters the brain silently);
  `whatsapp_ingest.py` parses both export dialects and writes snapshots to
  `memory/whatsapp/chats/<chat>/YYYY-MM.md` (re-export replaces, never
  merges); bot tools `search_whatsapp` + `whatsapp_chat`, every result
  carrying the snapshot's coverage date. Live after VPS `git pull` + restart
  (no new config, no new timer); the founder then uploads his first export
  (`deploy/DEPLOY.md` step 9).
- **Full source map added to `docs/BACKLOG.md`** (2026-07-16): one table of
  every candidate source (live → excluded) + scoping entries for Gmail,
  Calendar, Telegram exports, Kindle highlights, finance, people file —
  plus (same day, founder ask) Claude Code conversations and YouTube tagged
  videos.
- **Claude Code conversations plan refined 2026-07-16**: not a Mac export —
  local vs. remote/cloud execution is ambiguous for desktop-app sessions
  (this session itself proves cloud-executed Code sessions exist, with zero
  Mac footprint). Chosen approach instead: an on-demand skill
  (`/save-to-brain`) that has Claude itself condense the session into a
  markdown digest and git-push it to a new dedicated repo, mirrored into
  the brain via the existing `playbook_sync.py` git-mirror pattern — works
  whether the session ran locally or in the cloud, no export step needed.
  Detail + open items: `docs/BACKLOG.md`.
- **YouTube tagged-videos bank code complete + tested offline** (2026-07-16,
  founder-approved plan): send a YouTube link to the bot = the tag.
  `youtube_ingest.py` (link detect, oEmbed metadata, caption scrape →
  timestamped markdown, snapshot per video id) + `youtube_store.py` + bot
  tools `search_youtube`/`youtube_video`; confirm-first buttons; when the
  transcript fetch fails (YouTube may block datacenter IPs — the sandbox
  proxy blocked it here, so the scrape is UNVERIFIED against live YouTube)
  the bot offers paste-the-transcript / paste-a-summary fallbacks (entries
  labeled by how the text arrived). Multi-link messages batch into one
  confirm. Zero model calls in the pipeline. Live after VPS `git pull` +
  re-run of `setup_vps.sh` (installs the new timer below); walkthrough
  `deploy/DEPLOY.md` § 9b.
- **DayOS learning-log links auto-fetch SILENTLY** (founder decision
  2026-07-16, ROADMAP decision log — the one exception to confirm-first):
  `youtube_autofetch.py` scans the DayOS mirror's `learning.md` daily
  (`youtube-autofetch.timer`, 06:30 IST) and on every `/sync`; new links'
  transcripts are saved with no confirmation/notification. Per-video fetch
  failures retry 3 runs then park (in `/sync` output, NOT the banner); a
  crashed run does hit the ⚠️ banner.
  Suggested order after current deploys: Gmail → Drive → Calendar.
  Founder explainer: `docs/HOW_IT_WORKS.md`.
- Offline tests pass (`venv/bin/python tests/test_smoke.py`,
  `tests/test_dayos.py`, `tests/test_playbook.py`, `tests/test_digests.py`,
  `tests/test_whatsapp.py`, and `tests/test_youtube.py`).
- **Branch flow:** `main` exists (created 2026-07-12, founder-approved, by
  merging all prior `claude/*` branches — which never auto-merged and once
  left a session planning against a 9-day-stale view). `main` is the source
  of truth; **every session must merge its `claude/*` branch into `main`
  before ending** until an auto-merge Action like time-tracker's is added.
  Founder still owes one click: GitHub → Settings → change default branch
  to `main`.

## Architecture decisions (settled — don't re-litigate)

- **Python + python-telegram-bot v22** (async, polling — no webhook/port needed).
- **Models**: `claude-haiku-4-5` ($1/$5 per MTok) default; `claude-sonnet-5`
  ($3/$15 sticker, $2/$10 intro through 2026-08) for long/planning messages.
  Routing is a dumb heuristic in `bot.py:pick_model` — length > 700 chars or
  planning keywords. Good enough until proven otherwise.
- **Memory**: Karpathy-style files. `memory/profile.md` (+ facts section the
  model appends to via a single `remember_fact` tool), `memory/sessions/*.md`
  dated logs (last 2 days fed into context), `memory/usage/*.json` spend.
  No vector DB, no Mem0 — only if plain files demonstrably fail.
- **Cost guards (non-negotiable)**: `max_tokens=1000` per turn; daily ceiling
  `DAILY_CAP_USD` (default $0.50) computed from real API usage numbers and
  persisted to disk; 15-msgs/60s rate limit; tool loop capped at 3 rounds.
- **Web search**: Anthropic's server-side `web_search_20250305` tool, always on
  (disable via `WEB_SEARCH_MAX_USES=0`). Capped at 3 searches/message; $10 per
  1k searches, billed into the daily cap via `usage.server_tool_use` in
  budget.py. `pause_turn` stop reason is handled by re-sending (resumes the
  server-side search loop). user_location pinned to New Delhi/IST.
- **Security**: allowlist on his numeric Telegram ID; secrets only in `.env`
  (systemd `EnvironmentFile`); systemd hardening limits writes to `memory/`.
- **Hosting**: Hetzner CX22-class Ubuntu 24.04, systemd `telegram-agent.service`,
  `Restart=always`. His Claude Max sub must NOT power the bot — separate API key.
- **Phases**: 1 = talking agent w/ memory (now). 2 = read access to his Google
  Drive-synced notes via grep/file search (no embeddings unless search fails).
  3 = dashboards/automations, only when asked.
- **Second brain = memory banks, all plain files** (see `docs/SECOND_BRAIN.md`).
  DayOS is the first external bank: `dayos_sync.py` mirrors Firestore read-only
  into `memory/dayos/` (markdown digests + raw JSON) on a 2h systemd timer with
  a daily full re-pull; the bot gets 4 read tools (`search_dayos`, `dayos_day`,
  `dayos_period`, `dayos_project`) + a today/yesterday snapshot in the system
  prompt + `/sync`. Firestore access is raw REST with a service-account JWT
  (same pattern as DayOS's own cron) — deliberately NO firebase-admin/grpc.
  The agent never writes to DayOS. Staleness/sync failures surface loudly in
  tool results — don't strip those warnings.
- **Playbook bank**: `playbook_sync.py` keeps a read-only shallow git checkout
  of time-tracker under `memory/playbook/repo/` (never a copied fork — the
  playbook's own rule), refreshed by the same 2h timer (`ExecStart=-` so its
  failure can't block the DayOS sync) + `/sync`. Bot tools: `search_playbook`,
  `playbook_doc`. Config: `PLAYBOOK_REPO_URL` (+ `PLAYBOOK_REPO_TOKEN` for a
  private repo — scrubbed from all output/status, never stored in the git
  remote on disk).
- **WhatsApp bank**: manual chat exports only (WhatsApp → Export chat →
  Without media), uploaded to the bot as a Telegram file and routed through
  `ingest.py` — the generic file-drop pipeline (confirm-first inline buttons;
  8 MB cap; new sources = one parser module). Each ingest is a snapshot that
  REPLACES that chat's earlier one; every read carries the coverage date.
  Live/unofficial WhatsApp sync was rejected 2026-07-07 (ToS ban risk) —
  don't revisit.

## Lessons / gotchas

- **Prompt-cache minimums**: Haiku 4.5 needs a ≥4096-token prefix to cache at
  all; small profiles won't cache. Harmless (tiny prompts are cheap anyway) —
  don't chase zero cache_read as a bug.
- **Cache breakpoint placement**: system = [static prompt, profile(cache_control),
  recent session notes]. Volatile notes sit after the breakpoint on purpose.
- **Sonnet 5 quirk**: omitting `thinking` runs adaptive thinking by default
  (spends thinking tokens inside max_tokens). Currently accepted — replies are
  capped at 1000 tokens anyway. If Sonnet replies get truncated, that's why.
- **Budget math sanity check**: ~50 Haiku msgs/day ≈ $0.20–0.30/day ≈ $6–9/mo.
  VPS ≈ €4–5/mo. Total lands in the $10–15 target band.
- **anthropic SDK is sync**; called via `asyncio.to_thread` from the async
  telegram handler so the event loop doesn't block.
- **`sudo -u agent python <sync>.py` does NOT load `.env`** — EnvironmentFile
  is a systemd concept. Manual sync runs on the VPS must go through
  `systemctl start dayos-sync.service` (or Telegram `/sync`); a bare sudo run
  prints "not configured" and skips green. Bit us during the staleness drill
  (2026-07-12): the drill's "failing" sync recorded nothing.
- **Bank health warnings are machine-enforced**: `bot.health_banner()`
  prefixes every reply with ⚠️ while any bank's sync is stale/failed. Added
  after the model demonstrably answered from a broken bank's mirror without
  relaying the warning text it was given (playbook L11). Never remove it or
  downgrade it to prompt-only.
- **Mac-only data sources need a LOCAL Claude Code session, full stop.**
  Cloud/remote sessions (claude.ai/code web, GitHub-triggered runs) have zero
  filesystem link to the founder's Mac — no `~/Library`, nothing. A cloud
  session can write and offline-test a script against a synthetic fixture,
  but cannot locate the real file, inspect the real schema, or validate real
  output. Learned the hard way on the Wispr Flow export (2026-07-13,
  `docs/BACKLOG.md`): a whole `/goal` cycle went in circles because the
  session kept retrying a physically impossible step instead of the work
  being scoped for a local session from the start. Any future Mac-local
  integration (another local app's DB, local files not in git/Drive) —
  scope it for a local session up front; don't discover this mid-task.

## File map

- `bot.py` — handlers, allowlist, model routing, tool loop (generic dispatch in
  `handle_tool`), caps enforcement, `/sync`
- `memory.py` — profile/session-log/facts file I/O (IST timezone)
- `budget.py` — cost-per-call from usage block, daily/monthly accounting, cap
- `dayos_client.py` — read-only Firestore REST client (service-account JWT)
- `dayos_sync.py` — pull orchestrator + CLI (`--full/--recent/--status`),
  writes `memory/dayos/` + `sync_status.json`
- `dayos_digest.py` — pure raw→markdown transforms (days/weeks/months/projects)
- `dayos_store.py` — read side: search/day/period/project, staleness warnings,
  prompt snapshot
- `playbook_sync.py` — git-mirror orchestrator + CLI (`--status`), writes
  `memory/playbook/` + `sync_status.json`
- `playbook_store.py` — read side: search/doc lookup, staleness warnings,
  prompt note
- `digests.py` — weekly synthesis: build input from the DayOS mirror, one
  Sonnet call, write `memory/digests/<week>.md`, Telegram delivery, CLI
  (`--send/--week/--status`)
- `ingest.py` — generic Telegram file-drop pipeline (building block #2):
  parser registry + zip/text extraction + size cap; a new file-based source
  is one parser module added to `PARSERS`
- `whatsapp_ingest.py` — WhatsApp export parser (Android + iOS dialects) +
  snapshot writer into `memory/whatsapp/`
- `whatsapp_store.py` — read side: search/chat reads, coverage notes,
  ingest-failure warnings, prompt note
- `youtube_ingest.py` — link-drop write side: YouTube URL detection, oEmbed
  metadata + best-effort caption scrape (stdlib only, no API key), snapshot
  writer `memory/youtube/videos/<id>.md` (re-send replaces), raw caption
  JSON kept, status file
- `youtube_store.py` — read side: search/video reads, save-failure
  warnings, prompt note
- `youtube_autofetch.py` — silent daily scan of the DayOS mirror's
  `learning.md` for YouTube links → fetch+save via youtube_ingest; retry/
  park bookkeeping in the same status file; CLI (`--status`)
- `wispr_export.py` — standalone Mac-local utility (NOT wired into the bot or
  VPS): exports Wispr Flow's dictation history from its local SQLite DB to
  `~/WisprFlowExports/full-history.{json,md}`, incremental via
  `.last_export.json`. Schema-adaptive (queries `sqlite_master`/
  `PRAGMA table_info` and guesses the table/column mapping by keyword,
  saved to `.schema_map.json` for the founder to correct) because Wispr
  Flow's real schema was never inspected from this repo's sessions — it
  only exists on the founder's Mac, unreachable from a cloud session. Needs
  a local Claude Code run (see `docs/BACKLOG.md`) to find the real DB,
  validate/fix the guessed column map and detected timestamp epoch, and do
  the first real export before this is trustworthy.
- `tests/test_smoke.py`, `tests/test_dayos.py`, `tests/test_playbook.py`,
  `tests/test_digests.py`, `tests/test_whatsapp.py`, `tests/test_youtube.py`,
  `tests/test_wispr_export.py` — offline tests, no network (playbook sync
  tests clone a local file:// repo; digest tests fake the Anthropic client;
  wispr_export tests build a synthetic SQLite fixture since the real schema
  is unknown)
- `docs/SECOND_BRAIN.md` — memory-bank architecture plan of record
- `docs/HOW_IT_WORKS.md` — plain-language explainer for the founder: how a
  huge file-based memory coexists with the model's small context (library/
  desk analogy + diagrams). Point him here when he asks "how does this not
  overload the model?"
- `docs/ROADMAP.md` — phased second-brain roadmap + founder decision log
- `docs/BACKLOG.md` — living tracker for planned integrations (WhatsApp,
  trading journals, Drive notes, ...); read every session, update as things move
- `BUILD_BRIEF.md` — the filled build brief for the second brain (playbook rule)
- `deploy/` — `setup_vps.sh` (idempotent root script), `telegram-agent.service`,
  `dayos-sync.service` + `.timer`, `weekly-digest.service` + `.timer`,
  `youtube-autofetch.service` + `.timer`, `DEPLOY.md` (non-technical
  walkthrough)
