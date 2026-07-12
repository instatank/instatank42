"""Read side of the WhatsApp memory bank: the query functions the bot's tools call.

Reads the plain files whatsapp_ingest.py writes under memory/whatsapp/ — no
network. Same contract as dayos_store/playbook_store: every public function
returns a capped plain string, and warnings ride on every result.

Freshness works differently here than the synced banks: WhatsApp data is a
MANUAL SNAPSHOT (the founder re-exports a chat to refresh it), so there's no
"sync is broken" alarm for age. Instead every result carries each chat's
coverage line ("covers to <date>") so the model can never mistake a June
export for live data — plus a re-export nudge once a snapshot is old.
Ingest FAILURES do ride the health banner, via the same status-file shape
as the other banks.
"""

import json
import re

import memory
import whatsapp_ingest

WHATSAPP_DIR = memory.MEMORY_DIR / "whatsapp"
CHATS_DIR = WHATSAPP_DIR / "chats"
STATUS_PATH = WHATSAPP_DIR / "sync_status.json"

MAX_RESULT_CHARS = 3500     # per tool result (same cap as the other banks)
REEXPORT_NUDGE_DAYS = 45    # suggest a fresh export past this snapshot age

_TAG_QUERY = re.compile(r"#[a-z0-9_%]+$")


# --- Availability / status ----------------------------------------------------

def has_data() -> bool:
    return CHATS_DIR.exists() and any(CHATS_DIR.glob("*/*.md"))


def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def staleness_note() -> str:
    """Only ingest FAILURES belong on the health banner — snapshot age is by
    design here (manual exports), handled by coverage notes instead."""
    status = load_status()
    if status.get("last_error") and \
            status.get("last_error_time", "") > status.get("last_success", ""):
        return f"WARNING: the most recent WhatsApp ingest FAILED: {status['last_error'][:200]}"
    return ""


def _chats() -> dict:
    return load_status().get("chats", {})


def _coverage_note() -> str:
    """One line per chat: what the snapshot covers, so answers are never
    mistaken for live data. Includes a nudge when a snapshot has aged out."""
    lines = []
    for slug, info in sorted(_chats().items()):
        line = f"\"{info.get('name', slug)}\" covers to {info.get('last', '?')}"
        try:
            exported = memory.datetime.fromisoformat(info.get("ingested_at", ""))
            age_d = (memory.now() - exported).days
            line += f" (exported {age_d}d ago"
            if age_d > REEXPORT_NUDGE_DAYS:
                line += " — suggest re-exporting for anything recent"
            line += ")"
        except ValueError:
            pass
        lines.append(line)
    if not lines:
        return ""
    return "Note: WhatsApp data is manual snapshots — nothing newer than each export is visible. " \
           + "; ".join(lines) + "."


def _with_notes(text: str) -> str:
    parts = [n for n in (staleness_note(), _coverage_note()) if n]
    parts.append(text)
    return "\n\n".join(parts)


def _cap(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... truncated — use search_whatsapp for a narrower slice]"


# --- Chat lookup ----------------------------------------------------------------

def _resolve_chat(name: str):
    """Forgiving chat match on slug or display name; returns (slug, info) or
    (None, error_text)."""
    chats = _chats()
    want = whatsapp_ingest._slug(name)
    if want in chats:
        return want, chats[want]
    matches = [s for s in chats
               if want and (want in s or s in want
                            or want in whatsapp_ingest._slug(chats[s].get("name", "")))]
    if len(matches) == 1:
        return matches[0], chats[matches[0]]
    listing = ", ".join(f"\"{i.get('name', s)}\"" for s, i in sorted(chats.items())) or "(none yet)"
    return None, f"No WhatsApp chat matching '{name}'. Ingested chats: {listing}"


def chat(name: str, month: str = "") -> str:
    """One chat's messages: a specific 'YYYY-MM' month file, or the most
    recent month by default."""
    if not has_data():
        return "No WhatsApp chats ingested yet — send the bot a chat export (.txt or .zip) first."
    slug, info = _resolve_chat(name)
    if slug is None:
        return info
    files = sorted((CHATS_DIR / slug).glob("*.md"))
    if not files:
        return f"Chat \"{info.get('name', slug)}\" has no message files (re-export it?)."
    m = (month or "").strip()
    if m:
        if not re.fullmatch(r"\d{4}-\d{2}", m):
            return f"Could not parse month '{month}' — use YYYY-MM."
        path = CHATS_DIR / slug / f"{m}.md"
        if not path.exists():
            avail = ", ".join(p.stem for p in files)
            return _with_notes(f"No {m} messages in \"{info.get('name', slug)}\". Months on file: {avail}")
    else:
        path = files[-1]
    return _with_notes(_cap(path.read_text(encoding="utf-8")))


# --- Search -----------------------------------------------------------------------

def search(query: str, chat_name: str = "") -> str:
    """Same semantics as the other banks: one '#tag' = exact tag, anything
    else = case-insensitive AND. Paragraph unit = one day of one chat, so a
    multi-term query can span a day's back-and-forth. Newest first."""
    if not has_data():
        return "No WhatsApp chats ingested yet — send the bot a chat export (.txt or .zip) first."
    q = (query or "").strip()
    if not q:
        return "Empty search query."
    slugs = sorted(_chats())
    if (chat_name or "").strip():
        slug, info = _resolve_chat(chat_name)
        if slug is None:
            return info
        slugs = [slug]

    if _TAG_QUERY.fullmatch(q.lower()):
        pattern = re.compile(re.escape(q.lower()) + r"(?![a-z0-9_%])")
        matcher = lambda line: bool(pattern.search(line.lower()))
    else:
        terms = [t.lower() for t in q.split()]
        matcher = lambda line: all(t in line.lower() for t in terms)

    hits, total = [], 0
    for slug in slugs:
        label = _chats().get(slug, {}).get("name", slug)
        for path in sorted((CHATS_DIR / slug).glob("*.md"), reverse=True):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for para in text.split("\n\n"):
                if not matcher(para):
                    continue
                day = para.splitlines()[0].lstrip("# ").strip() if para.startswith("##") else path.stem
                lines = [ln for ln in para.splitlines() if matcher(ln)] or para.splitlines()[:2]
                for ln in lines[:3]:
                    snippet = ln.strip()
                    if len(snippet) > 240:
                        snippet = snippet[:240] + "…"
                    hits.append(f"[{label} {day}] {snippet}")
                total += 1
                if len(hits) >= 40:
                    break
            if len(hits) >= 40:
                break
        if len(hits) >= 40:
            break

    if not hits:
        return _with_notes(f"No matches for '{q}' in the WhatsApp memory bank.")
    header = f"{total} matching days for '{q}' (newest first):"
    return _with_notes(_cap(header + "\n" + "\n".join(hits)))


# --- System-prompt note --------------------------------------------------------

def prompt_note(max_chars: int = 700) -> str:
    """Compact ambient block: which chats exist and what they cover. The
    messages themselves are fetched by tool, never stuffed into every prompt."""
    if not has_data():
        return ""
    parts = ["## WhatsApp (manual chat-export snapshots)"]
    note = staleness_note()
    if note:
        parts.append(note)
    cov = _coverage_note()
    if cov:
        parts.append(cov)
    parts.append(
        "Use for 'what did we discuss/agree with X'. Tools: search_whatsapp "
        "(find messages), whatsapp_chat (read one chat, month by month)."
    )
    return "\n\n".join(parts)[:max_chars]
