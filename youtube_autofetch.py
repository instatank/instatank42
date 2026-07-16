"""Silent YouTube auto-fetch from the DayOS learning log.

Founder decision (2026-07-16): logging a YouTube link in DayOS's learning
sessions page IS the tag — no Telegram confirmation, no notification on
success. This is the one deliberate exception to confirm-first ingestion,
chosen because writing a link into his own learning log is already an
explicit act of curation. Daily cadence (also his call — 2h would be
overkill): the youtube-autofetch systemd timer, plus a scan on every /sync.

What it does: scan the DayOS mirror's learning log (memory/dayos/learning.md
— the one watched location; widening it is a one-line change to WATCHED) for
YouTube links, and for any video not already in the bank, fetch + save its
transcript through the exact same pipeline as a hand-shared link.

Failure policy (Rule 4, adapted for a silent path):
- A video whose transcript fetch fails is retried on later runs, up to
  MAX_ATTEMPTS, then parked in the status file's "gave_up" list — visible in
  /sync output and --status, deliberately NOT on the ⚠️ health banner (one
  caption-less video is not bank breakage, and silent-success was the point).
  Parked videos can still be saved by sharing the link to the bot directly
  (paste-fallback buttons).
- The RUN itself crashing (unreadable files, bugs) IS bank breakage: recorded
  via record_error, so the banner warns on every reply until a run succeeds.

CLI:  python youtube_autofetch.py            one scan+fetch run
      python youtube_autofetch.py --status   what's saved/pending/parked
"""

import json
import sys

import memory
import youtube_ingest

# The watched location(s): mirror files whose YouTube links count as tags.
WATCHED = [memory.MEMORY_DIR / "dayos" / "learning.md"]

MAX_ATTEMPTS = 3


def _auto_state(status: dict) -> dict:
    return status.setdefault("autofetch", {"attempts": {}, "gave_up": {}})


def scan() -> list:
    """All YouTube (vid, url) pairs currently present in the watched files."""
    links, seen = [], set()
    for path in WATCHED:
        if not path.exists():
            continue
        for vid, url in youtube_ingest.find_links(path.read_text(encoding="utf-8")):
            if vid not in seen:
                seen.add(vid)
                links.append((vid, url))
    return links


def run() -> dict:
    """One scan+fetch pass. Returns a summary dict; raises only on a broken
    run (after recording it for the health banner)."""
    try:
        return _run()
    except Exception as e:
        youtube_ingest.record_error(f"YouTube auto-fetch run crashed: {e}")
        raise


def _update_status(mutate) -> None:
    """Load-modify-save, so bookkeeping survives ingest() rewriting the same
    file mid-run and a crash mid-loop loses at most one video's record."""
    status = youtube_ingest.load_status()
    mutate(status)
    youtube_ingest._save_status(status)


def _run() -> dict:
    status = youtube_ingest.load_status()
    auto = _auto_state(status)
    known = set(status.get("videos", {}))
    found = scan()
    new = [(v, u) for v, u in found if v not in known and v not in auto["gave_up"]]

    saved, failed, parked = [], {}, []
    for vid, _url in new:
        info = youtube_ingest.fetch(vid)
        if info["transcript"]:
            youtube_ingest.ingest(
                vid, info["title"], info["channel"], info["transcript"],
                "transcript", info["lang"],
                note="auto-saved from the DayOS learning log",
                raw=info["raw"] or "")
            saved.append(info["title"] or vid)
            _update_status(lambda s: _auto_state(s)["attempts"].pop(vid, None))
        else:
            failed[vid] = info["error"]
            n = auto["attempts"].get(vid, 0) + 1
            if n >= MAX_ATTEMPTS:
                parked.append(vid)

            def bump(s, vid=vid, n=n, err=info["error"]):
                a = _auto_state(s)
                if n >= MAX_ATTEMPTS:
                    a["gave_up"][vid] = err[:200]
                    a["attempts"].pop(vid, None)
                else:
                    a["attempts"][vid] = n
            _update_status(bump)

    def stamp(s):
        a = _auto_state(s)
        a["last_run"] = memory.now().isoformat()
        a["last_found"] = len(found)
        # a completed run = the bank machinery works: clear any crash banner
        s["last_success"] = memory.now().isoformat()
        s.pop("last_error", None)
        s.pop("last_error_time", None)
    _update_status(stamp)
    return {"found": len(found), "new": len(new), "saved": saved,
            "failed": failed, "parked": parked}


def summary_line(result: dict) -> str:
    """One human line for /sync output and the CLI."""
    if result["new"] == 0:
        return (f"YouTube auto-fetch: {result['found']} link(s) in the DayOS "
                "learning log, nothing new.")
    parts = [f"YouTube auto-fetch: {result['new']} new link(s)"]
    if result["saved"]:
        titles = ", ".join(f'"{t[:40]}"' for t in result["saved"][:5])
        parts.append(f"saved {len(result['saved'])} ({titles})")
    if result["failed"]:
        parts.append(f"{len(result['failed'])} fetch(es) failed — will retry"
                     if not result["parked"] else
                     f"{len(result['failed'])} failed")
    if result["parked"]:
        parts.append(f"{len(result['parked'])} gave up after {MAX_ATTEMPTS} tries "
                     "— share those links to the bot directly to paste a "
                     "transcript/summary")
    return "; ".join(parts) + "."


def print_status() -> None:
    status = youtube_ingest.load_status()
    auto = status.get("autofetch", {})
    print(f"watched: {', '.join(str(p) for p in WATCHED)}")
    print(f"last run: {auto.get('last_run', 'never')}"
          f" (links found then: {auto.get('last_found', '-')})")
    print(f"videos in bank: {len(status.get('videos', {}))}")
    if auto.get("attempts"):
        for vid, n in auto["attempts"].items():
            print(f"retrying: {vid} (attempt {n}/{MAX_ATTEMPTS})")
    for vid, err in auto.get("gave_up", {}).items():
        print(f"gave up: https://youtu.be/{vid} — {err}")


def main(argv: list) -> int:
    if "--status" in argv:
        print_status()
        return 0
    if not any(p.exists() for p in WATCHED):
        print("nothing to scan — no DayOS learning log mirrored yet (run a DayOS sync first)")
        return 0
    result = run()
    print(summary_line(result))
    for vid, err in result["failed"].items():
        print(f"  failed: https://youtu.be/{vid} — {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
