"""Offline tests for the WhatsApp memory bank + file-drop ingestion — no
network, no Telegram. Run: venv/bin/python tests/test_whatsapp.py
"""

import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import memory

tmp = Path(tempfile.mkdtemp())
memory.MEMORY_DIR = tmp

import whatsapp_ingest
import whatsapp_store

for mod in (whatsapp_ingest, whatsapp_store):
    mod.WHATSAPP_DIR = tmp / "whatsapp"
    mod.CHATS_DIR = mod.WHATSAPP_DIR / "chats"
    mod.STATUS_PATH = mod.WHATSAPP_DIR / "sync_status.json"

import bot
import ingest

ANDROID_EXPORT = """\
12/06/26, 9:15 pm - Messages and calls are end-to-end encrypted.
12/06/26, 9:15 pm - Rohan: Hey, did you check the staking deal?
12/06/26, 9:17 pm - Ankit: Yes. 60/40 split, we agreed markup 1.2
12/06/26, 9:18 pm - Ankit: also: he covers travel
and hotels too
13/06/26, 8:01 am - Rohan: <Media omitted>
13/06/26, 12:05 am - Rohan: midnight ping
02/07/26, 10:00 am - Rohan: New month, reviewing the #staking numbers
"""

IOS_EXPORT = """\
‎[12/06/26, 21:15:33] Priya: Dinner friday?
[12/06/26, 21:16:02] Ankit: yes 8pm works
[13/06/26, 09:00:00] ‎Priya: booked the table
"""

MONTH_FIRST_EXPORT = """\
06/13/26, 9:15 am - A: first
06/14/26, 9:15 am - B: second
06/15/26, 9:15 am - A: third
"""


def test_parse_android():
    msgs = whatsapp_ingest.parse(ANDROID_EXPORT)
    assert len(msgs) == 7
    assert msgs[0]["sender"] is None  # encryption banner = system line
    assert msgs[1]["ts"].strftime("%Y-%m-%d %H:%M") == "2026-06-12 21:15"
    # a ': ' inside the body must not eat the sender
    assert msgs[3]["sender"] == "Ankit" and msgs[3]["text"].startswith("also: he covers")
    # multi-line continuation attached to its message
    assert "and hotels too" in msgs[3]["text"]
    # 12:05 am -> 00:05, and sorting puts it before the 8am media line
    assert msgs[4]["text"] == "midnight ping"
    assert msgs[4]["ts"].hour == 0 and msgs[4]["ts"].minute == 5
    assert msgs[5]["text"] == "<Media omitted>"
    print("ok parse android")


def test_parse_ios_and_month_first():
    msgs = whatsapp_ingest.parse(IOS_EXPORT)
    assert len(msgs) == 3
    assert msgs[0]["sender"] == "Priya" and msgs[0]["ts"].hour == 21
    assert msgs[2]["text"] == "booked the table"
    # a file whose SECOND field exceeds 12 proves month-first dates
    msgs = whatsapp_ingest.parse(MONTH_FIRST_EXPORT)
    assert [m["ts"].strftime("%m-%d") for m in msgs] == ["06-13", "06-14", "06-15"]
    print("ok parse ios + month-first")


def test_chat_name():
    assert whatsapp_ingest.chat_name("WhatsApp Chat with Rohan.txt", []) == "Rohan"
    assert whatsapp_ingest.chat_name("WhatsApp Chat - Poker Group.zip", []) == "Poker Group"
    msgs = whatsapp_ingest.parse(IOS_EXPORT)
    assert whatsapp_ingest.chat_name("_chat.txt", msgs) == "Priya & Ankit"
    print("ok chat name")


def test_detect():
    parser, info = ingest.detect("WhatsApp Chat with Rohan.txt", ANDROID_EXPORT)
    assert parser is not None and parser["name"] == "whatsapp"
    assert '"Rohan"' in info["preview"] and "2026-06-12 to 2026-07-02" in info["preview"]
    parser, reason = ingest.detect("notes.txt", "just some\nrandom notes\nnothing dated")
    assert parser is None and "didn't recognize" in reason
    print("ok detect")


def test_extract_text():
    name, text = ingest.extract_text("a.txt", "plain\n".encode("utf-8"))
    assert (name, text) == ("a.txt", "plain\n")
    # iOS-style zip: anonymous _chat.txt inside -> outer name kept for detection
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("_chat.txt", IOS_EXPORT)
    name, text = ingest.extract_text("WhatsApp Chat - Priya.zip", buf.getvalue())
    assert name == "WhatsApp Chat - Priya.zip" and "Dinner friday" in text
    for name, bad in (("x.txt", b"\xff\xfe binary junk"), ("x.zip", b"not a zip")):
        try:
            ingest.extract_text(name, bad)
            raise AssertionError(f"expected ValueError for {name}")
        except ValueError:
            pass
    try:
        ingest.extract_text("big.txt", b"x" * (ingest.MAX_FILE_BYTES + 1))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "cap" in str(e)
    print("ok extract text")


