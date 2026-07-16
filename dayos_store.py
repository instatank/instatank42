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
    return ("Available DayOS views: 'open loops' (everything still pending, by age), "
            f"'metrics' (per-day numbers CSV), and tag views: {tag_list}")


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
    if (DAYOS_DIR / "open-loops.md").exists():
        yield "open-loops", DAYOS_DIR / "open-loops.md"
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


# --- System-prompt snapshot -----------------------------------------------------

def prompt_snapshot(max_chars: int = 2400) -> str:
    """Compact ambient context: index summary + today + yesterday. Sits after
    the prompt-cache breakpoint (it changes throughout the day)."""
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
    parts.append(
        "Tools: search_dayos (find anything he wrote/did), dayos_day (one day's "
        "full digest), dayos_period (week/month rollup), dayos_project (per-project log)."
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
