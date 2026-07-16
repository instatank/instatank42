"""Read side of the YouTube memory bank: the query functions the bot's tools call.

Reads the plain files youtube_ingest.py writes under memory/youtube/ — no
network. Same contract as the other stores: every public function returns a
capped plain string, and warnings ride on every result.

Freshness: like WhatsApp, entries are deliberate snapshots (the founder tags
a video by sending its link), so there is no staleness alarm for age — a
saved video doesn't go stale. Save FAILURES do ride the health banner via
the same status-file shape as the other banks. Every result reminds the
model when an entry is a pasted summary rather than a full transcript.
"""

import json
import re

import memory

YOUTUBE_DIR = memory.MEMORY_DIR / "youtube"
VIDEOS_DIR = YOUTUBE_DIR / "videos"
STATUS_PATH = YOUTUBE_DIR / "sync_status.json"

MAX_RESULT_CHARS = 3500     # per tool result (same cap as the other banks)

_TAG_QUERY = re.compile(r"#[a-z0-9_%]+$")


# --- Availability / status ----------------------------------------------------

def has_data() -> bool:
    return VIDEOS_DIR.exists() and any(VIDEOS_DIR.glob("*.md"))


def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def staleness_note() -> str:
    """Only save FAILURES belong on the health banner — snapshot age is by
    design here (a saved video doesn't go stale)."""
    status = load_status()
    if status.get("last_error") and \
            status.get("last_error_time", "") > status.get("last_success", ""):
        return f"WARNING: the most recent YouTube save FAILED: {status['last_error'][:200]}"
    return ""


def _videos() -> dict:
    return load_status().get("videos", {})


def _with_notes(text: str) -> str:
    parts = [n for n in (staleness_note(),) if n]
    parts.append(text)
    return "\n\n".join(parts)


def _cap(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... truncated — use search_youtube for a narrower slice]"


# --- Video lookup ----------------------------------------------------------------

def _resolve(name: str):
    """Forgiving match on video id or title words; (vid, info) or (None, error)."""
    videos = _videos()
    want = (name or "").strip()
    if want in videos:
        return want, videos[want]
    terms = [t for t in want.lower().split() if t]
    matches = [v for v, i in videos.items()
               if terms and all(t in i.get("title", "").lower() for t in terms)]
    if len(matches) == 1:
        return matches[0], videos[matches[0]]
    listing = "; ".join(f"\"{i.get('title', v)}\"" for v, i in sorted(
        videos.items(), key=lambda kv: kv[1].get("saved_at", ""), reverse=True)[:15])
    hint = "Multiple matches" if len(matches) > 1 else "No saved video matching"
    return None, f"{hint} '{name}'. Saved videos: {listing or '(none yet)'}"


def video(name: str) -> str:
    """One saved video's full entry (transcript or summary), by title or id."""
    if not has_data():
        return "No YouTube videos saved yet — send the bot a YouTube link to tag one."
    vid, info = _resolve(name)
    if vid is None:
        return info
    path = VIDEOS_DIR / f"{vid}.md"
    if not path.exists():
        return f"Entry for \"{info.get('title', vid)}\" is missing its file — re-send the link."
    return _with_notes(_cap(path.read_text(encoding="utf-8")))


# --- Search -----------------------------------------------------------------------

def search(query: str) -> str:
    """Same semantics as the other banks: one '#tag' = exact tag, anything else
    = case-insensitive AND. Paragraph unit = one transcript paragraph (~a
    minute of speech), labeled with the video's title. Newest saves first."""
    if not has_data():
        return "No YouTube videos saved yet — send the bot a YouTube link to tag one."
    q = (query or "").strip()
    if not q:
        return "Empty search query."

    if _TAG_QUERY.fullmatch(q.lower()):
        pattern = re.compile(re.escape(q.lower()) + r"(?![a-z0-9_%])")
        matcher = lambda text: bool(pattern.search(text.lower()))
    else:
        terms = [t.lower() for t in q.split()]
        matcher = lambda text: all(t in text.lower() for t in terms)

    videos = _videos()
    order = sorted(videos, key=lambda v: videos[v].get("saved_at", ""), reverse=True)
    hits, total = [], 0
    for vid in order:
        path = VIDEOS_DIR / f"{vid}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        label = videos[vid].get("title", vid)
        if len(label) > 60:
            label = label[:60] + "…"
        for para in text.split("\n\n"):
            if not matcher(para):
                continue
            snippet = " ".join(para.split())
            if len(snippet) > 280:
                snippet = snippet[:280] + "…"
            hits.append(f"[{label}] {snippet}")
            total += 1
            if len(hits) >= 30:
                break
        if len(hits) >= 30:
            break

    if not hits:
        return _with_notes(f"No matches for '{q}' in the saved YouTube videos.")
    header = f"{total} matching passages for '{q}' (newest saves first):"
    return _with_notes(_cap(header + "\n" + "\n".join(hits)))


# --- System-prompt note --------------------------------------------------------

def prompt_note(max_chars: int = 700) -> str:
    """Compact ambient block: what's saved. Content is fetched by tool only."""
    if not has_data():
        return ""
    videos = _videos()
    recent = sorted(videos.values(), key=lambda i: i.get("saved_at", ""), reverse=True)
    titles = ", ".join(f"\"{i.get('title', '?')[:45]}\"" for i in recent[:5])
    parts = ["## YouTube (videos he chose to save)"]
    note = staleness_note()
    if note:
        parts.append(note)
    parts.append(
        f"{len(videos)} saved video(s), latest: {titles}. Use for 'that video "
        "about X I saved'. Tools: search_youtube (find passages), "
        "youtube_video (read one video's transcript/summary). Entries marked "
        "'manual summary' are his pasted notes, not full transcripts."
    )
    return "\n\n".join(parts)[:max_chars]
