"""Backfill past Claude Code sessions into the second brain — a Mac-local
utility, NOT part of the deployed bot (same category as wispr_export.py).

The /save-to-brain skill captures a session going forward. This script does the
one-time backfill: it walks Claude Code's own on-disk session transcripts,
condenses each into the same decisions/insights digest the skill writes, and
commits them to a local clone of instatank/2ndbrain — so a whole history of
past sessions enters the brain without resuming each one by hand.

WHY THIS MIGHT FIND NOTHING (read before trusting it): Claude Code stores a
transcript per session only for sessions that EXECUTE LOCALLY on this Mac, under
~/.claude/projects/<escaped-cwd>/<session-id>.jsonl. Desktop-app sessions that
run in the cloud leave no local file. Which mode your sessions use is something
only a run on your actual Mac reveals — so `--list` is step one: it prints what
it found (or says plainly that nothing is here). Everything below is UNVERIFIED
against a real transcript from this repo's cloud sessions; the JSONL parsing is
deliberately schema-adaptive and degrades loudly, and the first real run on the
Mac is what confirms the schema. (This is the same lesson as wispr_export.py.)

Design choices, matching the house style:
- stdlib only (urllib for the Anthropic call) — runs on a bare Mac with no venv
  or pip install, exactly like wispr_export.py and dayos_client.py's raw REST.
- Reads only. It never modifies Claude Code's session files.
- Tool calls, tool results, thinking blocks and file dumps are STRIPPED before
  the model ever sees a transcript — the insight density is in the prose, and
  stripping is also the main defense against a secret in some tool output
  reaching the digest.
- Nothing is pushed by default. Digests are written into a local 2ndbrain clone
  and committed once; you review `git log`/`git diff`, then push (or pass
  --push). Bulk work still shows you what entered the brain.
- A session already backfilled (its id already appears in a digest in the repo)
  is skipped, so re-runs are safe and resumable.

Usage:
    python3 brain_backfill.py --list                 # what sessions exist? (write nothing)
    python3 brain_backfill.py --dry-run              # plan + cost estimate (write nothing)
    python3 brain_backfill.py                        # backfill; commit locally, don't push
    python3 brain_backfill.py --since 2026-06-01 --project instatank42
    python3 brain_backfill.py --limit 10 --yes --push
Env:
    ANTHROPIC_API_KEY   required for a real run (not for --list/--dry-run)
    BACKFILL_MODEL      override the model (default claude-sonnet-5)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_REPO = Path.home() / "2ndbrain"

MODEL = os.environ.get("BACKFILL_MODEL", "claude-sonnet-5")
MAX_TOKENS = 2000                 # digests are short; this is generous headroom
TRANSCRIPT_CHAR_CAP = 180_000     # ~45k tokens per session, bounds cost + context
MIN_TURNS = 4                     # fewer real prose turns than this = skip as trivial
API_URL = "https://api.anthropic.com/v1/messages"

# Approximate prices per million tokens, for the up-front estimate only. Sonnet 5
# intro pricing ($2/$10 through 2026-08) is the default; Haiku is the cheap bulk
# option. These are estimates — the real bill is whatever Anthropic charges.
PRICES = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
}

SYSTEM = """You condense one Claude Code coding session into a durable markdown \
digest for a non-technical founder's "second brain". Write for a reader who did \
NOT see the conversation. This is a synthesis, not a transcript.

Output ONLY the digest, as markdown, in exactly this shape (drop any section \
with no real content):

# <short, specific title of what the session was about>

- Date: <the date given below>
- Project: <the project given below>

## What this session was about
2-4 sentences: the ask and why it mattered.

## Decisions made
One bullet per decision, WITH the reasoning ("chose X over Y because ..."). \
Decisions are the highest-value content — never drop one.

## Insights & learnings
Gotchas, derived facts, approaches that failed and why. Skip generic knowledge.

## What shipped / state of the work
What was built or changed, and whether it's tested/deployed/merged.

## Open items
What's unfinished, blocked, or deferred.

Rules: plain prose, complete sentences, no tool-call noise. NEVER include \
secrets (tokens, API keys, .env contents) even if they appear in the input. If \
the session was trivial, say so in two lines rather than padding."""


# --- Locate + parse session transcripts ---------------------------------------

def iter_session_files(projects_dir: Path):
    """Every *.jsonl transcript under ~/.claude/projects/, newest first."""
    if not projects_dir.is_dir():
        return []
    files = list(projects_dir.rglob("*.jsonl"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _text_from_content(content) -> str:
    """A message's content -> just its human prose. Content is either a plain
    string or a list of blocks; keep text blocks, drop tool_use / tool_result /
    thinking / images (machine noise, and where secrets would hide)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")).strip())
            elif isinstance(block, str):
                parts.append(block.strip())
        return "\n".join(p for p in parts if p)
    return ""


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _project_label(path: Path) -> str:
    """Claude Code names the project dir by escaping the cwd (slashes -> '-'),
    e.g. '-Users-ankit-Code-instatank42'. The trailing segment is the repo."""
    name = path.parent.name.strip("-")
    seg = name.split("-")[-1] if name else ""
    return seg or "general"


