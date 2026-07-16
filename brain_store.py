"""Read side of the brain memory bank: Claude Code session digests.

brain_sync.py keeps a read-only git checkout of the instatank/2ndbrain repo
(the second brain's storehouse) under memory/brain/repo/; this module reads
the `sessions/` lane inside it — the per-session digests the /save-to-brain
skill pushes there (topic, decisions, insights, open threads). The repo's
`memory/` subfolder is the bot's OWN nightly backup and is deliberately not
read — everything in it already has a first-class bank. Same contract as
playbook_store: every public function returns a capped plain string for the
model, and staleness warnings ride on every result (silent staleness is the
enemy).
"""

import json
import re

import memory

BRAIN_DIR = memory.MEMORY_DIR / "brain"
REPO_DIR = BRAIN_DIR / "repo"
STATUS_PATH = BRAIN_DIR / "sync_status.json"

MAX_RESULT_CHARS = 3500     # per tool result (same cap as the other banks)
STALE_AFTER_HOURS = 26      # timer runs 2-hourly; a day of silence is a fault

_TAG_QUERY = re.compile(r"#[a-z0-9_%]+$")


# --- Which files are the bank -------------------------------------------------

def digest_files() -> list:
    """(label, path) for every session digest, newest first. Labels are the
    filename stems — `YYYY-MM-DD--<project>--<topic>` per the repo's layout —
    so search results double as valid `session_digest` names."""
    sessions = REPO_DIR / "sessions"
    if not sessions.exists():
        return []
    return [(p.stem, p) for p in sorted(sessions.rglob("*.md"),
                                        key=lambda p: p.name, reverse=True)]


def has_data() -> bool:
    return (REPO_DIR / "sessions").exists()


# --- Status / staleness (same shape as playbook_store) ------------------------

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
                    f"WARNING: the session-digest mirror was last synced {age_h / 24:.1f} days ago — "
                    "it may be stale. Suggest the user runs /sync."
                )
        except ValueError:
            pass
    elif has_data():
        notes.append("WARNING: session digests present but no sync record — freshness unknown.")
    if status.get("last_error") and status.get("last_error_time", "") > (last or ""):
        notes.append(f"WARNING: the most recent brain sync FAILED: {status['last_error'][:200]}")
    return "\n".join(notes)


def _with_notes(text: str) -> str:
    note = staleness_note()
    return (note + "\n\n" + text) if note else text


def _cap(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... truncated — use search_session_digests for a narrower slice]"


def _listing(files: list, limit: int = 15) -> str:
    shown = files[:limit]
    lines = [label for label, _ in shown]
    more = len(files) - len(shown)
    if more > 0:
        lines.append(f"... and {more} older (search_session_digests finds them)")
    return "\n".join(lines)


# --- Whole-digest reads ---------------------------------------------------------

def _slug(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def digest(name: str) -> str:
    """Return one session digest by (forgiving) name: the label from a search
    result, a date, a project, topic words — every given word must appear."""
    if not has_data():
        return "No session digests synced yet — ask the user to run /sync first."
    files = digest_files()
    if not files:
        return "The brain mirror is synced but holds no session digests yet."
    terms = [_slug(t) for t in re.sub(r"\.md$", "", (name or "").strip(), flags=re.I).split()]
    terms = [t for t in terms if t]
    if not terms:
        return f"Which digest? Newest first:\n{_listing(files)}"
    matches = [(label, path) for label, path in files
               if all(t in _slug(label) for t in terms)]
    if not matches:
        return f"No session digest matching '{name}'. Newest first:\n{_listing(files)}"
    if len(matches) > 1:
        return (f"{len(matches)} digests match '{name}' — which one?\n"
                + _listing(matches))
    label, path = matches[0]
    try:
        return _with_notes(_cap(f"# {label}\n\n" + path.read_text(encoding="utf-8")))
    except OSError as e:
        return f"Could not read {label}: {e}"


# --- Search (same semantics as the other banks) ---------------------------------

def search(query: str) -> str:
    if not has_data():
        return "No session digests synced yet — ask the user to run /sync first."
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
    for label, path in digest_files():
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
        return _with_notes(f"No matches for '{q}' in the session-digest memory bank.")
    header = f"{total} matching sections for '{q}' (digests are newest first):"
    return _with_notes(_cap(header + "\n" + "\n".join(hits)))


# --- System-prompt note ----------------------------------------------------------

def prompt_note(max_chars: int = 700) -> str:
    """One compact ambient block so the model knows the bank exists. The
    digests themselves are fetched by tool — never stuffed into every prompt."""
    if not has_data():
        return ""
    files = digest_files()
    parts = ["## Claude Code session digests (his past AI working sessions)"]
    note = staleness_note()
    if note:
        parts.append(note)
    newest = files[0][0] if files else "none yet"
    parts.append(
        "Digests of his past Claude Code sessions — what was built, decided, "
        "and learned in each — live in a memory bank. Use them when he asks "
        "what was figured out, decided, or left open in a past session. Tools: "
        "search_session_digests (find a session/decision), session_digest "
        f"(read one digest). {len(files)} digests, newest: {newest}."
    )
    return "\n\n".join(parts)[:max_chars]
