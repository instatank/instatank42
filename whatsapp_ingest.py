"""WhatsApp chat-export parser + bank writer (write side of the WhatsApp bank).

The founder exports a chat from WhatsApp itself (Settings → Export chat →
Without media) and sends the .txt (or the iOS .zip) to the bot on Telegram;
ingest.py routes it here. Each ingest is a SNAPSHOT: it fully replaces that
chat's directory under memory/whatsapp/chats/<slug>/ — no merging, no dedup,
re-export whenever a refresh is wanted. Live sync via unofficial WhatsApp
libraries was rejected (ToS ban risk, see docs/BACKLOG.md).

Handles both export dialects:
    Android:  12/06/26, 10:15 pm - Rohan: message
    iOS:      [12/06/26, 22:15:33] Rohan: message   (+ stray U+200E/U+200F marks)
Multi-line messages continue on lines that don't match the header pattern.
Day-first dates are assumed (India) unless the file itself proves month-first.
"""

import json
import re
import shutil
from datetime import datetime

import memory

WHATSAPP_DIR = memory.MEMORY_DIR / "whatsapp"
CHATS_DIR = WHATSAPP_DIR / "chats"
STATUS_PATH = WHATSAPP_DIR / "sync_status.json"

# One regex per dialect; both yield (day-ish, month-ish, year, h, m, s?, am/pm?, rest)
_IOS_RE = re.compile(
    r"^\[(\d{1,2})[./](\d{1,2})[./](\d{2,4}),? (\d{1,2}):(\d{2})(?::(\d{2}))? ?([APap][Mm])?\] (.*)$")
_ANDROID_RE = re.compile(
    r"^(\d{1,2})[./](\d{1,2})[./](\d{2,4}),? (\d{1,2}):(\d{2})(?::(\d{2}))? ?([APap][Mm])? - (.*)$")

_FILENAME_NAME_RES = (
    re.compile(r"whatsapp chat with (.+?)(?:\.txt|\.zip)?$", re.I),
    re.compile(r"whatsapp chat - (.+?)(?:\.txt|\.zip)?$", re.I),
)

MIN_HEADER_LINES = 3        # fewer matching lines than this -> not a WhatsApp export


def _clean(line: str) -> str:
    """Strip the invisible unicode WhatsApp sprinkles into iOS exports."""
    return line.replace("‎", "").replace("‏", "") \
               .replace(" ", " ").replace(" ", " ")


def _header_match(line: str):
    return _IOS_RE.match(line) or _ANDROID_RE.match(line)


def _day_first(lines: list) -> bool:
    """Assume DD/MM (India) unless some line's second field exceeds 12."""
    for line in lines:
        m = _header_match(line)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12:
            return True
        if b > 12:
            return False
    return True


def parse(text: str) -> list:
    """Export text -> [{'ts': datetime, 'sender': str|None, 'text': str}]
    (sender None = a system line: encryption banner, joins, etc.)."""
    lines = [_clean(ln) for ln in text.lstrip("﻿").splitlines()]
    day_first = _day_first(lines)
    messages = []
    for line in lines:
        m = _header_match(line)
        if not m:
            # continuation of the previous message (or pre-header junk)
            if messages and line.strip():
                messages[-1]["text"] += "\n" + line.strip()
            continue
        a, b, year, hh, mm, ss, ampm, rest = m.groups()
        day, month = (int(a), int(b)) if day_first else (int(b), int(a))
        y = int(year) + (2000 if len(year) == 2 else 0)
        hour = int(hh)
        if ampm:
            hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
        try:
            ts = datetime(y, month, day, hour, int(mm), int(ss or 0))
        except ValueError:
            continue  # a text line that only looks like a header
        sender, _, body = rest.partition(": ")
        if _:
            messages.append({"ts": ts, "sender": sender.strip(), "text": body})
        else:
            messages.append({"ts": ts, "sender": None, "text": rest})
    messages.sort(key=lambda m: m["ts"])
    return messages


def chat_name(filename: str, messages: list) -> str:
    """Chat name from the export's filename; participants as the fallback
    (iOS zips contain an anonymous '_chat.txt')."""
    stem = _clean(filename or "").strip()
    for rx in _FILENAME_NAME_RES:
        m = rx.search(stem)
        if m:
            return m.group(1).strip()
    senders = []
    for msg in messages:
        if msg["sender"] and msg["sender"] not in senders:
            senders.append(msg["sender"])
    return " & ".join(senders[:4]) if senders else "unknown chat"


