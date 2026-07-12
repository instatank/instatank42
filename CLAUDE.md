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
  memory-bank integrations (WhatsApp chat history, trading journals, Drive
  notes, playbook, ...), their status, and shared plumbing to club across them.
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
- Offline tests pass (`venv/bin/python tests/test_smoke.py`,
  `tests/test_dayos.py`, `tests/test_playbook.py`, and `tests/test_digests.py`).
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
- `tests/test_smoke.py`, `tests/test_dayos.py`, `tests/test_playbook.py`,
  `tests/test_digests.py` — offline tests, no network (playbook sync tests
  clone a local file:// repo; digest tests fake the Anthropic client)
- `docs/SECOND_BRAIN.md` — memory-bank architecture plan of record
- `docs/ROADMAP.md` — phased second-brain roadmap + founder decision log
- `docs/BACKLOG.md` — living tracker for planned integrations (WhatsApp,
  trading journals, Drive notes, ...); read every session, update as things move
- `BUILD_BRIEF.md` — the filled build brief for the second brain (playbook rule)
- `deploy/` — `setup_vps.sh` (idempotent root script), `telegram-agent.service`,
  `dayos-sync.service` + `.timer`, `weekly-digest.service` + `.timer`,
  `DEPLOY.md` (non-technical walkthrough)
