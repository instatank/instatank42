"""Offline tests for the Wispr Flow exporter — builds a synthetic SQLite
fixture (Wispr Flow's real schema is unknown until run against the real app;
these tests validate the schema-adaptive logic itself, not real data).
Run: venv/bin/python tests/test_wispr_export.py
"""

import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wispr_export as we

tmp = Path(tempfile.mkdtemp())
we.EXPORT_DIR = tmp / "export"
we.STATE_PATH = we.EXPORT_DIR / ".last_export.json"
we.MAP_PATH = we.EXPORT_DIR / ".schema_map.json"
we.JSON_PATH = we.EXPORT_DIR / "full-history.json"
we.MD_PATH = we.EXPORT_DIR / "full-history.md"


def make_db(path: Path, rows):
    """Deliberately non-obvious column names, so passing proves the keyword
    heuristics (not a hardcoded guess) found the right table/columns. Plus a
    decoy table with no text-like columns, to prove it's not just picking
    the first table."""
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE DictationEntry (
        id INTEGER PRIMARY KEY,
        rawText TEXT,
        formattedText TEXT,
        sourceApp TEXT,
        createdAt TEXT,
        wordCount INTEGER,
        durationSeconds REAL
    )""")
    conn.execute("CREATE TABLE Settings (key TEXT, value TEXT)")
    conn.execute("INSERT INTO Settings VALUES ('theme', 'dark')")
    for r in rows:
        conn.execute(
            "INSERT INTO DictationEntry (rawText, formattedText, sourceApp, createdAt, wordCount, durationSeconds) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r["raw"], r["formatted"], r["app"], r["ts"], r["words"], r["dur"]),
        )
    conn.commit()
    conn.close()


BASE = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)

INITIAL_ROWS = [
    {"raw": "hey wat time is the meeting", "formatted": "Hey, what time is the meeting?",
     "app": "Slack", "ts": (BASE).isoformat(), "words": 6, "dur": 2.1},
    {"raw": "remind me to call mom tommorow", "formatted": "Remind me to call mom tomorrow.",
     "app": "Notes", "ts": (BASE + timedelta(hours=2)).isoformat(), "words": 6, "dur": 1.8},
    {"raw": "draft an email to the team about the deploy",
     "formatted": "Draft an email to the team about the deploy.",
     "app": "Mail", "ts": (BASE + timedelta(days=1)).isoformat(), "words": 9, "dur": 3.4},
]

NEW_ROWS = [
    {"raw": "add milk and eggs to the list", "formatted": "Add milk and eggs to the list.",
     "app": "Reminders", "ts": (BASE + timedelta(days=2)).isoformat(), "words": 7, "dur": 2.0},
    {"raw": "book a table for two on friday", "formatted": "Book a table for two on Friday.",
     "app": "OpenTable", "ts": (BASE + timedelta(days=2, hours=1)).isoformat(), "words": 8, "dur": 2.5},
]


def test_locate_finds_app_support_candidate():
    fake_support = tmp / "Library" / "Application Support"
    wispr_dir = fake_support / "WisprFlow"
    wispr_dir.mkdir(parents=True)
    db_path = wispr_dir / "dictation.sqlite"
    make_db(db_path, INITIAL_ROWS[:1])
    old_app_support = we.APP_SUPPORT
    we.APP_SUPPORT = fake_support
    try:
        found = we.find_database(None)
        assert found.resolve() == db_path.resolve()
    finally:
        we.APP_SUPPORT = old_app_support
    print("ok locate finds app-support candidate")


def test_schema_inspection_and_guess():
    db_path = tmp / "wispr_test.sqlite"
    make_db(db_path, INITIAL_ROWS)
    copy_path = we.safe_copy(db_path)
    conn = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
    schema = we.inspect_schema(conn)
    assert set(schema.keys()) == {"DictationEntry", "Settings"}
    assert schema["DictationEntry"]["row_count"] == 3

    table, colmap = we.guess_table_and_map(schema)
    assert table == "DictationEntry"  # not the decoy Settings table
    assert colmap["text_formatted"] == "formattedText"
    assert colmap["text_raw"] == "rawText"
    assert colmap["timestamp"] == "createdAt"
    assert colmap["app"] == "sourceApp"
    assert colmap["word_count"] == "wordCount"
    assert colmap["duration"] == "durationSeconds"
    conn.close()
    copy_path.unlink()
    copy_path.parent.rmdir()
    print("ok schema inspection + column guess")


def test_timestamp_format_detection():
    now_unix = datetime.now(timezone.utc).timestamp()
    now_coredata = now_unix - we.COREDATA_EPOCH.timestamp()
    assert we.detect_timestamp_format(["2026-07-10T09:00:00+00:00"]) == "iso"
    assert we.detect_timestamp_format([now_unix]) == "unix_seconds"
    assert we.detect_timestamp_format([now_unix * 1000]) == "unix_millis"
    assert we.detect_timestamp_format([now_coredata]) == "coredata_seconds"
    assert we.detect_timestamp_format([1.0]) == "unknown"  # not plausibly "now" under any interpretation
    print("ok timestamp format detection")


def test_full_export_then_incremental_then_full_again():
    db_path = tmp / "wispr_run.sqlite"
    make_db(db_path, INITIAL_ROWS)

    summary1 = we.run(db_arg=str(db_path))
    assert summary1["total_entries"] == 3
    assert summary1["new_this_run"] == 3
    assert summary1["table_used"] == "DictationEntry"
    assert summary1["date_range"] == ("2026-07-10", "2026-07-11")
    entries = json.loads(we.JSON_PATH.read_text())
    assert len(entries) == 3
    assert all("_key" in e and "_exported_ts" in e for e in entries)
    assert all("_parsed_ts" not in e for e in entries)  # transient field must not leak into output
    md = we.MD_PATH.read_text()
    assert "# Wispr Flow — Full Dictation History" in md
    assert "## 2026-07-11" in md and "## 2026-07-10" in md
    # newest date first
    assert md.index("## 2026-07-11") < md.index("## 2026-07-10")
    assert "Draft an email to the team about the deploy." in md
    assert "_Mail_" in md
    assert "9 words" in md

    # append new rows to the SAME live db file, then run incrementally
    conn = sqlite3.connect(db_path)
    for r in NEW_ROWS:
        conn.execute(
            "INSERT INTO DictationEntry (rawText, formattedText, sourceApp, createdAt, wordCount, durationSeconds) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r["raw"], r["formatted"], r["app"], r["ts"], r["words"], r["dur"]),
        )
    conn.commit()
    conn.close()

    summary2 = we.run(db_arg=str(db_path))
    assert summary2["new_this_run"] == 2
    assert summary2["total_entries"] == 5
    entries = json.loads(we.JSON_PATH.read_text())
    assert len(entries) == 5
    assert len({e["_key"] for e in entries}) == 5  # no duplicate keys

    # a second incremental run with no new rows must add nothing
    summary3 = we.run(db_arg=str(db_path))
    assert summary3["new_this_run"] == 0
    assert summary3["total_entries"] == 5

    # --full must NOT duplicate existing entries (this was the actual bug:
    # stripping _wispr_rowid before storage broke cross-run dedup identity)
    summary4 = we.run(db_arg=str(db_path), full=True)
    assert summary4["total_entries"] == 5
    assert summary4["new_this_run"] == 5  # re-pulled everything from the DB
    entries = json.loads(we.JSON_PATH.read_text())
    assert len(entries) == 5
    print("ok full export, incremental append, no-op run, full re-pull dedup")


def test_inspect_only_writes_nothing():
    db_path = tmp / "wispr_inspect.sqlite"
    make_db(db_path, INITIAL_ROWS[:1])
    fresh_dir = tmp / "inspect_only_export"
    we.EXPORT_DIR, we.JSON_PATH, we.MD_PATH = fresh_dir, fresh_dir / "full-history.json", fresh_dir / "full-history.md"
    we.MAP_PATH, we.STATE_PATH = fresh_dir / ".schema_map.json", fresh_dir / ".last_export.json"
    result = we.run(db_arg=str(db_path), inspect_only=True)
    assert result == {}
    assert not we.JSON_PATH.exists()
    assert not we.MD_PATH.exists()
    assert not we.MAP_PATH.exists()
    print("ok inspect-only writes nothing")


def test_missing_database_raises_clear_error():
    try:
        we.find_database("/nonexistent/path/nope.sqlite")
        raise AssertionError("expected DatabaseAccessError")
    except we.DatabaseAccessError as e:
        assert "does not exist" in str(e)
    print("ok missing db raises clear error")


if __name__ == "__main__":
    try:
        test_locate_finds_app_support_candidate()
        test_schema_inspection_and_guess()
        test_timestamp_format_detection()
        test_full_export_then_incremental_then_full_again()
        test_inspect_only_writes_nothing()
        test_missing_database_raises_clear_error()
        print("ALL WISPR EXPORT TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
