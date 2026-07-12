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
    learning.md           full learning log, newest first
    index.md              overview: date range, totals, project list

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
CTYPES = {
    "note": "Quick Note",
    "daily": "Daily Journal",
    "project": "Project Note",
    "insight": "Insight",   # legacy
    "journal": "Journal",   # legacy
}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --- Small helpers ---------------------------------------------------------

def not_trashed(doc: dict) -> bool:
    return isinstance(doc, dict) and not doc.get("deletedAt")


def live_items(arr) -> list:
    return [a for a in (arr or []) if isinstance(a, dict) and not a.get("deletedAt")]


def project_slug(name: str) -> str:
    """Mirror of DayOS projectSlug(): lowercase, strip leading '#', keep [a-z0-9_%]."""
    s = str(name or "").lower().lstrip("#")
    return "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch in "_%"))


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
        lines = _review_lines(review)
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
        lines = _review_lines(review)
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


def build_all(raw: dict) -> dict:
    """raw = {collection: {doc_id: fields}} -> {relative_path: content}."""
    files = {}
    bd = _index_by_date(raw)
    metric_labels = _metric_labels(raw)

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

    files["index.md"] = _render_index(raw, bd, names)
    return files


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
             "months/YYYY-MM.md · projects/<slug>.md · learning.md · raw/*.json "
             "(exact Firestore mirror)")
    return "\n".join(L).rstrip() + "\n"
