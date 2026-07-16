"""Sync DayOS (his time-tracker) from Firestore into the agent's memory bank.

Run it directly (`python dayos_sync.py`) or let the systemd timer call it.
Two modes:
  --recent  pull only the last DAYOS_RECENT_DAYS days of the big collections
            (cheap; the timer default)
  --full    re-pull everything, replacing the local mirror (catches edits to
            old entries and hard-deletes; auto-promoted when the last full
            sync is >22h old, so it runs about once a day on its own)

Everything lands under memory/dayos/: raw/*.json is the exact Firestore
mirror; the markdown files next to it are rebuilt from raw on every run
(see dayos_digest.py). Sync state lives in memory/dayos/sync_status.json —
the bot reads it to warn loudly when data is stale or the last run failed.
"""

import argparse
import json
import os
import sys
import time
from datetime import timedelta

import dayos_digest
import dayos_store
import memory
from dayos_client import DayosConfigError, FirestoreClient

RECENT_DAYS = int(os.environ.get("DAYOS_RECENT_DAYS", "14"))
FULL_EVERY_HOURS = 22

# Collections filterable by a date-ish field for the recent window.
DATE_FIELD = {
    "blocks": "date",            # 'YYYY-MM-DD'
    "captures": "timestamp",     # IST ISO — string compare vs a date works
    "dailyJournal": "date",
    "sessions": "date",
    "learning": "date",
}
# Collections whose doc ID is the date (filter on __name__).
DATE_ID = ("ratings", "life_ratings", "eod", "dfts")
# Small collections — always pulled in full.
ALWAYS_FULL = ("weeklyReviews", "monthlyReviews")

ALL_COLLECTIONS = list(DATE_FIELD) + list(DATE_ID) + list(ALWAYS_FULL)


def _log(msg: str) -> None:
    print(f"[dayos-sync] {msg}", flush=True)


def load_raw() -> dict:
    raw = {}
    if dayos_store.RAW_DIR.exists():
        for p in dayos_store.RAW_DIR.glob("*.json"):
            try:
                raw[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _log(f"WARNING: could not read {p} — will re-pull that collection in full")
    return raw


def _write_if_changed(path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def persist(raw: dict) -> dict:
    """Write raw JSON + rebuild every digest from it. Prunes digest files whose
    source data disappeared. Returns counts for the status file."""
    for coll, docs in raw.items():
        _write_if_changed(
            dayos_store.RAW_DIR / f"{coll}.json",
            json.dumps(docs, ensure_ascii=False, indent=1, sort_keys=True),
        )
    files = dayos_digest.build_all(raw, today=memory.now().strftime("%Y-%m-%d"))
    changed = sum(_write_if_changed(dayos_store.DAYOS_DIR / rel, content)
                  for rel, content in files.items())
    # prune digests for data that no longer exists (e.g. hard-deleted entries)
    for sub in ("days", "weeks", "months", "projects", "tags"):
        d = dayos_store.DAYOS_DIR / sub
        if d.exists():
            for p in d.glob("*.md"):
                if f"{sub}/{p.name}" not in files:
                    p.unlink()
    counts = {coll: len(docs) for coll, docs in raw.items() if coll != "meta"}
    counts["digest_files"] = len(files)
    counts["digest_files_changed"] = changed
    return counts


def pull(client: FirestoreClient, uid: str, mode: str, existing: dict) -> dict:
    parent = f"users/{uid}"
    raw = {k: dict(v) for k, v in existing.items()} if mode == "recent" else {}
    cutoff = (memory.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")

    for coll, field in DATE_FIELD.items():
        if mode == "recent":
            docs = client.query_collection(
                parent, coll, field, "GREATER_THAN_OR_EQUAL", {"stringValue": cutoff})
            raw.setdefault(coll, {}).update(docs)
        else:
            raw[coll] = client.list_collection(parent, coll)
        _log(f"{coll}: {len(raw[coll])} docs")

    for coll in DATE_ID:
        if mode == "recent":
            try:
                docs = client.query_by_doc_id(parent, coll, cutoff)
            except RuntimeError as e:
                _log(f"WARNING: doc-id window query failed for {coll} ({e}); pulling in full")
                docs = client.list_collection(parent, coll)
            raw.setdefault(coll, {}).update(docs)
        else:
            raw[coll] = client.list_collection(parent, coll)
        _log(f"{coll}: {len(raw[coll])} docs")

    for coll in ALWAYS_FULL:
        raw[coll] = client.list_collection(parent, coll)
        _log(f"{coll}: {len(raw[coll])} docs")

    raw["meta"] = client.list_collection(parent, "meta")
    return raw


def sync(mode: str = "auto") -> dict:
    """Run one sync. Returns the status dict it wrote. Raises on failure
    (after recording the error), so callers/systemd see a loud red exit."""
    status = dayos_store.load_status()
    if mode == "auto":
        last_full = status.get("last_full", "")
        try:
            age_h = (memory.now() - memory.datetime.fromisoformat(last_full)).total_seconds() / 3600
        except ValueError:
            age_h = 1e9
        mode = "recent" if age_h < FULL_EVERY_HOURS else "full"

    started = time.monotonic()
    status["last_attempt"] = memory.now().isoformat()
    try:
        client = FirestoreClient.from_env()
        uid = os.environ.get("DAYOS_UID", "").strip() or status.get("uid") or client.discover_uid()
        _log(f"mode={mode} uid={uid} project={client.project_id}")
        raw = pull(client, uid, mode, load_raw() if mode == "recent" else {})
        counts = persist(raw)
        now_iso = memory.now().isoformat()
        status.update({
            "uid": uid,
            "mode": mode,
            "last_success": now_iso,
            "counts": counts,
            "duration_s": round(time.monotonic() - started, 1),
        })
        if mode == "full":
            status["last_full"] = now_iso
        status.pop("last_error", None)
        status.pop("last_error_time", None)
    except Exception as e:
        status["last_error"] = f"{type(e).__name__}: {e}"
        status["last_error_time"] = memory.now().isoformat()
        _write_status(status)
        raise
    _write_status(status)
    _log(f"done in {status['duration_s']}s — {counts}")
    return status


def _write_status(status: dict) -> None:
    dayos_store.DAYOS_DIR.mkdir(parents=True, exist_ok=True)
    dayos_store.STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def configured() -> bool:
    return bool(os.environ.get("FIREBASE_SERVICE_ACCOUNT_FILE", "").strip()
                or os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync DayOS data into agent memory")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="re-pull everything")
    g.add_argument("--recent", action="store_true",
                   help=f"pull only the last {RECENT_DAYS} days")
    g.add_argument("--status", action="store_true", help="print sync status and exit")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(dayos_store.load_status(), indent=2))
        return 0
    if not configured():
        # Pre-configuration this is expected — exit green so the systemd timer
        # doesn't flag red before he has even added the key.
        _log("not configured (set FIREBASE_SERVICE_ACCOUNT_FILE in .env) — skipping")
        return 0
    mode = "full" if args.full else "recent" if args.recent else "auto"
    try:
        sync(mode)
        return 0
    except DayosConfigError as e:
        _log(f"CONFIG ERROR: {e}")
        return 2
    except Exception as e:
        _log(f"SYNC FAILED: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
