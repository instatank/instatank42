"""Read side of the DayOS memory bank: the query functions the bot's tools call.

Everything here reads the plain files dayos_sync.py maintains under
memory/dayos/ — no network, no Firestore, so tool calls are instant and free.
Search semantics deliberately mirror the DayOS app itself:
  - a single '#tag' query matches that exact tag only (#win != #winner)
  - anything else is case-insensitive AND over whitespace-split terms

Every public function returns a plain string ready to hand to the model,
already capped in size (tool results are paid input tokens).
"""

import json
import re
from datetime import timedelta

import dayos_digest
import memory

DAYOS_DIR = memory.MEMORY_DIR / "dayos"
STATUS_PATH = DAYOS_DIR / "sync_status.json"
RAW_DIR = DAYOS_DIR / "raw"

MAX_RESULT_CHARS = 3500     # per tool result
STALE_AFTER_HOURS = 26      # warn when the mirror is older than this

_TAG_QUERY = re.compile(r"#[a-z0-9_%]+$")


# --- Availability / status ---------------------------------------------------

def has_data() -> bool:
    return (DAYOS_DIR / "index.md").exists()


def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def staleness_note() -> str:
    """Loud warning when the mirror is old or the last sync failed — so stale
    data never masquerades as current (a silent-failure guard, not decoration)."""
    status = load_status()
    notes = []
    last = status.get("last_success")
    if last:
        try:
            age_h = (memory.now() - memory.datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h > STALE_AFTER_HOURS:
                notes.append(
                    f"WARNING: DayOS data was last synced {age_h / 24:.1f} days ago — "
                    "it may be stale. Suggest the user runs /sync."
                )
        except ValueError:
            pass
    elif has_data():
        notes.append("WARNING: DayOS data present but no sync record — freshness unknown.")
    if status.get("last_error") and status.get("last_error_time", "") > (last or ""):
        notes.append(f"WARNING: the most recent DayOS sync FAILED: {status['last_error'][:200]}")
    return "\n".join(notes)


def _with_notes(text: str) -> str:
    note = staleness_note()
    return (note + "\n\n" + text) if note else text


def _cap(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... truncated — ask for a narrower slice]"


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


# --- Raw review readers (for the digest syntheses) ---------------------------

def _load_raw(name: str) -> dict:
    """One mirrored raw collection ({doc_id: fields}) from memory/dayos/raw —
    for the rare case a digest needs a field the markdown rollup doesn't
    surface verbatim (e.g. a prior period's stated intention)."""
    p = RAW_DIR / f"{name}.json"
    if p.exists():
        try:
            return json.loads(_read(p))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def weekly_review(week_start: str) -> dict:
    return _load_raw("weeklyReviews").get(week_start) or {}


def monthly_review(ym: str) -> dict:
    return _load_raw("monthlyReviews").get(ym) or {}


def review_intention(week_start: str) -> str:
    """The 'intention for next week' the founder set in a past weekly review —
    lets a later week's digest call out whether it actually happened."""
    r = weekly_review(week_start)
    return str(r.get("nextWeekIntention") or r.get("intention") or "").strip()


def month_focus(ym: str) -> str:
    """The 'one focus' the founder set for a month — for the next month's
    synthesis to judge against."""
    r = monthly_review(ym)
    return str(r.get("oneFocus") or "").strip()


# --- Day / period / project lookups ------------------------------------------

def _resolve_date(date_str: str) -> str:
    s = (date_str or "").strip().lower()
    if s in ("", "today"):
        return memory.now().strftime("%Y-%m-%d")
    if s == "yesterday":
        return (memory.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return ""


def day(date_str: str) -> str:
    if not has_data():
        return "No DayOS data synced yet — ask the user to run /sync first."
    d = _resolve_date(date_str)
    if not d:
        return f"Could not parse date '{date_str}' — use YYYY-MM-DD, 'today' or 'yesterday'."
    path = DAYOS_DIR / "days" / f"{d}.md"
    if not path.exists():
        return _with_notes(f"No DayOS entries for {d} (nothing was logged that day).")
    return _with_notes(_cap(_read(path)))


def _week_start_of(d) -> str:
    back = (d.weekday() + 1) % 7  # DayOS weeks start Sunday
    return (d - timedelta(days=back)).strftime("%Y-%m-%d")


def period(key: str) -> str:
    """'this week' | 'last week' | 'this month' | 'last month' | 'YYYY-MM' |
    a date (returns that date's week)."""
    if not has_data():
        return "No DayOS data synced yet — ask the user to run /sync first."
    s = (key or "").strip().lower()
    now = memory.now()
    path = None
    if s in ("", "this week", "week"):
        path = DAYOS_DIR / "weeks" / f"{_week_start_of(now)}.md"
    elif s == "last week":
        path = DAYOS_DIR / "weeks" / f"{_week_start_of(now - timedelta(days=7))}.md"
    elif s in ("this month", "month"):
        path = DAYOS_DIR / "months" / f"{now.strftime('%Y-%m')}.md"
    elif s == "last month":
        first = now.replace(day=1) - timedelta(days=1)
        path = DAYOS_DIR / "months" / f"{first.strftime('%Y-%m')}.md"
    elif re.fullmatch(r"\d{4}-\d{2}", s):
        path = DAYOS_DIR / "months" / f"{s}.md"
    else:
        d = _resolve_date(s)
        if d:
            path = DAYOS_DIR / "weeks" / f"{_week_start_of(memory.datetime.fromisoformat(d))}.md"
    if path is None:
        return (f"Could not parse period '{key}' — use 'this week', 'last week', "
                "'this month', 'last month', YYYY-MM, or a date inside the week you want.")
    if not path.exists():
        return _with_notes(f"No DayOS rollup for that period ({path.stem}) — no data logged then.")
    return _with_notes(_cap(_read(path)))


def _slugify(name: str) -> str:
    s = str(name or "").lower().lstrip("#")
    return "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch in "_%"))


def project(name: str) -> str:
    if not has_data():
        return "No DayOS data synced yet — ask the user to run /sync first."
    pdir = DAYOS_DIR / "projects"
    available = sorted(p.stem for p in pdir.glob("*.md")) if pdir.exists() else []
    slug = _slugify(name)
    if slug and (pdir / f"{slug}.md").exists():
        return _with_notes(_cap(_read(pdir / f"{slug}.md")))
    # forgiving match: substring either way
    matches = [a for a in available if slug and (slug in a or a in slug)]
    if len(matches) == 1:
        return _with_notes(_cap(_read(pdir / f"{matches[0]}.md")))
    listing = ", ".join(available) if available else "(none yet)"
    return f"No project file for '{name}'. Known projects: {listing}"


# --- Cross-cutting views (Phase A of docs/DAYOS_ORGANIZATION.md) ---------------

OPEN_LOOP_NAMES = ("open loops", "open-loops", "openloops", "open loop",
                   "loops", "open", "pending")
NEVER_CLOSED_NAMES = ("never closed", "never-closed", "neverclosed", "never",
                      "never closed loops")
METRICS_NAMES = ("metrics", "metrics.csv", "numbers", "stats")


def _metrics_tail(text: str, limit: int) -> str:
    """metrics.csv grows forever and rows are ascending — keep the header and
    as many of the MOST RECENT rows as fit, instead of _cap()'s head-cut."""
    lines = text.splitlines()
    if not lines or len(text) <= limit:
        return text
    header, rows = lines[0], lines[1:]
    kept, size = [], len(header) + 80  # slack for the truncation note
    for row in reversed(rows):
        if size + len(row) + 1 > limit:
            break
        kept.append(row)
        size += len(row) + 1
    kept.reverse()
    note = (f"(showing the most recent {len(kept)} of {len(rows)} days — "
            "ask for a specific period for older data)")
    return "\n".join([note, header] + kept)


def _views_listing() -> str:
    tags_dir = DAYOS_DIR / "tags"
    tags = sorted(p.stem for p in tags_dir.glob("*.md")) if tags_dir.exists() else []
    tag_list = ", ".join("#" + t for t in tags) if tags else "(none yet — run /sync)"
    return ("Available DayOS views: 'open loops' (still pending, last 10 days), "
            "'never closed' (loops that outlived 10 days), 'metrics' (per-day "
            f"numbers CSV), and tag views: {tag_list}")


def view(name: str) -> str:
    """The cross-cutting views the sync builds: 'open loops', 'metrics', or a
    '#tag' view. Anything unrecognized returns the listing so the model can
    self-correct in one round."""
    if not has_data():
        return "No DayOS data synced yet — ask the user to run /sync first."
    s = (name or "").strip().lower()
    if s in OPEN_LOOP_NAMES:
        p = DAYOS_DIR / "open-loops.md"
        if p.exists():
            return _with_notes(_cap(_read(p)))
        return "No open-loops view built yet — run /sync once to rebuild the mirror."
    if s in NEVER_CLOSED_NAMES:
        p = DAYOS_DIR / "never-closed.md"
        if p.exists():
            return _with_notes(_cap(_read(p)))
        return "No never-closed view built yet — run /sync once to rebuild the mirror."
    if s in METRICS_NAMES:
        p = DAYOS_DIR / "metrics.csv"
        if p.exists():
            return _with_notes(_metrics_tail(_read(p), MAX_RESULT_CHARS))
        return "No metrics view built yet — run /sync once to rebuild the mirror."
    if s not in ("", "list", "views", "help"):
        fname = dayos_digest.tag_filename(s)
        p = DAYOS_DIR / "tags" / f"{fname}.md"
        if fname and p.exists():
            return _with_notes(_cap(_read(p)))
    return _views_listing()


# --- Search -------------------------------------------------------------------

def _search_files():
    """Yield (label, path) most-useful-first: days newest first, then projects,
    learning, weeks, months. The Phase A views come last on purpose — their
    content restates entries the day files already carry, so when the hit cap
    bites, the originals win and the restatements are what gets dropped."""
    if (DAYOS_DIR / "days").exists():
        for p in sorted((DAYOS_DIR / "days").glob("*.md"), reverse=True):
            yield p.stem, p
    if (DAYOS_DIR / "projects").exists():
        for p in sorted((DAYOS_DIR / "projects").glob("*.md")):
            yield f"project:{p.stem}", p
    if (DAYOS_DIR / "learning.md").exists():
        yield "learning", DAYOS_DIR / "learning.md"
    for sub in ("weeks", "months"):
        if (DAYOS_DIR / sub).exists():
            for p in sorted((DAYOS_DIR / sub).glob("*.md"), reverse=True):
                yield f"{sub[:-1]}:{p.stem}", p
    for stem in ("open-loops", "never-closed"):
        if (DAYOS_DIR / f"{stem}.md").exists():
            yield stem, DAYOS_DIR / f"{stem}.md"
    if (DAYOS_DIR / "tags").exists():
        for p in sorted((DAYOS_DIR / "tags").glob("*.md")):
            yield f"tag:{p.stem}", p


def search(query: str) -> str:
    if not has_data():
        return "No DayOS data synced yet — ask the user to run /sync first."
    q = (query or "").strip()
    if not q:
        return "Empty search query."

    tag_mode = bool(_TAG_QUERY.fullmatch(q.lower()))
    if tag_mode:
        # exact-tag: '#win' must not match '#winner' (same rule as the app)
        pattern = re.compile(re.escape(q.lower()) + r"(?![a-z0-9_%])")
        matcher = lambda line: bool(pattern.search(line.lower()))
    else:
        terms = [t.lower() for t in q.split()]
        matcher = lambda line: all(t in line.lower() for t in terms)

    hits, total = [], 0
    for label, path in _search_files():
        try:
            text = _read(path)
        except OSError:
            continue
        # paragraph units so multi-term queries can span an entry's lines
        for para in text.split("\n\n"):
            if not matcher(para):
                continue
            lines = [ln for ln in para.splitlines() if matcher(ln)] or para.splitlines()[:2]
            for ln in lines[:3]:
                snippet = ln.strip()
                if len(snippet) > 240:
                    snippet = snippet[:240] + "…"
                hits.append(f"[{label}] {snippet}")
            total += 1
            if len(hits) >= 40:
                break
        if len(hits) >= 40:
            break

    if not hits:
        mode = "exact tag" if tag_mode else "all-terms"
        return _with_notes(f"No matches for '{q}' ({mode} search) in the DayOS memory bank.")
    header = f"{total} matching entries for '{q}' (newest first):"
    return _with_notes(_cap(header + "\n" + "\n".join(hits)))


# --- System-prompt snapshot + ambient pulse (Phase B) ---------------------------

_LOOP_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \((\d+)d\) ([^:]+): (.*)$")


def _week_pulse(now=None) -> str:
    """One ambient line: this week's hours (top categories) vs last week —
    computed from metrics.csv at snapshot time, so awareness costs a file
    read, never a model call. Empty string when there's nothing to say."""
    path = DAYOS_DIR / "metrics.csv"
    if not path.exists():
        return ""
    try:
        lines = _read(path).splitlines()
    except OSError:
        return ""
    if len(lines) < 2:
        return ""
    cols = lines[0].split(",")
    try:
        i_total = cols.index("total_h")
    except ValueError:
        return ""
    cat_cols = [(i, c[:-2]) for i, c in enumerate(cols[:i_total]) if c.endswith("_h")]
    now = now or memory.now()
    this_ws = _week_start_of(now)
    last_ws = _week_start_of(now - timedelta(days=7))
    # Elapsed-matched comparison: measure last week only up to the SAME weekday
    # we've reached this week, so a Tuesday pulse compares Sun–Tue vs Sun–Tue,
    # not Sun–Tue vs a full Sun–Sat (which always read as a drop). Mirrors
    # DayOS's own prevDashPeriodRange — week-to-date vs same-days-last-week.
    elapsed = (now.date() - memory.datetime.fromisoformat(this_ws).date()).days
    matched_last_end = (memory.datetime.fromisoformat(last_ws)
                        + timedelta(days=elapsed)).strftime("%Y-%m-%d")
    this_total = last_total = 0.0
    per_cat: dict = {}
    for row in lines[1:]:
        vals = row.split(",")
        try:
            d, total = vals[0], float(vals[i_total] or 0)
        except (ValueError, IndexError):
            continue
        if d >= this_ws:
            this_total += total
            for i, cid in cat_cols:
                try:
                    per_cat[cid] = per_cat.get(cid, 0.0) + float(vals[i] or 0)
                except (ValueError, IndexError):
                    pass
        elif last_ws <= d <= matched_last_end:
            last_total += total
    if this_total == 0 and last_total == 0:
        return ""
    top = sorted(((v, c) for c, v in per_cat.items() if v >= 0.05), reverse=True)[:3]
    cats = " · ".join(f"{dayos_digest.CATS.get(c, c)} {v:.1f}" for v, c in top)
    return (f"Pulse: this week so far {this_total:.1f}h"
            + (f" ({cats})" if cats else "")
            + f" vs {last_total:.1f}h over the same days last week.")


def _loops_pulse() -> str:
    """One ambient line: how many loops are open and the oldest one, plus the
    never-closed count — read off the view files the sync maintains."""
    path = DAYOS_DIR / "open-loops.md"
    if not path.exists():
        return ""
    try:
        active = [m for ln in _read(path).splitlines() if (m := _LOOP_LINE.match(ln))]
        never_path = DAYOS_DIR / "never-closed.md"
        never = (sum(1 for ln in _read(never_path).splitlines() if _LOOP_LINE.match(ln))
                 if never_path.exists() else 0)
    except OSError:
        return ""
    if not active and not never:
        return ""
    if active:
        oldest = active[0]  # the file is oldest-first
        head = (f"Open loops: {len(active)} active "
                f"(oldest {oldest.group(2)}d: \"{oldest.group(4)}\")")
    else:
        head = "Open loops: none active"
    if never:
        head += f" · {never} never-closed"
    return head + "."


def prompt_snapshot(max_chars: int = 2400) -> str:
    """Compact ambient context: index summary + pulse + today + yesterday.
    Sits after the prompt-cache breakpoint (it changes throughout the day)."""
    if not has_data():
        return ""
    parts = ["## DayOS (his time-tracking + journaling system)"]
    note = staleness_note()
    if note:
        parts.append(note)
    status = load_status()
    if status.get("last_success"):
        parts.append(f"Mirror last synced {status['last_success'][:16]} IST.")
    try:
        index = _read(DAYOS_DIR / "index.md")
        parts.append("\n".join(index.splitlines()[1:6]).strip())
    except OSError:
        pass
    for pulse in (_week_pulse(), _loops_pulse()):
        if pulse:
            parts.append(pulse)
    parts.append(
        "Tools: search_dayos (find anything he wrote/did), dayos_day (one day's "
        "full digest), dayos_period (week/month rollup), dayos_project "
        "(per-project log), dayos_view ('open loops' / 'never closed' / "
        "'metrics' / '#tag' views)."
    )
    today = memory.now().strftime("%Y-%m-%d")
    yday = (memory.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for label, d in (("Today so far", today), ("Yesterday", yday)):
        p = DAYOS_DIR / "days" / f"{d}.md"
        if p.exists():
            body = _read(p).strip()
            if len(body) > 900:
                body = body[:900] + "\n[trimmed — full day via dayos_day]"
            parts.append(f"### {label}\n{body}")
    out = "\n\n".join(parts)
    return out[:max_chars]
