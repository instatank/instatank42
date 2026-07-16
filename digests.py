"""AI-written syntheses — the agent's own lane of the second brain.

Weekly: every Friday 18:00 IST (systemd timer, or /digest in Telegram) the
agent reads the week's DayOS mirror and writes a short distillation —
patterns, deltas vs last week, open loops — to
memory/digests/<week-sunday>.md.

Monthly (docs/DAYOS_ORGANIZATION.md Phase C, founder-approved 2026-07-16):
on the 5th of each month (monthly-digest.timer, or /digest month) one call
reads the previous month's weekly syntheses + the DayOS month rollup and
writes memory/digests/months/YYYY-MM.md — the month's story — and refreshes
memory/digests/themes.md, the standing list of patterns that recur across
months (the compounding layer: a theme enters after two monthlies, retires
when it stops appearing).

Digests are the agent's OPINION, clearly labeled, and never overwrite
mirror data. The `digest` bot tool reads stored files; only /digest and the
timers spend tokens generating one.

Cost guards: generation refuses when the daily budget cap is already hit,
and its own cost is added to the same ledger as chat turns. One Sonnet
call/week + one/month ≈ $0.10/month total. Failures are loud (Rule 4): the
timer paths report errors to the founder ON Telegram itself, not just into
a log file.
"""

import argparse
import json
import os
import re
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

MAX_TOKENS_MONTH = 1200  # monthly synthesis + updated themes in one reply

LABEL = ("*Agent-written weekly synthesis for the week of {week} — my own reading "
         "of your data, not your words.*\n\n")
MONTH_LABEL = ("*Agent-written monthly synthesis for {ym} — my own reading of "
               "your month, not your words.*\n\n")
THEMES_LABEL = ("*Standing themes — recurring patterns I track across your "
                "monthly syntheses, refreshed with each monthly (the 5th). "
                "My reading, not your words.*\n\n")
THEMES_MARKER = "===THEMES==="

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

MONTH_SYSTEM = """You write a monthly synthesis for one person: an ex-poker-pro \
solo builder in New Delhi who thinks in expected value and hates cheerleading. \
You are given the month's DayOS rollup, your own weekly syntheses from that \
month, your previous monthly synthesis, and your standing themes file.

Reply in two parts separated by one line containing exactly
===THEMES===

Part 1 — at most 400 words of plain markdown with exactly these sections:
**The month in one line** — its honest shape.
**Numbers vs last month** — hours by the categories that moved, focus-task \
rate, day ratings. Only real deltas; no padding.
**The month's story** — 2-4 observations connecting the weeks: trajectory, \
patterns-of-patterns, what changed mid-month.
**Biggest open loop** — the one thing most worth closing next month.

Part 2 — the UPDATED themes file, full replacement, one bullet per theme:
"- <theme, one plain sentence> (first seen YYYY-MM, last seen YYYY-MM)"
Carry existing themes forward (bump last-seen when the pattern shows this \
month). Add a theme only once it has appeared in at least two monthly \
syntheses. Drop a theme whose last-seen is three or more months old. If \
nothing recurs yet, write exactly: (no recurring themes yet — needs at \
least two months of data)

If the data is thin, say so in one line instead of inventing insight."""


def _log(msg: str) -> None:
    print(f"[weekly-digest] {msg}", flush=True)


def week_start_of(d) -> str:
    back = (d.weekday() + 1) % 7  # DayOS weeks start Sunday
    return (d - timedelta(days=back)).strftime("%Y-%m-%d")


def path_for(week_start: str):
    return DIGESTS_DIR / f"{week_start}.md"


def month_path(ym: str):
    return DIGESTS_DIR / "months" / f"{ym}.md"


def themes_path():
    return DIGESTS_DIR / "themes.md"


def has_any() -> bool:
    if not DIGESTS_DIR.exists():
        return False
    months = DIGESTS_DIR / "months"
    return (any(DIGESTS_DIR.glob("*-*-*.md"))
            or (months.exists() and any(months.glob("*.md")))
            or themes_path().exists())


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