def _slug(name: str) -> str:
    s = str(name or "").lower()
    out = "".join(ch if (ch.isascii() and ch.isalnum()) else "-" for ch in s)
    return re.sub(r"-+", "-", out).strip("-") or "chat"


# --- Detection (ingest.py contract) -------------------------------------------

def detect(filename: str, text: str):
    """Return a preview dict when this looks like a WhatsApp export, else None."""
    lines = [_clean(ln) for ln in text.lstrip("﻿").splitlines()]
    if sum(1 for ln in lines if _header_match(ln)) < MIN_HEADER_LINES:
        return None
    messages = parse(text)
    if len(messages) < MIN_HEADER_LINES:
        return None
    name = chat_name(filename, messages)
    senders = sorted({m["sender"] for m in messages if m["sender"]})
    first, last = messages[0]["ts"], messages[-1]["ts"]
    preview = (
        f"Looks like a WhatsApp export of \"{name}\" — {len(messages)} messages, "
        f"{len(senders)} senders, {first:%Y-%m-%d} to {last:%Y-%m-%d}. "
        "Ingesting replaces any earlier snapshot of this chat."
    )
    return {"chat": name, "messages": len(messages), "preview": preview}


# --- Bank writer ----------------------------------------------------------------

def _month_files(name: str, messages: list) -> dict:
    """Group into {'YYYY-MM': markdown} — one file per month, one paragraph
    per day (so multi-term search can span a day's conversation)."""
    months = {}
    for msg in messages:
        months.setdefault(msg["ts"].strftime("%Y-%m"), []).append(msg)
    out = {}
    for key, msgs in months.items():
        parts = [f"# WhatsApp — {name} — {key}"]
        day, chunk = None, []
        for msg in msgs + [None]:
            d = msg["ts"].strftime("%Y-%m-%d") if msg else None
            if d != day:
                if chunk:
                    parts.append("\n".join(chunk))
                day, chunk = d, ([f"## {d}"] if d else [])
            if msg is None:
                break
            who = msg["sender"] or "(system)"
            body = msg["text"].replace("\n", "\n  ")
            chunk.append(f"[{msg['ts']:%H:%M}] {who}: {body}")
        out[key] = "\n\n".join(parts) + "\n"
    return out


def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_status(status: dict) -> None:
    WHATSAPP_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")


def record_error(err: str) -> None:
    """Called (via ingest.py) when an ingest blows up — the failure must land
    in sync_status.json so the health banner surfaces it (Rule 4)."""
    status = load_status()
    status["last_error"] = str(err)[:500]
    status["last_error_time"] = memory.now().isoformat()
    _save_status(status)


def ingest(filename: str, text: str) -> str:
    """Parse and write one chat's snapshot; returns the summary for Telegram."""
    messages = parse(text)
    if not messages:
        raise ValueError("no parseable WhatsApp messages in the file")
    name = chat_name(filename, messages)
    slug = _slug(name)
    files = _month_files(name, messages)

    chat_dir = CHATS_DIR / slug
    if chat_dir.exists():
        shutil.rmtree(chat_dir)  # snapshot semantics: replace, never merge
    chat_dir.mkdir(parents=True)
    for key, body in files.items():
        (chat_dir / f"{key}.md").write_text(body, encoding="utf-8")
    # bank contract: keep the raw export too, so the markdown can always be
    # rebuilt (e.g. after a parser fix) without asking for a re-export
    raw_dir = WHATSAPP_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{slug}.txt").write_text(text, encoding="utf-8")

    first, last = messages[0]["ts"], messages[-1]["ts"]
    status = load_status()
    status.setdefault("chats", {})[slug] = {
        "name": name,
        "file": filename,
        "ingested_at": memory.now().isoformat(),
        "messages": len(messages),
        "first": first.strftime("%Y-%m-%d"),
        "last": last.strftime("%Y-%m-%d"),
    }
    status["last_success"] = memory.now().isoformat()
    status.pop("last_error", None)
    status.pop("last_error_time", None)
    _save_status(status)

    return (
        f"Added WhatsApp chat \"{name}\" to the brain: {len(messages)} messages "
        f"({first:%Y-%m-%d} → {last:%Y-%m-%d}), {len(files)} monthly file(s). "
        "This snapshot replaced any earlier one — re-export the chat whenever "
        "you want it refreshed."
    )


# The contract ingest.py's registry expects from every parser.
PARSER = {
    "name": "whatsapp",
    "detect": detect,
    "ingest": ingest,
    "record_error": record_error,
}
