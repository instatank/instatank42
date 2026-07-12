"""AI-written weekly synthesis — the agent's own lane of the second brain.

Once a week (Friday 18:00 IST via systemd timer, or on demand via /digest in
Telegram) the agent reads the week's DayOS mirror and writes a short
distillation — patterns, deltas vs last week, open loops — to
memory/digests/<week-sunday>.md. Digests are the agent's OPINION, clearly
labeled, and never overwrite mirror data. The weekly_digest bot tool reads
stored digests; only /digest and the timer spend tokens generating one.

Cost guards: generation refuses when the daily budget cap is already hit, and
its own cost is added to the same ledger as chat turns. One Sonnet call/week
≈ $0.02. Failures are loud (Rule 4): the timer path reports errors to the
founder ON Telegram itself, not just into a log file.
"""

import argparse
import json
import os
import sys
from datetime import timedelta

import budget
import dayos_store
import memory
import playbook_store

DIGESTS_DIR = memory.MEMORY_DIR / "digests"
STATUS_PATH = DIGESTS_DIR / "status.json"
MODEL = os.environ.get("DIGEST_MODEL", "claude-sonnet-5")
MAX_TOKENS = 900

LABEL = ("*Agent-written weekly synthesis for the week of {week} — my own reading "
         "of your data, not your words.*\n\n")

SYSTEM = """You write a weekly synthesis for one person: an ex-poker-pro solo \
builder in New Delhi who thinks in expected value and hates cheerleading. You \
are given his DayOS week rollup, that week's day digests, the prior week's \
rollup, your own previous synthesis, and (maybe) the current status lines of \
his technique curriculum.

Write at most 350 words of plain markdown with exactly these sections:
**The week in one line** — its honest shape.
**Numbers vs last week** — hours by the categories that moved, focus-task \
rate, day ratings. Only real deltas; no padding.
**Patterns** — 2-3 observations he might not see himself.
**Open loops** — pending tasks/focus items worth carrying forward.
**Next week** — ONE concrete suggestion; if a curriculum technique is \
in progress, tie the suggestion to it.

If the data is thin, say so in one line instead of inventing insight."""


def _log(msg: str) -> None:
    print(f"[weekly-digest] {msg}", flush=True)


def week_start_of(d) -> str:
    back = (d.weekday() + 1) % 7  # DayOS weeks start Sunday
    return (d - timedelta(days=back)).strftime("%Y-%m-%d")


def path_for(week_start: str):
    return DIGESTS_DIR / f"{week_start}.md"


def has_any() -> bool:
    return DIGESTS_DIR.exists() and any(DIGESTS_DIR.glob("*-*-*.md"))


def resolve_week(key: str) -> str:
    s = (key or "").strip().lower()
    now = memory.now()
    if s in ("", "this week", "week", "current"):
        return week_start_of(now)
    if s == "last week":
        return week_start_of(now - timedelta(days=7))
    try:
        return week_start_of(memory.datetime.fromisoformat(s))
    except ValueError:
        return ""


def load(period_key: str) -> str:
    """Tool read path: return a stored digest, never generate (reads are free)."""
    week = resolve_week(period_key)
    if not week:
        return f"Could not parse '{period_key}' — use 'this week', 'last week' or a date."
    p = path_for(week)
    if not p.exists():
        return (f"No synthesis written for the week of {week} yet — one is "
                "generated every Friday evening, or on demand with /digest.")
    return p.read_text(encoding="utf-8")


# --- Generation -----------------------------------------------------------------

def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[trimmed]"


def _read_if_exists(path, limit: int) -> str:
    try:
        return _trim(path.read_text(encoding="utf-8"), limit) if path.exists() else ""
    except OSError:
        return ""


