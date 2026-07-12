# Project: Personal AI Agent (Telegram + Claude)

Read this first every session. It is the cross-session memory for building this project.

## What this is

Personal AI agent for a solo builder (ex-poker pro, New Delhi, non-technical — he
steers, Claude Code writes all code). Telegram bot → Anthropic API → file-based
memory. Budget ceiling ~$20/month all-in, target $8–15.

## Current status (2026-07-12)

- **Phase 1 code complete, tested offline, NOT yet deployed or tested end-to-end.**
- **Second brain planned:** `docs/SECOND_BRAIN.md` is the PROPOSED strategy + roadmap
  (awaiting founder confirmation). It is the plan-of-record target that
  `time-tracker/docs/second-brain-integration.md` (the DayOS data contract) points to.
  Nothing brain-side is built yet — deploy Phase 1 first.
- Offline smoke tests pass (`venv/bin/python tests/test_smoke.py`).
- Waiting on him: Hetzner VPS signup, BotFather token, Anthropic API key (all
  require his accounts/money). Deploy guide: `deploy/DEPLOY.md`.
- Next session: help him deploy, then verify the benchmark — daily use, facts
  remembered across days.

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
- **Security**: allowlist on his numeric Telegram ID; secrets only in `.env`
  (systemd `EnvironmentFile`); systemd hardening limits writes to `memory/`.
- **Hosting**: Hetzner CX22-class Ubuntu 24.04, systemd `telegram-agent.service`,
  `Restart=always`. His Claude Max sub must NOT power the bot — separate API key.
- **Phases**: 1 = talking agent w/ memory (now). 2 = read access to his Google
  Drive-synced notes via grep/file search (no embeddings unless search fails).
  3 = dashboards/automations, only when asked.

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

- `docs/SECOND_BRAIN.md` — second-brain strategy, memory layout, phased roadmap (proposed)
- `bot.py` — handlers, allowlist, model routing, tool loop, caps enforcement
- `memory.py` — profile/session-log/facts file I/O (IST timezone)
- `budget.py` — cost-per-call from usage block, daily/monthly accounting, cap
- `tests/test_smoke.py` — offline tests, mocked API
- `deploy/` — `setup_vps.sh` (idempotent root script), `telegram-agent.service`,
  `DEPLOY.md` (non-technical walkthrough)
