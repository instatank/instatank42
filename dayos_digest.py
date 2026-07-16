"""Turn raw DayOS Firestore data into the organized markdown memory bank.

Pure functions: build_all(raw) -> {relative_path: file_content}. No network,
no file I/O — dayos_sync.py owns pulling and writing, which keeps everything
here trivially testable offline.

Layout produced (under memory/dayos/):
    days/YYYY-MM-DD.md    one digest per day with any data (timeline, journal,
                          captures, sessions, learning, EOD, ratings, DFT)
    weeks/YYYY-MM-DD.md   weekly rollup keyed by the week's Sunday (DayOS
                          weeks run Sunday-Saturday) + Weekly Review answers
    months/YYYY-MM.md     monthly rollup + Monthly Review answers
    projects/<slug>.md    per-project: sessions, notes, learning, hours
    tags/<tag>.md         per-tag view: every entry carrying the tag, in
                          full, newest first (special tags always; other
                          tags once used >= TAG_VIEW_MIN_USES times;
                          project tags excluded — projects/ covers those)
    open-loops.md         still pending from the last ACTIVE_LOOP_DAYS days
                          (deduped journal tasks, latest-session pending
                          items, today's DFT), oldest first
    never-closed.md       loops that outlived ACTIVE_LOOP_DAYS days, kept
                          for perpetuity — what lingers is itself a signal
    metrics.csv           one row per day: hours by category, total, rating,
                          check-in metrics, DFT status, wins
    learning.md           full learning log, newest first
    index.md              overview: date range, totals, project list

The tag/open-loops/metrics views are the Phase A lenses of
docs/DAYOS_ORGANIZATION.md — pure restatements of raw, no model calls.

Soft-deleted entries (deletedAt set) are excluded everywhere, matching what
the DayOS UI shows. Tags are stored by DayOS with their leading '#'.
"""

from collections import defaultdict
from datetime import date as date_cls
from datetime import timedelta

# Category ids -> display labels (mirrors CATS in time-tracker/index.html).
CATS = {
    "deep_work": "Deep Work",
    "learning": "Learning",
    "practice": "Practice",
    "routine": "Routine",
    "leisure": "Leisure",
    "leaks": "Leaks",
}
SLEEP_ID = "sleep"  # legacy blocks only; excluded from waking-hour totals
WAKING_DAY_MIN = 16 * 60  # a fully-elapsed day = 16 waking hours (matches
                          # WAKING_TOTAL_MIN in time-tracker/index.html); used
                          # to derive "skipped" (unlogged waking) hours.

# Adherence engine defaults — mirror DEFAULT_ADHERENCE_RULES in
# time-tracker/index.html. Used only when the founder hasn't customized
# meta/adherence. Categories are stored as CAT ids here; the app stores labels
# and maps them, so _adherence_cat_id accepts either.
DEFAULT_ADHERENCE_RULES = [
    {"id": "deepwork", "type": "auto", "source": "timeBlocks",
     "condition": {"category": "deep_work", "minMinutes": 120}},
    {"id": "practice", "type": "auto", "source": "timeBlocks",
     "condition": {"category": "practice", "minMinutes": 1}},
    {"id": "learning", "type": "auto", "source": "timeBlocks",
     "condition": {"category": "learning", "minMinutes": 60}},
]
CTYPES = {
    "note": "Quick Note",
    "daily": "Daily Journal",
    "project": "Project Note",
    "insight": "Insight",   # legacy
    "journal": "Journal",   # legacy
}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Tag views (docs/DAYOS_ORGANIZATION.md Phase A): the app's special tags
# always get a view, even when empty; any other tag earns one by use count.
SPECIAL_TAGS = ("#win", "#insight", "#1%", "#dft")
TAG_VIEW_MIN_USES = 5
# Open loops stay "active" this many days (founder decision 2026-07-16);
# older ones move to the never-closed archive instead of nagging forever.
ACTIVE_LOOP_DAYS = 10


# --- Small helpers ---------------------------------------------------------

def not_trashed(doc: dict) -> bool:
    return isinstance(doc, dict) and not doc.get("deletedAt")


def live_items(arr) -> list:
    return [a for a in (arr or []) if isinstance(a, dict) and not a.get("deletedAt")]


def project_slug(name: str) -> str:
    """Mirror of DayOS projectSlug(): lowercase, strip leading '#', keep [a-z0-9_%]."""
    s = str(name or "").lower().lstrip("#")
    return "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch in "_%"))


def tag_filename(tag: str) -> str:
    """Safe filename stem for a tag view: '#win' -> 'win', '#1%' -> '1%'.
    Anything outside [a-z0-9_%-] becomes '_' so odd tags can't escape tags/."""
    s = str(tag or "").lower().lstrip("#").strip()
    return "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "_%-")) else "_"
                   for ch in s)


