# Personal AI Agent (Telegram)

A private Telegram bot backed by Claude, with plain-file memory. One user only —
locked to your Telegram ID.

## How it works

- You message the bot on Telegram (voice via Wispr Flow dictation works — it's just text to the bot).
- Cheap fast model (Haiku) answers routine messages; the smarter model (Sonnet)
  kicks in automatically for longer/planning-type messages.
- **Web search built in:** for anything time-sensitive (news, prices, current
  events) the agent searches the web via Anthropic's server-side search tool
  and cites what it finds. Capped at 3 searches per message (~1¢ each, inside
  the daily budget cap).
- Memory is plain files in `memory/`:
  - `profile.md` — who you are. Edit it freely; the agent reads it every turn.
    The agent also saves durable facts here on its own.
  - `sessions/` — a dated log of every conversation (last two days are fed back
    to the agent as context).
  - `usage/` — daily spend tracking.
- Hard cost guards: per-reply output cap, and a daily spend ceiling
  (`DAILY_CAP_USD`, default $0.50/day ≈ $15/month worst case). When hit, the
  bot politely refuses until midnight IST.
- **DayOS second brain (optional):** `dayos_sync.py` mirrors your DayOS data
  (journals, activity blocks, notes, project sessions, learning, trends) from
  Firestore into `memory/dayos/` as organized markdown, and the agent can
  search and read it to answer questions like "what did I do last Tuesday" or
  "how was my week". Read-only — the agent never writes to DayOS. Setup:
  `deploy/DEPLOY.md` step 7; architecture: `docs/SECOND_BRAIN.md`.

## Commands

- `/start` — hello (also shows your numeric Telegram ID if you're not authorized yet)
- `/remember <fact>` — manually save a fact to your profile
- `/spend` — today's and this month's cost
- `/sync` — refresh DayOS data now (`/sync full` re-pulls everything)

## Setup

See `deploy/DEPLOY.md` for the full step-by-step server guide. Short version:

1. Create a bot with @BotFather on Telegram → get `TELEGRAM_BOT_TOKEN`.
2. Get an API key at console.anthropic.com → `ANTHROPIC_API_KEY`
   (this is a paid API key, separate from any Claude subscription).
3. Message your bot `/start` once — it replies with your numeric ID → `TELEGRAM_ALLOWED_USER_ID`.
4. Put all three in `.env` (copy from `.env.example`).

Run locally: `python3 -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/python bot.py`

## Tests

Offline, no API key or network needed:

```
venv/bin/python tests/test_smoke.py
venv/bin/python tests/test_dayos.py
```
