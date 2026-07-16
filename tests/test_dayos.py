"""Offline tests for the DayOS memory bank — no network, no Firebase.
Run: venv/bin/python tests/test_dayos.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import memory

tmp = Path(tempfile.mkdtemp())
memory.MEMORY_DIR = tmp
memory.PROFILE_PATH = tmp / "profile.md"
memory.SESSIONS_DIR = tmp / "sessions"

import dayos_store

dayos_store.DAYOS_DIR = tmp / "dayos"
dayos_store.STATUS_PATH = dayos_store.DAYOS_DIR / "sync_status.json"
dayos_store.RAW_DIR = dayos_store.DAYOS_DIR / "raw"

import bot
import dayos_digest
import dayos_sync
from dayos_client import decode_fields, decode_value

# 2026-07-01 was a Wednesday; its DayOS week (Sunday-start) begins 2026-06-28.
D1, D2, WEEK, MONTH = "2026-07-01", "2026-07-02", "2026-06-28", "2026-07"
D0 = "2026-06-01"  # a month earlier — exercises the open-loops age buckets


def fixture_raw() -> dict:
    return {
        "blocks": {
            "b1": {"id": "b1", "date": D1, "start_time": "08:00", "duration_min": 120,
                   "category": "deep_work", "label": "DayOS build", "note": "shipped the sync fix",
                   "projectTag": "dayos", "tags": ["#dayos"], "energy_level": 4, "_synced": True},
            "b2": {"id": "b2", "date": D1, "start_time": "06:30", "duration_min": 60,
                   "category": "routine", "label": "Morning walk"},
            "b3": {"id": "b3", "date": D1, "start_time": "20:00", "duration_min": 90,
                   "category": "leisure", "label": "SECRET DELETED BLOCK",
                   "deletedAt": "2026-07-01T21:00:00+05:30"},
            "b4": {"id": "b4", "date": D2, "start_time": "09:00", "duration_min": 60,
                   "category": "learning", "label": "Reading"},
        },
        "captures": {
            "c1": {"id": "c1", "timestamp": f"{D1}T10:32:00+05:30", "type": "note",
                   "body": "Closed the deal #win", "tags": ["#win"]},
            "c2": {"id": "c2", "timestamp": f"{D1}T14:05:00+05:30", "type": "project",
                   "body": "API idea for DayOS", "project_tag": "DayOS", "tags": ["#dayos"]},
            "c3": {"id": "c3", "timestamp": f"{D2}T09:15:00+05:30", "type": "note",
                   "body": "Long streak continues #winner", "tags": ["#winner"]},
            "c4": {"id": "c4", "timestamp": f"{D1}T23:00:00+05:30", "type": "note",
                   "body": "trashed note", "deletedAt": "2026-07-02T08:00:00+05:30"},
            # five #idea uses -> earns an auto tag view; i5 also pushes #dayos
            # to five uses, which must STILL not get a view (project tag)
            "i1": {"id": "i1", "timestamp": f"{D0}T10:00:00+05:30", "type": "note",
                   "body": "Automate journal imports", "tags": ["#idea"]},
            "i2": {"id": "i2", "timestamp": f"{D0}T11:00:00+05:30", "type": "note",
                   "body": "Morning-brief bot", "tags": ["#idea"]},
            "i3": {"id": "i3", "timestamp": f"{D0}T12:00:00+05:30", "type": "note",
                   "body": "Weekly metrics email", "tags": ["#idea"]},
            "i4": {"id": "i4", "timestamp": f"{D0}T13:00:00+05:30", "type": "note",
                   "body": "Voice-first capture", "tags": ["#idea"]},
            "i5": {"id": "i5", "timestamp": f"{D0}T14:00:00+05:30", "type": "note",
                   "body": "Tag heatmap view", "tags": ["#idea", "#dayos"]},
        },
        "dailyJournal": {
            D1: {"id": D1, "date": D1, "thoughts": "Good energy today.",
                 "reflection": "Focus held through the morning.",
                 "tasks": [{"id": "t1", "text": "Ship sync", "completed": True},
                           {"id": "t2", "text": "Call bank", "completed": False}],
                 "tags": ["#win"],
                 "voiceNotes": [{"id": "v1", "title": "morning ramble", "durationSec": 32}]},
            D0: {"id": D0, "date": D0, "thoughts": "Planning month.",
                 "tasks": [{"id": "t3", "text": "Renew lease", "completed": False}]},
        },
        "sessions": {
            "s1": {"id": "s1", "projectName": "DayOS", "date": D1, "durationMin": 90,
                   "before": "Plan the sync module", "during": "Wrote the client",
                   "after": "It works", "done": ["client"], "pending": ["digests"],
                   "learned": ["REST beats grpc here"], "tags": ["#dayos"]},
            # an OLDER session whose pending list is superseded by s1's
            "s0": {"id": "s0", "projectName": "DayOS", "date": "2026-06-20",
                   "pending": ["stale pending item"]},
        },
        "learning": {
            "l1": {"id": "l1", "sourceName": "Deep Work", "sourceType": "book",
                   "takeaway": "Schedule every minute", "fullNotes": "Cal Newport on focus blocks",
                   "tags": ["#dayos"], "date": D1, "createdAt": f"{D1}T18:00:00+05:30"},
        },
        "ratings": {D1: {"rating": 4}},
        "life_ratings": {D1: {"habit_stacking": 4, "mindset": 3}},
        "eod": {D1: {"text": "Solid day overall."}},
        "dfts": {D1: {"text": "Ship the sync module", "status": "done"},
                 D0: {"text": "File taxes", "status": "pending"}},
        "weeklyReviews": {WEEK: {"weekStart": WEEK, "intention": "Focus on DayOS",
                                 "aiSummary": "A strong, focused week."}},
        "monthlyReviews": {MONTH: {"month": MONTH, "oneFocus": "Deep work volume"}},
        "meta": {
            "projects": {"list": ["DayOS"]},
            "lifecheck": {"metrics": [
                {"id": "habit_stacking", "label": "Habit Stacking", "enabled": True},
                {"id": "mindset", "label": "Mindset", "enabled": True},
            ]},
        },
    }


def test_decode():
    fields = {
        "date": {"stringValue": "2026-07-01"},
        "duration_min": {"integerValue": "120"},
        "rating": {"doubleValue": 4.0},
        "done": {"booleanValue": True},
        "gone": {"nullValue": None},
        "tags": {"arrayValue": {"values": [{"stringValue": "#win"}]}},
        "nested": {"mapValue": {"fields": {"a": {"integerValue": "1"}}}},
    }
    out = decode_fields(fields)
    assert out == {"date": "2026-07-01", "duration_min": 120, "rating": 4.0,
                   "done": True, "gone": None, "tags": ["#win"], "nested": {"a": 1}}
    print("ok decode")


def test_digest_build():
    files = dayos_digest.build_all(fixture_raw())
    day = files[f"days/{D1}.md"]
    assert "08:00 120m Deep Work — DayOS build [#dayos] (energy 4)" in day
    assert "shipped the sync fix" in day
    assert "SECRET DELETED BLOCK" not in day          # soft-deleted → excluded
    assert "Logged 3.0h" in day                        # 120 + 60, trashed excluded
    assert 'DFT: "Ship the sync module" — done' in day
    assert "Habit Stacking 4" in day                   # metric label from meta/lifecheck
    assert "[x] Ship sync" in day and "[ ] Call bank" in day
    assert 'voice: "morning ramble" (32s)' in day
    assert "Solid day overall." in day

    week = files[f"weeks/{WEEK}.md"]
    assert "Deep Work 2.0" in week
    assert "DFT done: 1/1" in week
    assert "Wins (#win): 2" in week                    # capture + journal both tagged
    assert "A strong, focused week." in week
    assert "intention: Focus on DayOS" in week

    month = files[f"months/{MONTH}.md"]
    assert "oneFocus: Deep work volume" in month

    proj = files["projects/dayos.md"]
    assert "Plan the sync module" in proj
    assert "API idea for DayOS" in proj
    assert "Deep Work" in proj                         # tagged learning entry
    assert "2.0h logged" in proj

    assert "Schedule every minute" in files["learning.md"]
    assert "dayos" in files["index.md"]
    print("ok digest build")


def test_lenses_build():
    files = dayos_digest.build_all(fixture_raw(), today="2026-07-16")

    # tag views: full entries, newest first; specials always exist (even empty)
    win = files["tags/win.md"]
    assert "2 entries" in win
    assert "Closed the deal" in win                    # tagged capture, in full
    assert "Thoughts: Good energy today." in win       # tagged journal, in full
    idea = files["tags/idea.md"]
    assert "5 entries" in idea and "Tag heatmap view" in idea
    assert files["tags/insight.md"].startswith("# #insight — no entries yet")
    assert "tags/1%.md" in files and "tags/dft.md" in files
    assert "tags/dayos.md" not in files                # project tag: projects/ covers it
    assert "tags/winner.md" not in files               # 1 use < threshold, not special

    # open loops: bucketed by age, oldest first; done/superseded excluded
    loops = files["open-loops.md"]
    assert "Older than 30 days" in loops and "Renew lease" in loops
    assert "Last 30 days" in loops and "Call bank" in loops
    assert "digests" in loops                          # latest session's pending
    assert "stale pending item" not in loops           # older session superseded
    assert "Ship sync" not in loops                    # completed task
    assert "File taxes" not in loops                   # old pending DFT != today's
    assert loops.index("Renew lease") < loops.index("Call bank")  # oldest stares first

    # today's pending DFT IS a loop when today matches
    loops_d0 = dayos_digest.build_all(fixture_raw(), today=D0)["open-loops.md"]
    assert "today's focus task: File taxes" in loops_d0

    # metrics.csv: header + exact per-day rows (hours, rating, metrics, dft, wins)
    metrics = files["metrics.csv"]
    lines = metrics.splitlines()
    assert lines[0] == ("date,deep_work_h,learning_h,practice_h,routine_h,"
                        "leisure_h,leaks_h,total_h,rating,habit_stacking,"
                        "mindset,dft_status,wins")
    assert "2026-07-01,2.00,0.00,0.00,1.00,0.00,0.00,3.00,4,4,3,done,2" in lines
    assert "2026-07-02,0.00,1.00,0.00,0.00,0.00,0.00,1.00,,,,,0" in lines
    assert lines[1].startswith(D0)                     # rows ascending
    print("ok lenses build")


def test_persist_and_store():
    raw = fixture_raw()
    dayos_sync.persist(raw)
    assert dayos_store.has_data()
    # a data dir with no sync record warns loudly on every read
    assert "freshness unknown" in dayos_store.day(D1)
    dayos_store.DAYOS_DIR.mkdir(parents=True, exist_ok=True)
    dayos_store.STATUS_PATH.write_text(json.dumps({"last_success": memory.now().isoformat()}))

    day = dayos_store.day(D1)
    assert "Ship the sync module" in day
    assert dayos_store.day("2026-01-01").startswith("No DayOS entries")
    assert "Could not parse" in dayos_store.day("garbage")

    # period: explicit month, and a date snapping to its week
    assert "Deep work volume" in dayos_store.period(MONTH)
    assert "A strong, focused week." in dayos_store.period(D1)

    # project lookup: exact, case-insensitive, #tag form
    for query in ("dayos", "DayOS", "#dayos"):
        assert "Plan the sync module" in dayos_store.project(query), query
    assert "Known projects: dayos" in dayos_store.project("nonexistent")
    print("ok persist/store")


def test_views_store():
    # (mirror already persisted + fresh status by test_persist_and_store)
    assert "Renew lease" in dayos_store.view("open loops")
    assert "Renew lease" in dayos_store.view("pending")          # forgiving names
    for q in ("#win", "win"):                                    # tag with or without '#'
        assert "Closed the deal" in dayos_store.view(q), q
    m = dayos_store.view("metrics")
    assert "deep_work_h" in m and "2026-07-01,2.00" in m
    # unknown/list -> the listing, so the model self-corrects in one round
    for q in ("list", "", "#nonexistent"):
        out = dayos_store.view(q)
        assert "open loops" in out and "#idea" in out, q

    # metrics tail-capping keeps the header and the MOST RECENT rows
    csv = (dayos_store.DAYOS_DIR / "metrics.csv").read_text(encoding="utf-8")
    lines = csv.splitlines()
    room_for_last_row_only = len(lines[0]) + 80 + len(lines[-1]) + 2
    tail = dayos_store._metrics_tail(csv, room_for_last_row_only)
    assert tail.startswith("(showing the most recent")
    assert "date,deep_work_h" in tail
    assert D2 in tail and D0 not in tail               # newest kept, oldest dropped

    # the new views are searchable, after the primary files
    labels = [label for label, _ in dayos_store._search_files()]
    assert "open-loops" in labels and "tag:win" in labels
    assert labels.index(D1) < labels.index("open-loops")
    print("ok views store")


def test_search_semantics():
    # exact-tag mode: '#win' must NOT match '#winner'
    hits = dayos_store.search("#win")
    assert "Closed the deal" in hits
    assert "streak" not in hits
    hits = dayos_store.search("#winner")
    assert "streak" in hits
    # multi-term AND, order-independent, case-insensitive
    hits = dayos_store.search("fix sync")
    assert "shipped the sync fix" in hits
    assert "No matches" in dayos_store.search("zebra unicorn")
    print("ok search")


def test_prune():
    raw = fixture_raw()
    dayos_sync.persist(raw)
    assert (dayos_store.DAYOS_DIR / "days" / f"{D2}.md").exists()
    for coll in ("blocks", "captures"):
        raw[coll] = {k: v for k, v in raw[coll].items()
                     if not (v.get("date") == D2 or str(v.get("timestamp", "")).startswith(D2))}
    dayos_sync.persist(raw)
    assert not (dayos_store.DAYOS_DIR / "days" / f"{D2}.md").exists()
    dayos_sync.persist(fixture_raw())  # restore for later tests
    print("ok prune")


def test_tag_view_prune():
    # a tag that falls below the threshold loses its view; specials never do
    raw = fixture_raw()
    dayos_sync.persist(raw)
    assert (dayos_store.DAYOS_DIR / "tags" / "idea.md").exists()
    raw["captures"] = {k: v for k, v in raw["captures"].items()
                       if "#idea" not in (v.get("tags") or [])}
    dayos_sync.persist(raw)
    assert not (dayos_store.DAYOS_DIR / "tags" / "idea.md").exists()
    assert (dayos_store.DAYOS_DIR / "tags" / "win.md").exists()
    dayos_sync.persist(fixture_raw())  # restore for later tests
    print("ok tag view prune")


def test_staleness():
    fresh = memory.now().isoformat()
    old = (memory.now() - timedelta(days=3)).isoformat()
    dayos_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    assert dayos_store.staleness_note() == ""
    dayos_store.STATUS_PATH.write_text(json.dumps({"last_success": old}))
    note = dayos_store.staleness_note()
    assert "WARNING" in note and "stale" in note
    assert dayos_store.day(D1).startswith("WARNING")   # warnings ride on tool results
    dayos_store.STATUS_PATH.write_text(json.dumps({
        "last_success": fresh, "last_error": "boom",
        "last_error_time": (memory.now() + timedelta(minutes=1)).isoformat(),
    }))
    assert "FAILED" in dayos_store.staleness_note()
    dayos_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    print("ok staleness")


def test_bot_wiring():
    assert any(t["name"] == "search_dayos" for t in bot.current_tools())
    out = bot.handle_tool("search_dayos", {"query": "#win"})
    assert "Closed the deal" in out
    out = bot.handle_tool("dayos_day", {"date": D1})
    assert "DayOS build" in out
    out = bot.handle_tool("dayos_period", {"period": MONTH})
    assert "Deep work volume" in out
    out = bot.handle_tool("dayos_project", {"name": "dayos"})
    assert "Plan the sync module" in out
    assert any(t["name"] == "dayos_view" for t in bot.current_tools())
    assert "Renew lease" in bot.handle_tool("dayos_view", {"name": "open loops"})
    assert "Closed the deal" in bot.handle_tool("dayos_view", {"name": "#win"})
    assert "Unknown tool" in bot.handle_tool("bogus", {})
    # tool errors come back as text, never exceptions
    assert "Tool error" in bot.handle_tool("remember_fact", {})  # missing arg
    snap = dayos_store.prompt_snapshot()
    assert "search_dayos" in snap and len(snap) <= 2400
    print("ok bot wiring")


def test_sync_status_written_on_error():
    # sync() without config must record the failure loudly, then raise
    for var in ("FIREBASE_SERVICE_ACCOUNT_FILE", "FIREBASE_SERVICE_ACCOUNT"):
        os.environ.pop(var, None)
    dayos_store.STATUS_PATH.unlink(missing_ok=True)
    try:
        dayos_sync.sync("recent")
        raise AssertionError("expected DayosConfigError")
    except Exception:
        pass
    status = dayos_store.load_status()
    assert "last_error" in status
    dayos_store.STATUS_PATH.unlink(missing_ok=True)
    print("ok sync error status")


if __name__ == "__main__":
    try:
        test_decode()
        test_digest_build()
        test_lenses_build()
        test_persist_and_store()
        test_views_store()
        test_search_semantics()
        test_prune()
        test_tag_view_prune()
        test_staleness()
        test_bot_wiring()
        test_sync_status_written_on_error()
        print("ALL DAYOS TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