def resolve_month(key: str) -> str:
    """'' / 'last' / 'last month' -> the month that just ended (the timer runs
    on the 5th, writing about the finished month); 'this month' -> current;
    'YYYY-MM' -> itself. Unparseable -> ''."""
    s = (key or "").strip().lower()
    now = memory.now()
    if s in ("", "last", "month", "last month"):
        return (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if s in ("this month", "current"):
        return now.strftime("%Y-%m")
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s
    return ""


def load(period_key: str) -> str:
    """Tool read path: return a stored synthesis (week / month / themes),
    never generate (reads are free)."""
    s = (period_key or "").strip().lower()
    if s in ("themes", "theme", "patterns"):
        p = themes_path()
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ("No themes file yet — it grows out of the monthly syntheses "
                "(written the 5th of each month); needs at least one month of data.")
    if s in ("last month", "this month", "month") or re.fullmatch(r"\d{4}-\d{2}", s):
        ym = resolve_month(s)
        p = month_path(ym)
        if not p.exists():
            return (f"No monthly synthesis for {ym} yet — one is written on the "
                    "5th of each month, or on demand with /digest month.")
        return p.read_text(encoding="utf-8")
    week = resolve_week(period_key)
    if not week:
        return (f"Could not parse '{period_key}' — use 'this week', 'last week', "
                "a date, 'YYYY-MM', 'last month', or 'themes'.")
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
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": build_input(week)}],
    )
    cost = budget.cost_of(MODEL, response.usage)
    budget.add_spend(cost)
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError(
            f"model returned no synthesis text (stop_reason="
            f"{getattr(response, 'stop_reason', '?')}) — cost was still recorded; try again")
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


# --- Monthly synthesis + standing themes (Phase C) --------------------------------

def _month_weeks(ym: str) -> list:
    """Week-start dates (Sundays) of the weekly syntheses that overlap month
    ym — a week belongs to the month if any of its 7 days falls inside it."""
    first = memory.datetime.fromisoformat(ym + "-01")
    next_first = (first + timedelta(days=32)).replace(day=1)
    lo = (first - timedelta(days=6)).strftime("%Y-%m-%d")
    hi = (next_first - timedelta(days=1)).strftime("%Y-%m-%d")
    weeks = sorted(p.stem for p in DIGESTS_DIR.glob("*-*-*.md"))
    return [w for w in weeks if lo <= w <= hi]


def build_month_input(ym: str) -> str:
    """Everything the model sees for a monthly, size-capped: the month's DayOS
    rollup, my own weekly syntheses from that month, the previous monthly,
    and the current themes file (so it can carry themes forward)."""
    parts = [f"# Input data for the monthly synthesis of {ym}"]

    rollup = _read_if_exists(dayos_store.DAYOS_DIR / "months" / f"{ym}.md", 2500)
    parts.append("## The month's DayOS rollup\n" + (rollup or "(no rollup — thin month)"))

    week_parts = []
    for w in _month_weeks(ym):
        body = _read_if_exists(path_for(w), 1600)
        if body:
            week_parts.append(f"### Week of {w}\n{body}")
    parts.append("## Your weekly syntheses this month\n"
                 + ("\n".join(week_parts) or "(none written this month)"))

    prev_first = memory.datetime.fromisoformat(ym + "-01") - timedelta(days=1)
    prev_ym = prev_first.strftime("%Y-%m")
    parts.append("## Last month's DayOS rollup (for deltas)\n" +
                 (_read_if_exists(dayos_store.DAYOS_DIR / "months" / f"{prev_ym}.md", 1500)
                  or "(none)"))
    parts.append("## Your previous monthly synthesis\n" +
                 (_read_if_exists(month_path(prev_ym), 1500) or "(none — this is the first)"))
    parts.append("## Your current themes file\n" +
                 (_read_if_exists(themes_path(), 1200) or "(none yet — this starts it)"))

    return "\n\n".join(parts)


