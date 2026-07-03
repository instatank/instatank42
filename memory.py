"""File-based memory: a profile file + dated session logs. No database.

Layout (all under ./memory/):
    profile.md            - who the user is + durable facts the agent saves
    sessions/YYYY-MM-DD.md - append-only log of each day's conversation
    usage/YYYY-MM.json     - daily spend tracking (written by budget.py)
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Kolkata")

MEMORY_DIR = Path(__file__).resolve().parent / "memory"
PROFILE_PATH = MEMORY_DIR / "profile.md"
SESSIONS_DIR = MEMORY_DIR / "sessions"

FACTS_HEADER = "## Facts the agent has learned"


def now() -> datetime:
    return datetime.now(TZ)


def load_profile() -> str:
    if PROFILE_PATH.exists():
        return PROFILE_PATH.read_text(encoding="utf-8")
    return "(no profile file found)"


def append_fact(fact: str) -> None:
    """Append one durable fact under the facts section of profile.md."""
    MEMORY_DIR.mkdir(exist_ok=True)
    text = PROFILE_PATH.read_text(encoding="utf-8") if PROFILE_PATH.exists() else ""
    line = f"- {fact.strip()} (saved {now().strftime('%Y-%m-%d')})"
    if FACTS_HEADER in text:
        text = text.rstrip() + "\n" + line + "\n"
    else:
        text = text.rstrip() + f"\n\n{FACTS_HEADER}\n{line}\n"
    PROFILE_PATH.write_text(text, encoding="utf-8")


def append_session(role: str, text: str) -> None:
    """Append one line to today's session log."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{now().strftime('%Y-%m-%d')}.md"
    stamp = now().strftime("%H:%M")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {role}: {text.strip()}\n")


def recent_sessions(max_chars: int = 6000) -> str:
    """Return the tail of the two most recent session logs (for context)."""
    if not SESSIONS_DIR.exists():
        return "(no session history yet)"
    files = sorted(SESSIONS_DIR.glob("*.md"))[-2:]
    if not files:
        return "(no session history yet)"
    chunks = []
    for path in files:
        chunks.append(f"### {path.stem}\n{path.read_text(encoding='utf-8')}")
    text = "\n".join(chunks)
    return text[-max_chars:]
