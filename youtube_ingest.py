"""YouTube tagged-videos — fetch + bank writer (write side of the YouTube bank).

The tag is the act of sharing: the founder sends a YouTube link to the bot
(YouTube app → Share → Telegram), the bot fetches the video's title and — best
effort — its transcript (YouTube's own captions, auto-generated included),
previews what it found, and writes to the brain only after the "Add to brain"
button (confirm-first, same as file-drop ingestion). Watch history stays out
by standing decision; only deliberately tagged videos enter.

Transcript fetching scrapes the public watch page for caption tracks — no API
key, no cost, but YouTube increasingly blocks datacenter IPs, so this is
BEST-EFFORT BY DESIGN: failure is loud and interactive (the bot says so in
the preview and offers the fallback — the founder pastes a summary, e.g. from
Gemini's summarize button, and that is stored with the link instead).

Each save is a snapshot keyed by video id: re-sending the same link replaces
the earlier entry. Files: memory/youtube/videos/<video-id>.md (+ the raw
caption JSON under memory/youtube/raw/ so markdown can be rebuilt).
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

import memory

YOUTUBE_DIR = memory.MEMORY_DIR / "youtube"
VIDEOS_DIR = YOUTUBE_DIR / "videos"
RAW_DIR = YOUTUBE_DIR / "raw"
STATUS_PATH = YOUTUBE_DIR / "sync_status.json"

FETCH_TIMEOUT_S = 20
MAX_TRANSCRIPT_CHARS = 1_500_000   # ~3h podcast is ~200 KB; this is a sanity cap
PARAGRAPH_GAP_MS = 60_000          # start a new transcript paragraph every ~minute

# Browser-ish headers: YouTube serves the consent wall / bot page to bare clients.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",
}

# Every URL shape that carries a video id; the id itself is always [\w-]{11}.
_LINK_RES = (
    re.compile(r"https?://(?:www\.|m\.|music\.)?youtube\.com/(?:watch|shorts|live|embed)"
               r"(?:\?(?:[^\s]*?&)?v=|/)([\w-]{11})[^\s]*", re.I),
    re.compile(r"https?://youtu\.be/([\w-]{11})[^\s]*", re.I),
)


class TranscriptUnavailable(Exception):
    """Transcript could not be fetched; str(e) says why, in founder language."""


# --- Link detection -------------------------------------------------------------

def find_links(text: str) -> list:
    """All YouTube links in a text -> [(video_id, matched_url)], first-seen
    order, deduped by video id (the batch flow and the DayOS auto-fetch scan
    both feed whole blobs of text through this)."""
    matches = sorted((m.start(), m.group(1), m.group(0))
                     for rx in _LINK_RES for m in rx.finditer(text or ""))
    found, seen = [], set()
    for _pos, vid, url in matches:
        if vid not in seen:
            seen.add(vid)
            found.append((vid, url))
    return found


def find_link(text: str):
    """First YouTube link in a message -> (video_id, matched_url) or None."""
    links = find_links(text)
    return links[0] if links else None


def note_from(text: str, urls) -> str:
    """Whatever the founder wrote around the link(s) = his note on the video."""
    out = text or ""
    for url in ([urls] if isinstance(urls, str) else urls):
        out = out.replace(url, " ")
    return out.strip()


# --- HTTP (single seam, so tests can fake the network) ---------------------------

def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", errors="replace")


# --- Metadata + transcript fetch --------------------------------------------------

def _fetch_oembed(vid: str) -> dict:
    """Title + channel via YouTube's oEmbed endpoint — the robust, boring path
    (no key, not behind the bot checks that hit the watch page)."""
    q = urllib.parse.urlencode(
        {"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
    data = json.loads(_http_get(f"https://www.youtube.com/oembed?{q}"))
    return {"title": data.get("title", ""), "channel": data.get("author_name", "")}


def _balanced_json(text: str, start: int):
    """Parse the JSON value ([...] or {...}) starting at text[start]."""
    return json.JSONDecoder().raw_decode(text, start)[0]


def _caption_tracks(vid: str) -> list:
    """Scrape the watch page for its caption-track list. Raises
    TranscriptUnavailable with a plain-language reason on every failure mode."""
    try:
        html = _http_get(f"https://www.youtube.com/watch?v={vid}&hl=en")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise TranscriptUnavailable(f"couldn't reach YouTube from the server ({e})")
    marker = '"captionTracks":'
    idx = html.find(marker)
    if idx < 0:
        if "consent.youtube.com" in html or "sorry/index" in html:
            raise TranscriptUnavailable(
                "YouTube blocked the request (bot check on this server's IP)")
        raise TranscriptUnavailable("this video has no captions/transcript on YouTube")
    try:
        tracks = _balanced_json(html, idx + len(marker))
    except (json.JSONDecodeError, ValueError):
        raise TranscriptUnavailable("YouTube's page format changed — caption list unreadable")
    if not tracks:
        raise TranscriptUnavailable("this video has no captions/transcript on YouTube")
    return tracks


def _pick_track(tracks: list) -> dict:
    """Prefer human captions over auto-generated, English/Hindi over others."""
    def score(t):
        lang = (t.get("languageCode") or "").lower()
        manual = t.get("kind") != "asr"
        pref = 2 if lang.startswith("en") else (1 if lang.startswith("hi") else 0)
        return (manual, pref)
    return max(tracks, key=score)


def _track_label(track: dict) -> str:
    lang = track.get("languageCode", "?")
    return f"{lang}, auto-generated" if track.get("kind") == "asr" else lang


def _render_transcript(raw_json3: str) -> str:
    """YouTube's json3 caption payload -> timestamped markdown paragraphs
    (a new paragraph every ~minute, so search hits carry a position)."""
    events = json.loads(raw_json3).get("events", [])
    paras, current, para_start = [], [], None
    for ev in events:
        if ev.get("aAppend") or not ev.get("segs"):
            continue  # rolling-caption repeats / window events, not new words
        piece = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not piece:
            continue
        t = ev.get("tStartMs", 0)
        if para_start is None or t - para_start > PARAGRAPH_GAP_MS:
            if current:
                paras.append(" ".join(current))
            h, rem = divmod(t // 1000, 3600)
            current, para_start = [f"[{h}:{rem // 60:02d}:{rem % 60:02d}]"], t
        current.append(piece)
    if current:
        paras.append(" ".join(current))
    text = "\n\n".join(paras)
    if not text.strip():
        raise TranscriptUnavailable("the caption file came back empty")
    return text[:MAX_TRANSCRIPT_CHARS]


def fetch(vid: str) -> dict:
    """Everything the preview needs, in one call. Never raises: metadata and
    transcript each degrade independently, with the failure reason carried in
    the result so the bot can tell the founder exactly what happened."""
    info = {"vid": vid, "title": "", "channel": "",
            "transcript": None, "raw": None, "lang": "", "error": ""}
    try:
        info.update(_fetch_oembed(vid))
    except Exception as e:
        info["error"] = f"couldn't fetch the video's title ({e})"
    try:
        track = _pick_track(_caption_tracks(vid))
        base = track.get("baseUrl", "")
        sep = "&" if "?" in base else "?"
        raw = _http_get(base + sep + "fmt=json3")
        info["transcript"] = _render_transcript(raw)
        info["raw"] = raw
        info["lang"] = _track_label(track)
    except TranscriptUnavailable as e:
        info["error"] = str(e)
    except Exception as e:  # anything unexpected still degrades to the fallback
        info["error"] = f"transcript fetch failed ({e})"
    return info


# --- Bank writer ------------------------------------------------------------------

def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_status(status: dict) -> None:
    YOUTUBE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")


def record_error(err: str) -> None:
    """A confirmed save that then blows up must land in the status file so the
    health banner surfaces it (Rule 4)."""
    status = load_status()
    status["last_error"] = str(err)[:500]
    status["last_error_time"] = memory.now().isoformat()
    _save_status(status)


SOURCE_LABELS = {
    # what goes on the entry's "Source:" line, keyed by how the text arrived
    "transcript": None,  # rendered with the language, below
    "pasted_transcript": "full transcript (pasted by the user)",
    "summary": "manual summary (pasted by the user — not a full transcript)",
}


def ingest(vid: str, title: str, channel: str, body: str,
           source: str, lang: str = "", note: str = "", raw: str = "") -> str:
    """Write one video's snapshot (replacing any earlier one) and update the
    status file. `source` is 'transcript' (auto-fetched), 'pasted_transcript'
    or 'summary'; `body` is that text. Returns the confirmation line for
    Telegram."""
    if not (body or "").strip():
        raise ValueError("nothing to save — empty transcript/summary")
    if source not in SOURCE_LABELS:
        raise ValueError(f"unknown source kind: {source}")
    title = title.strip() or f"YouTube video {vid}"
    saved = memory.now().strftime("%Y-%m-%d")
    src_line = f"transcript ({lang})" if source == "transcript" \
        else SOURCE_LABELS[source]
    lines = [
        f"# {title}",
        "",
        f"- Channel: {channel.strip() or 'unknown'}",
        f"- URL: https://youtu.be/{vid}",
        f"- Saved: {saved}",
        f"- Source: {src_line}",
    ]
    if note.strip():
        lines.append(f"- User's note when saving: {note.strip()}")
    lines += ["", f"## {'Summary' if source == 'summary' else 'Transcript'}",
              "", body.strip(), ""]

    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    (VIDEOS_DIR / f"{vid}.md").write_text("\n".join(lines), encoding="utf-8")
    if raw:  # bank contract: keep the raw payload so markdown is rebuildable
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{vid}.json").write_text(raw, encoding="utf-8")

    status = load_status()
    status.setdefault("videos", {})[vid] = {
        "title": title,
        "channel": channel.strip(),
        "saved_at": memory.now().isoformat(),
        "source": source,
        "words": len(body.split()),
    }
    status["last_success"] = memory.now().isoformat()
    status.pop("last_error", None)
    status.pop("last_error_time", None)
    _save_status(status)

    what = {"transcript": f"full transcript, ~{len(body.split())} words",
            "pasted_transcript": f"your pasted transcript, ~{len(body.split())} words",
            "summary": "your pasted summary"}[source]
    return (f"Added to the brain: \"{title}\" ({channel.strip() or 'unknown channel'}) "
            f"— {what}. Ask me about it any time.")