def parse_session(path: Path) -> dict:
    """One transcript -> {id, project, turns, start, end, first_user, ...}.
    Schema-adaptive: tolerates content as string or block-list, missing
    timestamps, summary/meta lines, and subagent sidechains (skipped)."""
    turns, timestamps = [], []
    n_lines = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("isSidechain"):          # subagent thread, not the main convo
            continue
        n_lines += 1
        ts = _parse_ts(obj.get("timestamp"))
        if ts:
            timestamps.append(ts)
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        role = msg.get("role") or obj.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _text_from_content(msg.get("content"))
        # A user turn that was purely a tool_result carries no prose -> skip it.
        if text:
            turns.append((role, text))

    start = min(timestamps) if timestamps else None
    end = max(timestamps) if timestamps else None
    if start is None:                       # no timestamps in file -> use mtime
        start = end = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    first_user = next((t for r, t in turns if r == "user"), "")
    return {
        "id": path.stem,
        "path": path,
        "project": _project_label(path),
        "turns": turns,
        "n_lines": n_lines,
        "start": start,
        "end": end,
        "first_user": first_user,
    }


def condense(session: dict) -> str:
    """Turns -> a single 'User:/Assistant:' transcript, capped for cost."""
    blocks = []
    for role, text in session["turns"]:
        who = "User" if role == "user" else "Assistant"
        blocks.append(f"{who}: {text}")
    body = "\n\n".join(blocks)
    if len(body) > TRANSCRIPT_CHAR_CAP:
        body = body[:TRANSCRIPT_CHAR_CAP] + "\n\n[transcript truncated for length]"
    return body


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)          # rough chars-per-token heuristic


# --- Naming + skip-already-done -----------------------------------------------

def _slug(text: str, words: int = 6) -> str:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return "-".join(toks[:words]) or "session"


def digest_path(repo: Path, session: dict) -> Path:
    date = session["start"].astimezone().strftime("%Y-%m-%d")
    year = date[:4]
    name = f"{date}--{session['project']}--{_slug(session['first_user'])}.md"
    return repo / "sessions" / year / name


def done_ids(repo: Path) -> set:
    """Session ids already backfilled — each digest we write carries a machine
    marker line, so this is self-describing and survives a re-clone (no
    separate state file to lose)."""
    ids = set()
    sessions_dir = repo / "sessions"
    if not sessions_dir.is_dir():
        return ids
    for md in sessions_dir.rglob("*.md"):
        try:
            for line in md.read_text(encoding="utf-8").splitlines():
                m = re.match(r"<!-- session-id: (\S+) -->", line)
                if m:
                    ids.add(m.group(1))
                    break
        except OSError:
            continue
    return ids


# --- The digest call (single seam, so tests can fake the network) -------------

class BackfillError(Exception):
    pass


