"""Read side of the playbook memory bank: the founder's cross-project rules.

playbook_sync.py keeps a read-only git checkout of the time-tracker repo under
memory/playbook/repo/; this module reads the principles docs inside it —
playbook/*.md (PLAYBOOK, NORTH_STAR, CURRICULUM, LEARNING_METHOD, SOPs,
templates) plus the repo-root LEARNINGS.md ledger. Same contract as
dayos_store: every public function returns a capped plain string for the
model, and staleness warnings ride on every result (silent staleness is the
enemy).
"""

import json
import re

import memory

PLAYBOOK_DIR = memory.MEMORY_DIR / "playbook"
REPO_DIR = PLAYBOOK_DIR / "repo"
STATUS_PATH = PLAYBOOK_DIR / "sync_status.json"

MAX_RESULT_CHARS = 3500     # per tool result (same cap as dayos_store)
STALE_AFTER_HOURS = 26      # timer runs 2-hourly; a day of silence is a fault

_TAG_QUERY = re.compile(r"#[a-z0-9_%]+$")


# --- Which files are the bank -------------------------------------------------

def doc_files() -> list:
    """(label, path) for every doc in the bank, stable order: the playbook
    folder first, then templates, then the LEARNINGS ledger."""
    out = []
    pb = REPO_DIR / "playbook"
    if pb.exists():
        for p in sorted(pb.glob("*.md")):
            out.append((f"playbook/{p.name}", p))
        for p in sorted((pb / "templates").glob("*.md")) if (pb / "templates").exists() else []:
            out.append((f"playbook/templates/{p.name}", p))
    learnings = REPO_DIR / "LEARNINGS.md"
    if learnings.exists():
        out.append(("LEARNINGS.md", learnings))
    return out


def has_data() -> bool:
    return (REPO_DIR / "playbook").exists()


# --- Status / staleness (same shape as dayos_store) ---------------------------

def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def staleness_note() -> str:
    status = load_status()
    notes = []
    last = status.get("last_success")
    if last:
        try:
            age_h = (memory.now() - memory.datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h > STALE_AFTER_HOURS:
                notes.append(
                    f"WARNING: the playbook mirror was last synced {age_h / 24:.1f} days ago — "
                    "it may be stale. Suggest the user runs /sync."
                )
        except ValueError:
            pass
    elif has_data():
        notes.append("WARNING: playbook files present but no sync record — freshness unknown.")
    if status.get("last_error") and status.get("last_error_time", "") > (last or ""):
        notes.append(f"WARNING: the most recent playbook sync FAILED: {status['last_error'][:200]}")
    return "\n".join(notes)


def _with_notes(text: str) -> str:
    note = staleness_note()
    return (note + "\n\n" + text) if note else text


def _cap(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... truncated — use search_playbook for a narrower slice]"


# --- Whole-document reads ------------------------------------------------------

def _slug(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def doc(name: str) -> str:
    """Return one document by (forgiving) name: 'playbook', 'north star',
    'curriculum', 'learnings', 'sop ship', 'build brief', ..."""
    if not has_data():
        return "No playbook synced yet — ask the user to run /sync first."
    files = doc_files()
    want = _slug(re.sub(r"\.md$", "", (name or "").strip(), flags=re.I))
    if not want:
        listing = ", ".join(label for label, _ in files)
        return f"Which document? Available: {listing}"
    for label, path in files:
        stem = _slug(path.stem)
        if want == stem or want in stem or stem in want:
            try:
                return _with_notes(_cap(f"# {label}\n\n" + path.read_text(encoding="utf-8")))
            except OSError as e:
                return f"Could not read {label}: {e}"
    listing = ", ".join(label for label, _ in files)
    return f"No playbook document matching '{name}'. Available: {listing}"


# --- Search (same semantics as dayos_store / the DayOS app) --------------------

def search(query: str) -> str:
    if not has_data():
        return "No playbook synced yet — ask the user to run /sync first."
    q = (query or "").strip()
    if not q:
        return "Empty search query."

    if _TAG_QUERY.fullmatch(q.lower()):
        pattern = re.compile(re.escape(q.lower()) + r"(?![a-z0-9_%])")
        matcher = lambda line: bool(pattern.search(line.lower()))
    else:
        terms = [t.lower() for t in q.split()]
        matcher = lambda line: all(t in line.lower() for t in terms)

    hits, total = [], 0
    for label, path in doc_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
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
        return _with_notes(f"No matches for '{q}' in the playbook memory bank.")
    header = f"{total} matching sections for '{q}':"
    return _with_notes(_cap(header + "\n" + "\n".join(hits)))


# --- System-prompt note ----------------------------------------------------------

def prompt_note(max_chars: int = 700) -> str:
    """One compact ambient block so the model knows the bank exists. The docs
    themselves are fetched by tool — never stuffed into every prompt."""
    if not has_data():
        return ""
    parts = ["## Playbook (his cross-project working rules + lessons)"]
    note = staleness_note()
    if note:
        parts.append(note)
    names = ", ".join(label for label, _ in doc_files())
    parts.append(
        "He runs all his projects by a written playbook. Quote it when he asks "
        "about his own rules, lessons, methods, or priorities. Tools: "
        "search_playbook (find a rule/lesson), playbook_doc (read one document). "
        f"Documents: {names}."
    )
    return "\n\n".join(parts)[:max_chars]