def build_input(week_start: str) -> str:
    """Everything the model sees, size-capped. Week rollup + days + prior week
    + previous synthesis + curriculum status lines (if the playbook is synced)."""
    ws = memory.datetime.fromisoformat(week_start)
    parts = [f"# Input data for the week starting {week_start} (Sunday)"]

    rollup = _read_if_exists(dayos_store.DAYOS_DIR / "weeks" / f"{week_start}.md", 2500)
    parts.append("## This week's rollup\n" + (rollup or "(no rollup — thin week)"))

    day_parts = []
    for i in range(7):
        d = (ws + timedelta(days=i)).strftime("%Y-%m-%d")
        body = _read_if_exists(dayos_store.DAYOS_DIR / "days" / f"{d}.md", 700)
        if body:
            day_parts.append(f"### {d}\n{body}")
    parts.append("## Day digests\n" + ("\n".join(day_parts) or "(no days logged)"))

    prev = week_start_of(ws - timedelta(days=7))
    parts.append("## Last week's rollup (for deltas)\n" +
                 (_read_if_exists(dayos_store.DAYOS_DIR / "weeks" / f"{prev}.md", 1500) or "(none)"))
    parts.append("## Your previous synthesis\n" +
                 (_read_if_exists(path_for(prev), 1500) or "(none — this is the first)"))

    if playbook_store.has_data():
        cur = _read_if_exists(playbook_store.REPO_DIR / "playbook" / "CURRICULUM.md", 100000)
        status_lines = [ln for ln in cur.splitlines()
                        if any(g in ln for g in ("☐", "◐", "●"))][:16]
        if status_lines:
            parts.append("## Curriculum status lines\n" + "\n".join(status_lines))

    return "\n\n".join(parts)


class BudgetCapError(RuntimeError):
    pass


def generate_week(week_start: str = "", client=None) -> dict:
    """One Sonnet call -> write memory/digests/<week>.md. Returns
    {week, path, text, cost}. Raises BudgetCapError if the daily cap is hit."""
    if budget.over_daily_cap():
        raise BudgetCapError(
            f"daily budget cap (${budget.DAILY_CAP_USD:.2f}) already reached — "
            "synthesis skipped, will not spend past the cap")
    week = week_start or week_start_of(memory.now())
    if client is None:
        import anthropic  # lazy: the timer script doesn't need it until here
        client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_input(week)}],
    )
    cost = budget.cost_of(MODEL, response.usage)
    budget.add_spend(cost)
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    out = LABEL.format(week=week) + text
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    path_for(week).write_text(out, encoding="utf-8")
    _write_status({"last_success": memory.now().isoformat(), "week": week,
                   "cost_usd": round(cost, 4)})
    _log(f"wrote {path_for(week)} (${cost:.4f})")
    return {"week": week, "path": str(path_for(week)), "text": out, "cost": cost}


def _write_status(update: dict) -> None:
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    status = {}
    if STATUS_PATH.exists():
        try:
            status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    status.update(update)
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")


# --- Telegram delivery (used by the Friday timer; /digest replies in-chat) -------

def send_telegram(text: str) -> None:
    import httpx  # already a dependency (dayos_client uses it)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_USER_ID not set")
    for i in range(0, len(text), 4000):  # Telegram's message size cap
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[i:i + 4000]},
            timeout=30,
        )
        r.raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the weekly synthesis")
    ap.add_argument("--send", action="store_true",
                    help="deliver to Telegram (the Friday timer path)")
    ap.add_argument("--week", default="", help="week start YYYY-MM-DD (default: current)")
    ap.add_argument("--status", action="store_true", help="print status and exit")
    args = ap.parse_args()

    if args.status:
        print(STATUS_PATH.read_text(encoding="utf-8") if STATUS_PATH.exists() else "{}")
        return 0
    if not dayos_store.has_data() or not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        # Pre-configuration this is expected — skip green, same as the sync jobs.
        _log("not configured (no DayOS data or no API key) — skipping")
        return 0
    try:
        result = generate_week(args.week)
        if args.send:
            send_telegram(result["text"])
            _log("delivered to Telegram")
        else:
            print(result["text"])
        return 0
    except BudgetCapError as e:
        _log(str(e))
        if args.send:
            # free message — the skip itself must not be silent
            send_telegram(f"Weekly synthesis skipped: {e}")
        return 0
    except Exception as e:
        _write_status({"last_error": f"{type(e).__name__}: {e}",
                       "last_error_time": memory.now().isoformat()})
        _log(f"FAILED: {type(e).__name__}: {e}")
        if args.send:
            try:  # loud failure on the channel he actually reads
                send_telegram(f"Weekly synthesis FAILED: {type(e).__name__}: {e}")
            except Exception:
                pass  # Telegram itself down — journalctl still has it
        return 1


if __name__ == "__main__":
    sys.exit(main())