def generate_month(month_key: str = "", client=None) -> dict:
    """One Sonnet call -> memory/digests/months/<ym>.md + a refreshed
    themes.md. Returns {month, path, text, cost, themes_updated}. Raises
    BudgetCapError at the daily cap; a reply missing the ===THEMES===
    marker keeps the month text but leaves themes.md untouched (never
    destroy the standing file on a malformed reply)."""
    if budget.over_daily_cap():
        raise BudgetCapError(
            f"daily budget cap (${budget.DAILY_CAP_USD:.2f}) already reached — "
            "synthesis skipped, will not spend past the cap")
    ym = resolve_month(month_key)
    if not ym:
        raise ValueError(f"could not parse month '{month_key}' — use YYYY-MM or 'last'")
    if client is None:
        import anthropic  # lazy: the timer script doesn't need it until here
        client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_MONTH,
        system=MONTH_SYSTEM,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": build_month_input(ym)}],
    )
    cost = budget.cost_of(MODEL, response.usage)
    budget.add_spend(cost)
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError(
            f"model returned no synthesis text (stop_reason="
            f"{getattr(response, 'stop_reason', '?')}) — cost was still recorded; try again")

    if THEMES_MARKER in text:
        month_part, themes_part = (s.strip() for s in text.split(THEMES_MARKER, 1))
    else:
        month_part, themes_part = text, ""
    if not month_part:
        raise RuntimeError(
            "model reply had no month-synthesis text before the ===THEMES=== "
            "marker — cost was still recorded; try again")
    out = MONTH_LABEL.format(ym=ym) + month_part
    month_path(ym).parent.mkdir(parents=True, exist_ok=True)
    month_path(ym).write_text(out, encoding="utf-8")
    themes_updated = bool(themes_part)
    if themes_updated:
        themes_path().write_text(THEMES_LABEL + themes_part + "\n", encoding="utf-8")
    else:
        _log("WARNING: reply had no ===THEMES=== block — themes.md left untouched")
    _write_status({"last_month_success": memory.now().isoformat(), "month": ym,
                   "month_cost_usd": round(cost, 4), "themes_updated": themes_updated})
    _log(f"wrote {month_path(ym)} (${cost:.4f}, themes_updated={themes_updated})")
    return {"month": ym, "path": str(month_path(ym)), "text": out, "cost": cost,
            "themes_updated": themes_updated}


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
    ap = argparse.ArgumentParser(description="Generate the weekly or monthly synthesis")
    ap.add_argument("--send", action="store_true",
                    help="deliver to Telegram (the timer path)")
    ap.add_argument("--week", default="", help="week start YYYY-MM-DD (default: current)")
    ap.add_argument("--month", nargs="?", const="last", default=None, metavar="YYYY-MM",
                    help="write a MONTHLY synthesis + themes instead "
                         "(default: the month that just ended; the 5th-of-month timer path)")
    ap.add_argument("--status", action="store_true", help="print status and exit")
    args = ap.parse_args()

    if args.status:
        print(STATUS_PATH.read_text(encoding="utf-8") if STATUS_PATH.exists() else "{}")
        return 0
    if not dayos_store.has_data() or not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        # Pre-configuration this is expected — skip green, same as the sync jobs.
        _log("not configured (no DayOS data or no API key) — skipping")
        return 0
    kind = "Monthly" if args.month is not None else "Weekly"
    try:
        if args.month is not None:
            result = generate_month(args.month)
        else:
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
            send_telegram(f"{kind} synthesis skipped: {e}")
        return 0
    except Exception as e:
        _write_status({"last_error": f"{type(e).__name__}: {e}",
                       "last_error_time": memory.now().isoformat()})
        _log(f"FAILED: {type(e).__name__}: {e}")
        if args.send:
            try:  # loud failure on the channel he actually reads
                send_telegram(f"{kind} synthesis FAILED: {type(e).__name__}: {e}")
            except Exception:
                pass  # Telegram itself down — journalctl still has it
        return 1


if __name__ == "__main__":
    sys.exit(main())
