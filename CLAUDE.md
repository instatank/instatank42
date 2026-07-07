# Project: Personal AI Agent (Telegram + Claude)

Read this first every session. It is the cross-session memory for building this project.

## What this is

Personal AI agent for a solo builder (ex-poker pro, New Delhi, non-technical — he
steers, Claude Code writes all code). Telegram bot → Anthropic API → file-based
memory. Budget ceiling ~$20/month all-in, target $8–15.

## Current status (2026-07-07)

- **Phase 1 code complete, tested offline, NOT yet deployed or tested end-to-end.**
- **DayOS second-brain integration code complete, tested offline, NOT yet run
  against live Firestore.** Plan of record: `docs/SECOND_BRAIN.md`. Firestore
  schema contract lives in `time-tracker/docs/second-brain-integration.md`.
- Offline tests pass (`venv/bin/python tests/test_smoke.py` and
  `venv/bin/python tests/test_dayos.py`).
- Waiting on him: Hetzner VPS signup, BotFather token, Anthropic API key, and
  (for DayOS) the Firebase service-account key. Deploy guide: `deploy/DEPLOY.md`
  (DayOS hookup is step 7).
- Next session: help him deploy, run the first `dayos_sync.py --full`, then
  verify the benchmark — daily use, facts remembered, DayOS questions answered
  from real data (checklist at the end of `docs/SECOND_BRAIN.md`).

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
- `tests/test_smoke.py`, `tests/test_dayos.py` — offline tests, no network
- `docs/SECOND_BRAIN.md` — memory-bank architecture plan of record
- `deploy/` — `setup_vps.sh` (idempotent root script), `telegram-agent.service`,
  `dayos-sync.service` + `.timer`, `DEPLOY.md` (non-technical walkthrough)