def _parse_date(s: str):
    try:
        y, m, d = str(s)[:10].split("-")
        return date_cls(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def week_start(date_str: str) -> str:
    """Sunday that starts the DayOS week containing date_str (mirror of getWeekStart)."""
    d = _parse_date(date_str)
    if not d:
        return ""
    back = (d.weekday() + 1) % 7  # Monday=0 ... Sunday=6 -> Sunday goes back 0
    return (d - timedelta(days=back)).isoformat()


def _day_name(date_str: str) -> str:
    d = _parse_date(date_str)
    return DAY_NAMES[d.weekday()] if d else ""


def _cat_label(cat_id: str) -> str:
    if cat_id == SLEEP_ID:
        return "Sleep"
    return CATS.get(cat_id, cat_id or "?")


def _hours(minutes: float) -> str:
    return f"{minutes / 60:.1f}h"


def _cap_date(c: dict) -> str:
    return str(c.get("timestamp", ""))[:10]


def _cap_time(c: dict) -> str:
    ts = str(c.get("timestamp", ""))
    return ts[11:16] if len(ts) >= 16 else ""


def _tags_line(tags) -> str:
    tags = [t for t in (tags or []) if t]
    return " ".join(tags)


def _media_lines(doc: dict, indent: str = "  ") -> list:
    """Voice-note titles + attachment filenames (searchable pointers; the
    binary lives in Firebase Storage, not in this memory bank)."""
    out = []
    for v in live_items(doc.get("voiceNotes")):
        dur = v.get("durationSec")
        dur_s = f" ({int(dur)}s)" if isinstance(dur, (int, float)) else ""
        out.append(f"{indent}voice: \"{v.get('title') or 'untitled'}\"{dur_s}")
    for a in live_items(doc.get("attachments")):
        out.append(f"{indent}{a.get('kind', 'file')}: \"{a.get('title') or 'untitled'}\"")
    return out


def _block_minutes(b: dict) -> float:
    try:
        return float(b.get("duration_min") or 0)
    except (TypeError, ValueError):
        return 0.0


def _cat_totals(blocks: list) -> tuple[float, dict]:
    """(waking_minutes_total, {cat_id: minutes}) — sleep excluded from total."""
    per = defaultdict(float)
    total = 0.0
    for b in blocks:
        mins = _block_minutes(b)
        cat = b.get("category") or "?"
        per[cat] += mins
        if cat != SLEEP_ID:
            total += mins
    return total, per


def _totals_line(prefix: str, total_min: float, per_cat: dict) -> str:
    parts = [
        f"{_cat_label(c)} {per_cat[c] / 60:.1f}"
        for c in list(CATS) + [SLEEP_ID]
        if per_cat.get(c)
    ]
    extra = " — " + " · ".join(parts) if parts else ""
    return f"{prefix} {_hours(total_min)}{extra}"


def _block_project(b: dict) -> str:
    """Slug of the project a block belongs to, if any."""
    if b.get("projectTag"):
        return project_slug(b["projectTag"])
    for t in b.get("tags") or []:
        s = project_slug(t)
        if s:
            return s  # first tag wins; good enough for rollups
    return ""


def _fmt_review_value(v) -> str:
    if isinstance(v, list):
        return "; ".join(_fmt_review_value(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_fmt_review_value(x)}" for k, x in v.items())
    return str(v)


def _review_lines(review: dict) -> list:
    """Generic dump of a Weekly/Monthly Review doc — robust to schema drift.
    aiSummary is rendered separately (it reads best as prose)."""
    skip = {"_synced", "deletedAt", "aiSummary"}
    out = []
    for k in sorted(review):
        if k in skip or k.startswith("_"):
            continue
        v = review[k]
        if v in (None, "", [], {}):
            continue
        out.append(f"- {k}: {_fmt_review_value(v)}")
    return out


def _pct01(v) -> str:
    """A 0..1 rate as a percent; passes non-numeric values through."""
    return f"{round(float(v) * 100)}%" if isinstance(v, (int, float)) else str(v)


# Fields _render_review handles explicitly (so the generic tail doesn't repeat
# them). Everything else in a review doc still renders — drift degrades nicely.
_REVIEW_KNOWN = {
    "_synced", "deletedAt", "aiSummary", "savedAt",
    "weekStart", "weekEnd", "month", "monthLabel",
    "intention", "nextWeekIntention", "totals", "starAverages", "patterns",
    "tasks", "directionCheck", "projectActions", "newProjects",
    "learningHarvest", "learningFocusNext", "weeklyIntentionsCoherence",
    "oneFocus", "oneExperiment",
}


def _render_review(review: dict, kind: str) -> list:
    """Structured render of a Weekly/Monthly Review — the fields the founder
    actually fills, friendly-labelled and highest-signal first, then a generic
    dump of anything unrecognized (schema-drift safe). aiSummary is rendered by
    the caller as prose. Replaces the old flat key:value dump so both the
    rollup files and the AI syntheses that read them get legible review data."""
    L = []
    intention = review.get("nextWeekIntention") or review.get("intention")
    if intention:
        label = "Intention for next week" if kind == "week" else "Focus for next month"
        L.append(f"- {label}: {str(intention).strip()}")
    if review.get("oneFocus"):
        L.append(f"- One focus: {str(review['oneFocus']).strip()}")
    if review.get("oneExperiment"):
        L.append(f"- One experiment: {str(review['oneExperiment']).strip()}")
    totals = review.get("totals")
    if isinstance(totals, dict):
        bits = []
        if totals.get("deepWorkHrs") is not None:
            bits.append(f"deep work {totals['deepWorkHrs']}h")
        if totals.get("adherencePct") is not None:
            bits.append(f"adherence {totals['adherencePct']}%")
        if totals.get("dftRate") is not None:
            bits.append(f"DFT {_pct01(totals['dftRate'])}")
        if totals.get("taskCompletionRate") is not None:
            bits.append(f"tasks {_pct01(totals['taskCompletionRate'])}")
        if totals.get("winCount") is not None:
            bits.append(f"wins {totals['winCount']}")
        if totals.get("dayRatingAvg") is not None:
            bits.append(f"avg rating {totals['dayRatingAvg']}/5")
        if bits:
            L.append("- Snapshot at save: " + ", ".join(bits))
    patterns = review.get("patterns")
    if isinstance(patterns, list) and patterns:
        L.append("- Patterns DayOS surfaced:")
        L.extend(f"  - {str(p).strip()}" for p in patterns if str(p).strip())
    dc = review.get("directionCheck")
    if isinstance(dc, dict):
        if dc.get("gotClearer"):
            L.append(f"- Got clearer on: {str(dc['gotClearer']).strip()}")
        if dc.get("didntGoAsPlanned"):
            L.append(f"- Didn't go as planned: {str(dc['didntGoAsPlanned']).strip()}")
    pa = review.get("projectActions")
    if isinstance(pa, list):
        calls = [f"{a['projectName']}→{a['action']}" for a in pa
                 if isinstance(a, dict) and a.get("projectName") and a.get("action")]
        if calls:
            L.append("- Project portfolio calls: " + ", ".join(calls))
    lh = review.get("learningHarvest")
    if isinstance(lh, dict):
        if lh.get("worthApplying"):
            L.append(f"- Worth applying: {str(lh['worthApplying']).strip()}")
        if lh.get("topTags"):
            L.append(f"- Top learning tags: {_fmt_review_value(lh['topTags'])}")
    lfn = review.get("learningFocusNext")
    if isinstance(lfn, dict) and (lfn.get("freeText") or lfn.get("tags")):
        parts = []
        if lfn.get("tags"):
            parts.append(_fmt_review_value(lfn["tags"]))
        if lfn.get("freeText"):
            parts.append(str(lfn["freeText"]).strip())
        L.append("- Learning focus next: " + " — ".join(p for p in parts if p))
    coh = review.get("weeklyIntentionsCoherence")
    if coh:
        L.append(f"- Weekly intentions were: {coh}")
    tasks = review.get("tasks")
    if isinstance(tasks, list) and tasks:
        done = sum(1 for t in tasks if isinstance(t, dict) and t.get("completed"))
        L.append(f"- Review to-dos: {done}/{len(tasks)} done")
    for k in sorted(review):
        if k in _REVIEW_KNOWN or k.startswith("_"):
            continue
        v = review[k]
        if v in (None, "", [], {}):
            continue
        L.append(f"- {k}: {_fmt_review_value(v)}")
    return L


# --- Per-day digest --------------------------------------------------------

def render_day(date_str: str, blocks: list, journal, captures: list,
               sessions: list, learning: list, rating, life_rating: dict,
               eod: str, dft: dict, metric_labels: dict) -> str:
    L = [f"# {date_str} · {_day_name(date_str)}", ""]

    headline = []
    if rating:
        headline.append(f"Rating: {rating}/5")
    if dft and dft.get("text"):
        headline.append(f"DFT: \"{dft['text']}\" — {dft.get('status', 'pending')}")
    if headline:
        L.append(" · ".join(headline))
    if life_rating:
        pairs = [
            f"{metric_labels.get(k, k)} {v}"
            for k, v in sorted(life_rating.items())
            if isinstance(v, (int, float))
        ]
        if pairs:
            L.append("Check-in: " + " · ".join(pairs))
    if len(L) > 2:
        L.append("")

    if blocks:
        L.append("## Timeline")
        for b in sorted(blocks, key=lambda x: str(x.get("start_time", ""))):
            mins = int(_block_minutes(b))
            head = f"- {b.get('start_time', '??:??')} {mins}m {_cat_label(b.get('category'))}"
            if b.get("label"):
                head += f" — {b['label']}"
            slug = _block_project(b)
            if slug:
                head += f" [#{slug}]"
            if b.get("energy_level"):
                head += f" (energy {b['energy_level']})"
            L.append(head)
            if b.get("note"):
                L.append(f"  note: {b['note']}")
            L.extend(_media_lines(b))
        total, per = _cat_totals(blocks)
        L.append(_totals_line("Logged", total, per))
        L.append("")

    if journal:
        L.append("## Daily Journal")
        if journal.get("thoughts"):
            L.append("Thoughts:")
            L.append(str(journal["thoughts"]).strip())
        if journal.get("reflection"):
            L.append("Reflection:")
            L.append(str(journal["reflection"]).strip())
        tasks = [t for t in journal.get("tasks") or [] if isinstance(t, dict) and t.get("text")]
        if tasks:
            L.append("Tasks: " + " · ".join(
                f"[{'x' if t.get('completed') else ' '}] {t['text']}" for t in tasks
            ))
        if journal.get("entertainmentCap"):
            L.append(f"Entertainment cap: {journal['entertainmentCap']}")
        if journal.get("tags"):
            L.append("Tags: " + _tags_line(journal["tags"]))
        L.extend(_media_lines(journal, indent=""))
        L.append("")

    if captures:
        L.append("## Captures")
        for c in sorted(captures, key=_cap_time):
            label = CTYPES.get(c.get("type"), c.get("type") or "Note")
            head = f"- {_cap_time(c)} {label}"
            if c.get("project_tag"):
                head += f" ({project_slug(c['project_tag'])})"
            body = str(c.get("body") or "").strip()
            L.append(f"{head}: {body}" if body else head)
            extra_tags = [t for t in c.get("tags") or [] if t and t not in body]
            if extra_tags:
                L.append(f"  tags: {_tags_line(extra_tags)}")
            L.extend(_media_lines(c))
        L.append("")

    if sessions:
        L.append("## Project sessions")
        for s in sessions:
            mins = s.get("durationMin")
            dur = f" · {int(mins)}m" if isinstance(mins, (int, float)) and mins else ""
            L.append(f"### {s.get('projectName', '?')}{dur}")
            for field, label in (("before", "Before"), ("during", "During"), ("after", "After")):
                if s.get(field):
                    L.append(f"{label}: {str(s[field]).strip()}")
            for field, label in (("done", "Done"), ("pending", "Pending"), ("learned", "Learned")):
                items = [str(x).strip() for x in s.get(field) or [] if str(x).strip()]
                if items:
                    L.append(f"{label}: " + "; ".join(items))
            if s.get("tags"):
                L.append("Tags: " + _tags_line(s["tags"]))
            L.extend(_media_lines(s, indent=""))
        L.append("")

    if learning:
        L.append("## Learning")
        for e in learning:
            src = e.get("sourceName") or "?"
            typ = f" ({e['sourceType']})" if e.get("sourceType") else ""
            L.append(f"- {src}{typ}: {str(e.get('takeaway') or '').strip()}")
            if e.get("fullNotes"):
                L.append(f"  notes: {str(e['fullNotes']).strip()}")
            if e.get("tags"):
                L.append(f"  tags: {_tags_line(e['tags'])}")
        L.append("")

    if eod:
        L.append("## End of day")
        L.append(str(eod).strip())
        L.append("")

    return "\n".join(L).rstrip() + "\n"


# --- Weekly / monthly rollups ----------------------------------------------

def _period_stats(dates: list, by_date: dict) -> dict:
    """Aggregate stats over a list of dates using the by_date index."""
    blocks = [b for d in dates for b in by_date["blocks"].get(d, [])]
    total, per_cat = _cat_totals(blocks)
    per_project = defaultdict(float)
    for b in blocks:
        slug = _block_project(b)
        if slug:
            per_project[slug] += _block_minutes(b)
    ratings = [by_date["ratings"][d] for d in dates if by_date["ratings"].get(d)]
    dfts = [by_date["dfts"][d] for d in dates if by_date["dfts"].get(d)]
    wins = 0
    for d in dates:
        for doc in (by_date["captures"].get(d, []) + by_date["journals_list"].get(d, [])):
            if "#win" in (doc.get("tags") or []):
                wins += 1
    return {
        "total_min": total,
        "per_cat": per_cat,
        "per_project": dict(per_project),
        "days_with_data": sum(1 for d in dates if d in by_date["all_dates"]),
        "ratings": ratings,
        "dft_done": sum(1 for x in dfts if x.get("status") == "done"),
        "dft_set": len(dfts),
        "wins": wins,
    }


def _stats_lines(st: dict, n_days: int) -> list:
    L = [_totals_line("Logged", st["total_min"], st["per_cat"])]
    bits = [f"Days with data: {st['days_with_data']}/{n_days}"]
    if st["ratings"]:
        avg = sum(st["ratings"]) / len(st["ratings"])
        bits.append(f"Avg day rating: {avg:.1f}/5 ({len(st['ratings'])} rated)")
    if st["dft_set"]:
        bits.append(f"DFT done: {st['dft_done']}/{st['dft_set']}")
    if st["wins"]:
        bits.append(f"Wins (#win): {st['wins']}")
    L.append(" · ".join(bits))
    if st["per_project"]:
        top = sorted(st["per_project"].items(), key=lambda kv: -kv[1])
        L.append("By project: " + " · ".join(f"{s} {m / 60:.1f}h" for s, m in top))
    return L


def render_week(ws: str, by_date: dict, review) -> str:
    dates = [(_parse_date(ws) + timedelta(days=i)).isoformat() for i in range(7)]
    st = _period_stats(dates, by_date)
    L = [f"# Week {ws} → {dates[-1]}", ""]
    L.extend(_stats_lines(st, 7))
    day_bits = []
    for d in dates:
        total, _ = _cat_totals(by_date["blocks"].get(d, []))
        r = by_date["ratings"].get(d)
        if total or r:
            day_bits.append(f"{_day_name(d)[:3]} {d[8:]}: {total / 60:.1f}h" + (f" ★{r}" if r else ""))
    if day_bits:
        L.append("Daily: " + " · ".join(day_bits))
    if review:
        lines = _render_review(review, "week")
        if lines:
            L.append("")
            L.append("## Weekly review")
            L.extend(lines)
        if review.get("aiSummary"):
            L.append("")
            L.append("## AI summary (drafted in DayOS)")
            L.append(str(review["aiSummary"]).strip())
    return "\n".join(L).rstrip() + "\n"


def render_month(ym: str, dates: list, by_date: dict, review) -> str:
    st = _period_stats(dates, by_date)
    L = [f"# {ym}", ""]
    L.extend(_stats_lines(st, len(dates)))
    weeks = sorted({week_start(d) for d in dates if week_start(d)})
    wk_bits = []
    for ws in weeks:
        wdates = [(_parse_date(ws) + timedelta(days=i)).isoformat() for i in range(7)]
        wtotal, _ = _cat_totals([b for d in wdates for b in by_date["blocks"].get(d, [])])
        if wtotal:
            wk_bits.append(f"wk {ws}: {wtotal / 60:.1f}h")
    if wk_bits:
        L.append("By week: " + " · ".join(wk_bits))
    if review:
        lines = _render_review(review, "month")
        if lines:
            L.append("")
            L.append("## Monthly review")
            L.extend(lines)
        if review.get("aiSummary"):
            L.append("")
            L.append("## AI summary (drafted in DayOS)")
            L.append(str(review["aiSummary"]).strip())
    return "\n".join(L).rstrip() + "\n"


# --- Per-project + learning + index -----------------------------------------

def render_project(name: str, slug: str, sessions: list, captures: list,
                   blocks: list, learning: list) -> str:
    total_min = sum(_block_minutes(b) for b in blocks)
    bits = []
    if total_min:
        bits.append(f"{_hours(total_min)} logged across {len(blocks)} blocks")
    if sessions:
        bits.append(f"{len(sessions)} sessions")
    L = [f"# {name} (#{slug})" + (" — " + " · ".join(bits) if bits else ""), ""]

    if sessions:
        L.append("## Sessions (newest first)")
        for s in sorted(sessions, key=lambda x: str(x.get("date", "")), reverse=True):
            mins = s.get("durationMin")
            dur = f" · {int(mins)}m" if isinstance(mins, (int, float)) and mins else ""
            L.append(f"### {s.get('date', '?')}{dur}")
            for field, label in (("before", "Before"), ("during", "During"), ("after", "After")):
                if s.get(field):
                    L.append(f"{label}: {str(s[field]).strip()}")
            for field, label in (("done", "Done"), ("pending", "Pending"), ("learned", "Learned")):
                items = [str(x).strip() for x in s.get(field) or [] if str(x).strip()]
                if items:
                    L.append(f"{label}: " + "; ".join(items))
        L.append("")

    if captures:
        L.append("## Notes (newest first)")
        for c in sorted(captures, key=lambda x: str(x.get("timestamp", "")), reverse=True):
            label = CTYPES.get(c.get("type"), c.get("type") or "Note")
            L.append(f"- {_cap_date(c)} {label}: {str(c.get('body') or '').strip()}")
            L.extend(_media_lines(c))
        L.append("")

    if learning:
        L.append(f"## Learning (tagged #{slug})")
        for e in sorted(learning, key=lambda x: str(x.get("date", "")), reverse=True):
            L.append(f"- {e.get('date', '?')} {e.get('sourceName', '?')}: "
                     f"{str(e.get('takeaway') or '').strip()}")
        L.append("")

    return "\n".join(L).rstrip() + "\n"


def render_learning(entries: list) -> str:
    L = ["# Learning log (newest first)", ""]
    for e in sorted(entries, key=lambda x: str(x.get("date") or x.get("createdAt") or ""),
                    reverse=True):
        typ = f" ({e['sourceType']})" if e.get("sourceType") else ""
        L.append(f"## {e.get('date', '?')} · {e.get('sourceName', '?')}{typ}")
        if e.get("takeaway"):
            L.append(f"Takeaway: {str(e['takeaway']).strip()}")
        if e.get("fullNotes"):
            L.append(str(e["fullNotes"]).strip())
        if e.get("tags"):
            L.append("Tags: " + _tags_line(e["tags"]))
        L.extend(_media_lines(e, indent=""))
        L.append("")
    return "\n".join(L).rstrip() + "\n"


# --- Phase A lenses: tag views, open loops, metrics --------------------------

def _collect_tagged(raw: dict) -> dict:
    """{tag: [(date, time, header, body_lines)]} over every live entry that
    carries tags — the raw material for the per-tag views."""
    out = defaultdict(list)

    def add(tags, date, time_s, head, body):
        for t in {str(t).lower() for t in (tags or []) if t}:
            out[t].append((str(date), str(time_s or ""), head, body))

    for b in raw.get("blocks", {}).values():
        if not_trashed(b) and b.get("date"):
            head = (f"Block {b.get('start_time', '??:??')} "
                    f"{int(_block_minutes(b))}m {_cat_label(b.get('category'))}")
            if b.get("label"):
                head += f" — {b['label']}"
            body = [f"note: {b['note']}"] if b.get("note") else []
            add(b.get("tags"), b["date"], b.get("start_time"), head, body)

    for c in raw.get("captures", {}).values():
        if not_trashed(c) and _cap_date(c):
            head = f"{CTYPES.get(c.get('type'), c.get('type') or 'Note')} {_cap_time(c)}".strip()
            body = [ln for ln in [str(c.get("body") or "").strip()] if ln]
            add(c.get("tags"), _cap_date(c), _cap_time(c), head, body)

    for j in raw.get("dailyJournal", {}).values():
        if not_trashed(j) and j.get("date"):
            body = []
            if j.get("thoughts"):
                body.append("Thoughts: " + str(j["thoughts"]).strip())
            if j.get("reflection"):
                body.append("Reflection: " + str(j["reflection"]).strip())
            add(j.get("tags"), j["date"], "", "Daily Journal", body)

    for s in raw.get("sessions", {}).values():
        if not_trashed(s) and s.get("date"):
            body = []
            for field, label in (("before", "Before"), ("during", "During"), ("after", "After")):
                if s.get(field):
                    body.append(f"{label}: {str(s[field]).strip()}")
            for field, label in (("done", "Done"), ("pending", "Pending"), ("learned", "Learned")):
                items = [str(x).strip() for x in s.get(field) or [] if str(x).strip()]
                if items:
                    body.append(f"{label}: " + "; ".join(items))
            add(s.get("tags"), s["date"], "", f"Session: {s.get('projectName', '?')}", body)

    for e in raw.get("learning", {}).values():
        if not_trashed(e) and e.get("date"):
            body = []
            if e.get("takeaway"):
                body.append("Takeaway: " + str(e["takeaway"]).strip())
            if e.get("fullNotes"):
                body.append(str(e["fullNotes"]).strip())
            add(e.get("tags"), e["date"], "", f"Learning: {e.get('sourceName', '?')}", body)

    return out


def render_tag_view(tag: str, entries: list) -> str:
    """One tag's view: every entry in full, newest first, dated + labeled by
    origin — a document, not a pile of search snippets."""
    if not entries:
        return f"# {tag} — no entries yet\n"
    entries = sorted(entries, key=lambda x: (x[0], x[1]), reverse=True)
    dates = [e[0] for e in entries]
    L = [f"# {tag} — {len(entries)} entries ({min(dates)} → {max(dates)}), newest first"]
    for date, _time, head, body in entries:
        L.append("")
        L.append(f"## {date} · {head}")
        L.extend(body)
    return "\n".join(L).rstrip() + "\n"


def _journal_loops(bd: dict) -> list:
    """Unchecked journal tasks, deduped: DayOS journals carry an unfinished
    task forward day after day, but one loop = one line (founder ask
    2026-07-16). Occurrences group by normalized text; the LATEST copy
    decides done-ness (ticking any copy that day closes the loop, and a task
    re-added after being done is a fresh loop); the line is dated from the
    start of the current unchecked streak, so age = how long it's been open."""
    occ = {}   # normalized text -> {date: completed_that_day}
    disp = {}  # normalized text -> display text
    for d in sorted(bd["journals"]):
        for task in bd["journals"][d].get("tasks") or []:
            text = str(task.get("text") or "").strip() if isinstance(task, dict) else ""
            if not text:
                continue
            norm = " ".join(text.lower().split())
            day_map = occ.setdefault(norm, {})
            day_map[d] = bool(day_map.get(d)) or bool(task.get("completed"))
            disp[norm] = text
    items = []
    for norm, day_map in occ.items():
        dates = sorted(day_map)
        if day_map[dates[-1]]:
            continue  # latest copy is ticked -> closed
        since = dates[-1]
        for d in reversed(dates):
            if day_map[d]:
                break
            since = d
        items.append((since, "journal task", disp[norm]))
    return items


def render_open_loops(raw: dict, bd: dict, today: str) -> tuple[str, str]:
    """Everything he said he'd do that isn't done -> two files (founder
    decisions 2026-07-16): open-loops.md holds loops from the last
    ACTIVE_LOOP_DAYS days; anything older lands in never-closed.md, kept for
    perpetuity so what tends to linger is itself visible. Sources: deduped
    journal tasks, pending[] from each project's LATEST session (older
    sessions' lists are superseded, not open), today's DFT if pending (older
    pending DFTs auto-skip in the app — history, not loops). Oldest first."""
    items = _journal_loops(bd)

    latest = {}  # project slug -> ((date, createdAt), session)
    for s in raw.get("sessions", {}).values():
        if not_trashed(s) and s.get("date") and s.get("projectName"):
            slug = project_slug(s["projectName"])
            key = (str(s["date"]), str(s.get("createdAt") or ""))
            if slug not in latest or key > latest[slug][0]:
                latest[slug] = (key, s)
    for slug in sorted(latest):
        s = latest[slug][1]
        for p in s.get("pending") or []:
            text = str(p).strip()
            if text:
                items.append((str(s["date"]), f"session · {s.get('projectName')}", text))

    dft = bd["dfts"].get(today)
    if dft and dft.get("status") == "pending" and str(dft.get("text", "")).strip():
        items.append((today, "today's focus task", str(dft["text"]).strip()))

    t_today = _parse_date(today)

    def age(d: str) -> int:
        pd = _parse_date(d)
        return (t_today - pd).days if (t_today and pd) else 0

    active = sorted(x for x in items if age(x[0]) <= ACTIVE_LOOP_DAYS)
    stale = sorted(x for x in items if age(x[0]) > ACTIVE_LOOP_DAYS)

    def lines(rows):
        return [f"- {d} ({age(d)}d) {origin}: {text}" for d, origin, text in rows]

    L = [f"# Open loops — still pending as of {today}", ""]
    if active:
        L.append(f"{len(active)} active loop(s) from the last {ACTIVE_LOOP_DAYS} "
                 "days, oldest first.")
        L.extend(lines(active))
    else:
        L.append(f"Nothing pending from the last {ACTIVE_LOOP_DAYS} days — all clear.")
    if stale:
        L.append("")
        L.append(f"({len(stale)} older item(s) live in the never-closed archive — "
                 "dayos_view 'never closed'.)")
    L.append("")
    L.append("(Rebuilt every sync — a loop closes once its task is ticked in "
             "DayOS. Carried-forward copies of one task collapse into a single "
             f"line, dated from when it first went open. After {ACTIVE_LOOP_DAYS} "
             "days an item moves to never-closed.md.)")
    active_md = "\n".join(L).rstrip() + "\n"

    N = [f"# Never closed — loops that outlived {ACTIVE_LOOP_DAYS} days "
         f"(as of {today})", ""]
    if stale:
        N.append(f"{len(stale)} item(s), oldest first — what tends to land here "
                 "is a signal in itself.")
        N.extend(lines(stale))
        N.append("")
        N.append("(An item leaves this list only when its task is finally ticked "
                 "— or deleted — in DayOS.)")
    else:
        N.append(f"Nothing here yet — no loop has outlived {ACTIVE_LOOP_DAYS} days.")
    never_md = "\n".join(N).rstrip() + "\n"

    return active_md, never_md


def _adherence_cat_id(cat) -> str:
    """Map a rule's condition.category (a CAT id like 'deep_work' OR a label
    like 'Deep Work') to the canonical category id — the app stores labels."""
    if not cat:
        return ""
    if cat in CATS:
        return cat
    for cid, label in CATS.items():
        if cat == label:
            return cid
    return str(cat)


def _adherence_rules(raw: dict) -> list:
    """(cat_id, min_minutes) for every enabled auto/timeBlocks rule in
    meta/adherence — the founder's own config, else DayOS's built-in defaults.
    Explicit rules are skipped: they read a per-day dailyChecks doc DayOS
    doesn't sync, so they can't be evaluated here (the app treats an absent
    check as 'not met' too, so we match it by omission)."""
    meta = raw.get("meta", {}) or {}
    cfg = meta.get("adherence") or {}
    rules = cfg.get("rules")
    if not isinstance(rules, list) or not rules:
        rules = DEFAULT_ADHERENCE_RULES
    out = []
    for r in rules:
        if not isinstance(r, dict) or r.get("enabled") is False:
            continue
        if r.get("type") != "auto" or r.get("source") != "timeBlocks":
            continue
        cond = r.get("condition") or {}
        try:
            min_min = float(cond.get("minMinutes") or 0)
        except (TypeError, ValueError):
            min_min = 0.0
        out.append((_adherence_cat_id(cond.get("category")), min_min))
    return out


def _day_adherence_pct(day_blocks: list, rules: list):
    """Percent of enabled auto-rules met this day (same math as the app's
    calculateAdherence, one day wide), or None when no rules are configured."""
    if not rules:
        return None
    passed = 0
    for cat_id, min_min in rules:
        mins = sum(_block_minutes(b) for b in day_blocks if b.get("category") == cat_id)
        if mins >= min_min:
            passed += 1
    return round(passed / len(rules) * 100)


def render_metrics(bd: dict, metric_ids: list, rules: list, today: str) -> str:
    """metrics.csv — one row per day: hours by category, total, day rating,
    each check-in metric, DFT status, wins, and the Trends-grade derived
    numbers the DayOS dashboard shows but never persists — adherence %, task
    completion, leak %, and skipped (unlogged waking) hours. The machine-
    readable spine for trend/correlation questions; dates ascending.

    Derived columns are appended after `wins` so existing readers (and column
    positions) are undisturbed. `skipped_h` is left blank for `today` and any
    future date, since a day still in progress hasn't 'skipped' its unlogged
    hours yet — it's only meaningful once the day is complete."""
    cols = (["date"] + [f"{c}_h" for c in CATS] + ["total_h", "rating"]
            + list(metric_ids) + ["dft_status", "wins",
            "adherence_pct", "task_done", "task_total", "leak_pct", "skipped_h"])
    rows = [",".join(cols)]
    for d in sorted(bd["all_dates"]):
        day_blocks = bd["blocks"].get(d, [])
        total, per = _cat_totals(day_blocks)
        row = [d]
        row += [f"{per.get(c, 0) / 60:.2f}" for c in CATS]
        row.append(f"{total / 60:.2f}")
        rating = bd["ratings"].get(d)
        row.append(str(rating) if rating else "")
        life = bd["life"].get(d, {})
        for m in metric_ids:
            v = life.get(m)
            row.append(str(v) if isinstance(v, (int, float)) else "")
        dft = bd["dfts"].get(d)
        row.append(str(dft.get("status", "")) if dft else "")
        wins = sum(1 for doc in (bd["captures"].get(d, []) + bd["journals_list"].get(d, []))
                   if "#win" in (doc.get("tags") or []))
        row.append(str(wins))
        # --- Trends-grade derived columns ---
        adh = _day_adherence_pct(day_blocks, rules)
        row.append(str(adh) if adh is not None else "")
        journal = bd["journals"].get(d) or {}
        tasks = [t for t in (journal.get("tasks") or []) if isinstance(t, dict) and (t.get("text") or "").strip()]
        if tasks:
            done = sum(1 for t in tasks if t.get("completed"))
            row.append(str(done))
            row.append(str(len(tasks)))
        else:
            row += ["", ""]
        leaks_min = per.get("leaks", 0)
        row.append(f"{leaks_min / total * 100:.0f}" if total > 0 else "")
        if today and d < today:
            row.append(f"{max(0.0, WAKING_DAY_MIN - total) / 60:.2f}")
        else:
            row.append("")
        rows.append(",".join(row))
    return "\n".join(rows) + "\n"


# --- Top-level build ---------------------------------------------------------

def _index_by_date(raw: dict) -> dict:
    """Bucket every live doc by its IST date string."""
    blocks = defaultdict(list)
    for b in raw.get("blocks", {}).values():
        if not_trashed(b) and b.get("date"):
            blocks[b["date"]].append(b)
    captures = defaultdict(list)
    for c in raw.get("captures", {}).values():
        if not_trashed(c) and _cap_date(c):
            captures[_cap_date(c)].append(c)
    journals = {}
    journals_list = defaultdict(list)
    for j in raw.get("dailyJournal", {}).values():
        if not_trashed(j) and j.get("date"):
            journals[j["date"]] = j
            journals_list[j["date"]].append(j)
    sessions = defaultdict(list)
    for s in raw.get("sessions", {}).values():
        if not_trashed(s) and s.get("date"):
            sessions[s["date"]].append(s)
    learning = defaultdict(list)
    for e in raw.get("learning", {}).values():
        if not_trashed(e) and e.get("date"):
            learning[e["date"]].append(e)
    ratings = {d: v.get("rating") for d, v in raw.get("ratings", {}).items() if v.get("rating")}
    life = {d: {k: v for k, v in doc.items() if not k.startswith("_")}
            for d, doc in raw.get("life_ratings", {}).items() if isinstance(doc, dict)}
    eod = {d: v.get("text", "") for d, v in raw.get("eod", {}).items() if v.get("text")}
    dfts = {d: v for d, v in raw.get("dfts", {}).items() if isinstance(v, dict) and v.get("text")}

    all_dates = (set(blocks) | set(captures) | set(journals) | set(sessions)
                 | set(learning) | set(ratings) | set(eod) | set(dfts)
                 | {d for d, v in life.items() if v})
    return {
        "blocks": blocks, "captures": captures, "journals": journals,
        "journals_list": journals_list, "sessions": sessions, "learning": learning,
        "ratings": ratings, "life": life, "eod": eod, "dfts": dfts,
        "all_dates": all_dates,
    }


def _metric_labels(raw: dict) -> dict:
    labels = {}
    lifecheck = (raw.get("meta", {}) or {}).get("lifecheck") or {}
    for m in lifecheck.get("metrics") or []:
        if isinstance(m, dict) and m.get("id"):
            labels[m["id"]] = m.get("label", m["id"])
    return labels


def build_all(raw: dict, today: str = "") -> dict:
    """raw = {collection: {doc_id: fields}} -> {relative_path: content}.
    `today` (YYYY-MM-DD) anchors the open-loops age buckets and the DFT
    check; defaults to the newest date in the data so the function stays
    pure/deterministic for tests. dayos_sync passes the real IST date."""
    files = {}
    bd = _index_by_date(raw)
    metric_labels = _metric_labels(raw)
    today = today or (max(bd["all_dates"]) if bd["all_dates"] else "")

    for d in sorted(bd["all_dates"]):
        files[f"days/{d}.md"] = render_day(
            d, bd["blocks"].get(d, []), bd["journals"].get(d),
            bd["captures"].get(d, []), bd["sessions"].get(d, []),
            bd["learning"].get(d, []), bd["ratings"].get(d),
            bd["life"].get(d, {}), bd["eod"].get(d, ""),
            bd["dfts"].get(d), metric_labels,
        )

    weeks = {week_start(d) for d in bd["all_dates"] if week_start(d)}
    weeks |= {w for w in raw.get("weeklyReviews", {}) if _parse_date(w)}
    for ws in sorted(weeks):
        files[f"weeks/{ws}.md"] = render_week(ws, bd, raw.get("weeklyReviews", {}).get(ws))

    months = defaultdict(list)
    for d in bd["all_dates"]:
        months[d[:7]].append(d)
    for ym in raw.get("monthlyReviews", {}):
        months.setdefault(ym, [])
    for ym in sorted(months):
        files[f"months/{ym}.md"] = render_month(
            ym, sorted(months[ym]), bd, raw.get("monthlyReviews", {}).get(ym))

    # Projects: canonical list from meta/projects, plus any seen on sessions.
    meta = raw.get("meta", {}) or {}
    names = list((meta.get("projects") or {}).get("list") or [])
    seen = {project_slug(n) for n in names}
    for s in raw.get("sessions", {}).values():
        if not_trashed(s) and s.get("projectName") and project_slug(s["projectName"]) not in seen:
            names.append(s["projectName"])
            seen.add(project_slug(s["projectName"]))
    live_learning = [e for e in raw.get("learning", {}).values() if not_trashed(e)]
    for name in names:
        slug = project_slug(name)
        if not slug:
            continue
        p_sessions = [s for s in raw.get("sessions", {}).values()
                      if not_trashed(s) and project_slug(s.get("projectName", "")) == slug]
        p_captures = [c for c in raw.get("captures", {}).values()
                      if not_trashed(c) and (
                          project_slug(c.get("project_tag") or "") == slug
                          or slug in {project_slug(t) for t in c.get("tags") or []})]
        p_blocks = [b for b in raw.get("blocks", {}).values()
                    if not_trashed(b) and _block_project(b) == slug]
        p_learning = [e for e in live_learning
                      if slug in {project_slug(t) for t in e.get("tags") or []}]
        if p_sessions or p_captures or p_blocks or p_learning:
            files[f"projects/{slug}.md"] = render_project(
                name, slug, p_sessions, p_captures, p_blocks, p_learning)

    if live_learning:
        files["learning.md"] = render_learning(live_learning)

    # Phase A lenses (docs/DAYOS_ORGANIZATION.md): tag views — specials
    # always, others by use count, project tags excluded (projects/ already
    # gives those a richer view). Tags sharing a filename merge into one view.
    tagged = _collect_tagged(raw)
    project_slugs = {project_slug(n) for n in names if project_slug(n)}
    view_tags = set(SPECIAL_TAGS) | {
        t for t, entries in tagged.items()
        if len(entries) >= TAG_VIEW_MIN_USES and project_slug(t) not in project_slugs
    }
    by_file = defaultdict(list)
    for t in sorted(view_tags):
        if tag_filename(t):
            by_file[tag_filename(t)].append(t)
    for fname, tags_ in by_file.items():
        entries = [e for t in tags_ for e in tagged.get(t, [])]
        files[f"tags/{fname}.md"] = render_tag_view(" / ".join(tags_), entries)

    files["open-loops.md"], files["never-closed.md"] = render_open_loops(raw, bd, today)
    files["metrics.csv"] = render_metrics(
        bd, _metrics_columns(metric_labels, bd), _adherence_rules(raw), today)

    files["index.md"] = _render_index(raw, bd, names)
    return files


def _metrics_columns(metric_labels: dict, bd: dict) -> list:
    """Check-in metric columns: the app's configured order first, then any
    extra ids seen in the data (sorted) so nothing logged is dropped."""
    ids = list(metric_labels)
    seen = {k for doc in bd["life"].values() for k, v in doc.items()
            if isinstance(v, (int, float))}
    return ids + sorted(seen - set(ids))


def _render_index(raw: dict, bd: dict, project_names: list) -> str:
    dates = sorted(bd["all_dates"])
    all_blocks = [b for lst in bd["blocks"].values() for b in lst]
    total, per_cat = _cat_totals(all_blocks)
    L = ["# DayOS memory bank — index", ""]
    if dates:
        L.append(f"Data from {dates[0]} to {dates[-1]} — {len(dates)} days with entries.")
    counts = []
    for coll, label in (("blocks", "activity blocks"), ("captures", "captures"),
                        ("dailyJournal", "daily journals"), ("sessions", "project sessions"),
                        ("learning", "learning entries")):
        n = sum(1 for x in raw.get(coll, {}).values() if not_trashed(x))
        if n:
            counts.append(f"{n} {label}")
    if counts:
        L.append("Contains: " + ", ".join(counts) + ".")
    if total:
        L.append(_totals_line("All-time logged", total, per_cat))
    slugs = [project_slug(n) for n in project_names if project_slug(n)]
    if slugs:
        L.append("Projects: " + " · ".join(slugs))
    L.append("")
    L.append("Layout: days/YYYY-MM-DD.md (daily digest) · weeks/<sunday>.md · "
             "months/YYYY-MM.md · projects/<slug>.md · tags/<tag>.md (per-tag "
             "views) · open-loops.md (pending, last 10 days) · never-closed.md "
             "(loops that outlived 10 days) · metrics.csv (one row per day) · "
             "learning.md · raw/*.json (exact Firestore mirror)")
    return "\n".join(L).rstrip() + "\n"