def test_ingest_writes_bank():
    summary = ingest.run("whatsapp", "WhatsApp Chat with Rohan.txt", ANDROID_EXPORT)
    assert '"Rohan"' in summary and "7 messages" in summary
    chat_dir = whatsapp_ingest.CHATS_DIR / "rohan"
    files = sorted(p.name for p in chat_dir.glob("*.md"))
    assert files == ["2026-06.md", "2026-07.md"]
    june = (chat_dir / "2026-06.md").read_text(encoding="utf-8")
    assert "## 2026-06-12" in june and "[21:17] Ankit:" in june
    assert "\n  and hotels too" in june  # continuation lines indented
    status = whatsapp_ingest.load_status()
    assert status["chats"]["rohan"]["last"] == "2026-07-02"
    # raw export kept alongside (bank contract: mirrors are rebuildable)
    raw = (whatsapp_ingest.WHATSAPP_DIR / "raw" / "rohan.txt").read_text(encoding="utf-8")
    assert "staking deal" in raw
    print("ok ingest writes bank")


def test_reingest_replaces():
    # a fresh export with only July must wipe the June file (snapshot semantics)
    ingest.run("whatsapp", "WhatsApp Chat with Rohan.txt",
               "03/07/26, 10:00 am - Rohan: only message now\n" * 3)
    files = sorted(p.name for p in (whatsapp_ingest.CHATS_DIR / "rohan").glob("*.md"))
    assert files == ["2026-07.md"]
    # restore the full snapshot for the store tests
    ingest.run("whatsapp", "WhatsApp Chat with Rohan.txt", ANDROID_EXPORT)
    print("ok reingest replaces")


def test_store_reads():
    ingest.run("whatsapp", "WhatsApp Chat - Priya.zip", IOS_EXPORT)
    assert whatsapp_store.has_data()
    # default = most recent month; explicit month; forgiving name match
    assert "New month" in whatsapp_store.chat("Rohan")
    assert "staking deal" in whatsapp_store.chat("rohan", "2026-06")
    assert "Dinner friday" in whatsapp_store.chat("priya")
    assert "Months on file" in whatsapp_store.chat("Rohan", "2025-01")
    assert "Ingested chats" in whatsapp_store.chat("nobody")
    # every result names its coverage — snapshots must never pass as live data
    assert "covers to 2026-07-02" in whatsapp_store.chat("Rohan")
    print("ok store reads")


def test_store_search():
    out = whatsapp_store.search("staking deal")
    assert "[Rohan 2026-06-12]" in out and "staking deal" in out
    assert "#staking" in whatsapp_store.search("#staking")
    assert "No matches" in whatsapp_store.search("#stak")  # exact tag only
    assert "No matches" in whatsapp_store.search("zebra unicorn")
    # chat filter: Priya's chat has no staking talk
    assert "No matches" in whatsapp_store.search("staking", "priya")
    assert "Dinner" in whatsapp_store.search("dinner", "Priya")
    print("ok store search")


def test_staleness_and_banner():
    assert whatsapp_store.staleness_note() == ""
    assert bot.health_banner() == ""
    whatsapp_ingest.record_error("parser exploded")
    note = whatsapp_store.staleness_note()
    assert "FAILED" in note and "parser exploded" in note
    assert "parser exploded" in bot.health_banner()
    # a later successful ingest clears it
    ingest.run("whatsapp", "WhatsApp Chat with Rohan.txt", ANDROID_EXPORT)
    assert whatsapp_store.staleness_note() == ""
    print("ok staleness + banner")


def test_reexport_nudge():
    status = whatsapp_ingest.load_status()
    status["chats"]["rohan"]["ingested_at"] = (memory.now() - timedelta(days=60)).isoformat()
    whatsapp_ingest._save_status(status)
    assert "re-exporting" in whatsapp_store.chat("Rohan")
    ingest.run("whatsapp", "WhatsApp Chat with Rohan.txt", ANDROID_EXPORT)
    print("ok re-export nudge")


def test_ingest_failure_recorded():
    try:
        ingest.run("whatsapp", "empty.txt", "no messages here")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert "FAILED" in whatsapp_store.staleness_note()
    ingest.run("whatsapp", "WhatsApp Chat with Rohan.txt", ANDROID_EXPORT)
    print("ok failure recorded")


def test_bot_wiring():
    names = [t.get("name") for t in bot.current_tools()]
    assert "search_whatsapp" in names and "whatsapp_chat" in names
    assert "staking deal" in bot.handle_tool("search_whatsapp", {"query": "staking deal"})
    assert "Dinner friday" in bot.handle_tool("whatsapp_chat", {"name": "priya"})
    note = whatsapp_store.prompt_note()
    assert "search_whatsapp" in note and "snapshots" in note and len(note) <= 700
    # bank absent -> tools disappear (gated on data, not env)
    shutil.rmtree(whatsapp_store.CHATS_DIR)
    assert "search_whatsapp" not in [t.get("name") for t in bot.current_tools()]
    assert whatsapp_store.prompt_note() == ""
    print("ok bot wiring")


if __name__ == "__main__":
    try:
        test_parse_android()
        test_parse_ios_and_month_first()
        test_chat_name()
        test_detect()
        test_extract_text()
        test_ingest_writes_bank()
        test_reingest_replaces()
        test_store_reads()
        test_store_search()
        test_staleness_and_banner()
        test_reexport_nudge()
        test_ingest_failure_recorded()
        test_bot_wiring()
        print("ALL WHATSAPP TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