def _call_api(system: str, transcript: str, model: str) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise BackfillError("ANTHROPIC_API_KEY is not set (needed for a real run)")
    body = json.dumps({
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": transcript}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text").strip()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 529) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            detail = e.read().decode("utf-8", "replace")[:300] if e.fp else str(e)
            raise BackfillError(f"API error {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise BackfillError(f"network error: {e}")
    raise BackfillError("exhausted retries")


def build_digest(session: dict, model: str) -> str:
    transcript = condense(session)
    date = session["start"].astimezone().strftime("%Y-%m-%d")
    header = (f"Session date: {date}\nProject: {session['project']}\n"
              f"(This is a Claude Code session transcript, tool output stripped.)\n\n")
    text = _call_api(SYSTEM, header + transcript, model)
    if not text:
        raise BackfillError("model returned an empty digest")
    # Machine marker (skip-detection) + provenance, appended to the model's prose.
    return (text.rstrip() + "\n\n---\n"
            f"<!-- session-id: {session['id']} -->\n"
            f"*Backfilled from a Claude Code session ({date}) by brain_backfill.py.*\n")


# --- Git (write into the local 2ndbrain clone) --------------------------------

def _git(args: list, repo: Path) -> str:
    proc = subprocess.run(["git"] + args, cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BackfillError(f"git {args[0]} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def commit(repo: Path, n: int) -> None:
    _git(["add", "sessions"], repo)
    if not _git(["status", "--porcelain"], repo).strip():
        return
    _git(["commit", "-m", f"backfill: {n} Claude Code session digest(s)"], repo)


# --- Orchestration ------------------------------------------------------------

def select(sessions: list, args) -> list:
    out = []
    since = _parse_ts(args.since + "T00:00:00+00:00") if args.since else None
    for s in sessions:
        if len([1 for r, _ in s["turns"] if r == "user"]) < args.min_turns and \
                len(s["turns"]) < args.min_turns:
            continue
        if since and s["end"] and s["end"] < since:
            continue
        if args.project and args.project.lower() not in s["project"].lower():
            continue
        out.append(s)
    out.sort(key=lambda s: s["start"])          # oldest first, chronological
    if args.limit:
        out = out[: args.limit]
    return out


def cost_line(sessions: list, model: str) -> str:
    in_tok = sum(estimate_tokens(condense(s)) for s in sessions)
    out_tok = len(sessions) * MAX_TOKENS
    pin, pout = PRICES.get(model, PRICES["claude-sonnet-5"])
    est = in_tok / 1e6 * pin + out_tok / 1e6 * pout
    return (f"~{in_tok:,} input + ~{out_tok:,} output tokens on {model} "
            f"=> roughly ${est:.2f} (estimate)")


def print_table(sessions: list) -> None:
    if not sessions:
        print("No local Claude Code session transcripts found under",
              f"{PROJECTS_DIR}.\nIf your sessions run in the Claude desktop app,",
              "they may execute in the cloud and leave nothing on this Mac —",
              "in which case there's nothing to backfill from here.")
        return
    print(f"{len(sessions)} session(s):\n")
    for s in sessions:
        date = s["start"].astimezone().strftime("%Y-%m-%d")
        prose = len(s["turns"])
        first = " ".join(s["first_user"].split())[:60]
        print(f"  {date}  {s['project']:<16}  {prose:>3} turns  {s['id'][:8]}  {first}")


def run(args) -> int:
    files = iter_session_files(Path(args.projects_dir))
    parsed = [parse_session(f) for f in files]
    selected = select(parsed, args)

    if args.list:
        print_table(selected)
        return 0

    repo = Path(args.repo).expanduser()
    if not (repo / ".git").is_dir():
        raise BackfillError(
            f"no git clone of 2ndbrain at {repo}. Clone it first:\n"
            "  git clone https://github.com/instatank/2ndbrain.git ~/2ndbrain\n"
            "or pass --repo /path/to/your/clone")
    _git(["pull", "--ff-only"], repo)          # start from latest, avoid conflicts
    done = done_ids(repo)
    todo = [s for s in selected if s["id"] not in done]
    skipped = len(selected) - len(todo)

    print(f"{len(selected)} session(s) selected; {skipped} already in the brain; "
          f"{len(todo)} to backfill.")
    if not todo:
        print("Nothing to do.")
        return 0
    print(cost_line(todo, args.model))

    if args.dry_run:
        print("\n(dry run — nothing written) Would write:")
        for s in todo:
            print(f"  {digest_path(repo, s).relative_to(repo)}")
        return 0

    if not args.yes:
        try:
            if input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        except EOFError:
            print("Non-interactive; pass --yes to proceed.")
            return 1

    written, failed = 0, []
    for i, s in enumerate(todo, 1):
        date = s["start"].astimezone().strftime("%Y-%m-%d")
        print(f"[{i}/{len(todo)}] {date} {s['project']} {s['id'][:8]} …", flush=True)
        try:
            digest = build_digest(s, args.model)
        except BackfillError as e:
            print(f"    FAILED: {e}")
            failed.append(s["id"])
            continue
        path = digest_path(repo, s)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(digest, encoding="utf-8")
        written += 1

    if written:
        commit(repo, written)
        print(f"\nWrote + committed {written} digest(s) to {repo}.")
        if args.push:
            _git(["push", "origin", "main"], repo)
            print("Pushed to origin/main.")
        else:
            print("Review with `git -C", str(repo), "log -1 --stat`, then "
                  "`git -C", str(repo), "push origin main` (or re-run with --push).")
    if failed:
        print(f"{len(failed)} session(s) failed — re-run to retry them "
              "(already-written ones are skipped).")
    return 1 if failed and not written else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list local sessions and exit")
    ap.add_argument("--dry-run", action="store_true", help="show plan + cost, write nothing")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="local 2ndbrain clone (default ~/2ndbrain)")
    ap.add_argument("--projects-dir", default=str(PROJECTS_DIR),
                    help="Claude Code projects dir (default ~/.claude/projects)")
    ap.add_argument("--since", help="only sessions on/after this date (YYYY-MM-DD)")
    ap.add_argument("--project", help="only sessions whose project name contains this")
    ap.add_argument("--limit", type=int, help="cap how many sessions to process")
    ap.add_argument("--min-turns", type=int, default=MIN_TURNS,
                    help=f"skip sessions with fewer prose turns (default {MIN_TURNS})")
    ap.add_argument("--model", default=MODEL, help=f"model (default {MODEL})")
    ap.add_argument("--push", action="store_true", help="git push after committing")
    ap.add_argument("--yes", action="store_true", help="don't prompt before running")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except BackfillError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
