"""Offline tests for the YouTube memory bank + link-drop ingestion — no
network (the HTTP seam is faked), no Telegram. Run: venv/bin/python tests/test_youtube.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import memory

tmp = Path(tempfile.mkdtemp())
memory.MEMORY_DIR = tmp

import youtube_ingest
import youtube_store

for mod in (youtube_ingest, youtube_store):
    mod.YOUTUBE_DIR = tmp / "youtube"
    mod.VIDEOS_DIR = mod.YOUTUBE_DIR / "videos"
    mod.STATUS_PATH = mod.YOUTUBE_DIR / "sync_status.json"
youtube_ingest.RAW_DIR = youtube_ingest.YOUTUBE_DIR / "raw"

import bot

VID = "dQw4w9WgXcQ"

# --- fake network ----------------------------------------------------------------

CAPTION_TRACKS = [
    {"baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=de",
     "languageCode": "de", "kind": "asr"},
    {"baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=en",
     "languageCode": "en", "kind": "asr"},
]
WATCH_HTML = ('<html>..."captions":{"playerCaptionsTracklistRenderer":{'
              '"captionTracks":' + json.dumps(CAPTION_TRACKS) + ',"other":1}}...</html>')
JSON3 = json.dumps({"events": [
    {"tStartMs": 0, "segs": [{"utf8": "position sizing is"}, {"utf8": " everything"}]},
    {"tStartMs": 1000, "aAppend": 1, "segs": [{"utf8": "everything"}]},  # rolling repeat
    {"tStartMs": 5000, "wWinId": 1},  # window event, no segs
    {"tStartMs": 95000, "segs": [{"utf8": "never risk more than two percent\n"}]},
]})
OEMBED = json.dumps({"title": "Position Sizing Masterclass", "author_name": "PokerEV"})

fake_pages = {}


def fake_http_get(url):
    for key, val in fake_pages.items():
        if key in url:
            if isinstance(val, Exception):
                raise val
            return val
    raise AssertionError(f"unexpected fetch: {url}")


youtube_ingest._http_get = fake_http_get


def all_working():
    fake_pages.clear()
    fake_pages.update({"oembed": OEMBED, "/watch": WATCH_HTML, "timedtext": JSON3})


# --- tests -----------------------------------------------------------------------

def test_find_link():
    cases = {
        f"check this https://www.youtube.com/watch?v={VID} out": VID,
        f"https://youtu.be/{VID}?t=42": VID,
        f"https://m.youtube.com/watch?feature=share&v={VID}": VID,
        f"https://www.youtube.com/shorts/{VID}": VID,
        f"https://music.youtube.com/watch?v={VID}&list=x": VID,
    }
    for text, vid in cases.items():
        found = youtube_ingest.find_link(text)
        assert found and found[0] == vid, text
    assert youtube_ingest.find_link("no links here") is None
    assert youtube_ingest.find_link("https://vimeo.com/12345") is None
    # the note = message text minus the link
    vid, url = youtube_ingest.find_link(f"great sizing vid https://youtu.be/{VID}")
    assert youtube_ingest.note_from(f"great sizing vid https://youtu.be/{VID}", url) \
        == "great sizing vid"
    print("ok find link")


def test_fetch_success():
    all_working()
    info = youtube_ingest.fetch(VID)
    assert info["title"] == "Position Sizing Masterclass"
    assert info["channel"] == "PokerEV"
    assert info["lang"] == "en, auto-generated"  # en preferred over de
    # timestamps every ~minute; rolling repeats and window events skipped
    assert info["transcript"].startswith("[0:00:00] position sizing is everything")
    assert "[0:01:35] never risk more than two percent" in info["transcript"]
    assert info["transcript"].count("everything") == 1
    assert info["error"] == ""
    print("ok fetch success")


def test_fetch_degrades():
    # no captions on the page
    all_working()
    fake_pages["/watch"] = "<html>no captions key here</html>"
    info = youtube_ingest.fetch(VID)
    assert info["transcript"] is None and "no captions" in info["error"]
    assert info["title"] == "Position Sizing Masterclass"  # metadata still fetched
    # bot check page
    fake_pages["/watch"] = "<html>redirect consent.youtube.com</html>"
    assert "bot check" in youtube_ingest.fetch(VID)["error"]
    # network completely down: title degrades too, error still explains
    fake_pages.clear()
    fake_pages.update({"oembed": OSError("boom"), "/watch": OSError("boom")})
    info = youtube_ingest.fetch(VID)
    assert info["transcript"] is None and info["title"] == "" and info["error"]
    print("ok fetch degrades")


def test_ingest_writes_bank():
    all_working()
    info = youtube_ingest.fetch(VID)
    out = youtube_ingest.ingest(VID, info["title"], info["channel"],
                                info["transcript"], "transcript", info["lang"],
                                note="great sizing vid", raw=info["raw"])
    assert "Position Sizing Masterclass" in out and "transcript" in out
    md = (youtube_ingest.VIDEOS_DIR / f"{VID}.md").read_text(encoding="utf-8")
    assert md.startswith("# Position Sizing Masterclass")
    assert f"https://youtu.be/{VID}" in md
    assert "User's note when saving: great sizing vid" in md
    assert "## Transcript" in md and "two percent" in md
    # raw payload kept (bank contract: markdown is rebuildable)
    assert (youtube_ingest.RAW_DIR / f"{VID}.json").exists()
    status = youtube_ingest.load_status()
    assert status["videos"][VID]["source"] == "transcript"
    print("ok ingest writes bank")


def test_summary_fallback_and_replace():
    # same video re-saved as a summary must REPLACE the transcript entry
    youtube_ingest.ingest(VID, "Position Sizing Masterclass", "PokerEV",
                          "Key idea: risk max 2% per trade.", "summary")
    md = (youtube_ingest.VIDEOS_DIR / f"{VID}.md").read_text(encoding="utf-8")
    assert "## Summary" in md and "manual summary" in md and "## Transcript" not in md
    assert youtube_ingest.load_status()["videos"][VID]["source"] == "summary"
    # empty body refuses to save
    try:
        youtube_ingest.ingest("x" * 11, "t", "c", "   ", "summary")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    # restore the transcript entry for the store tests
    all_working()
    info = youtube_ingest.fetch(VID)
    youtube_ingest.ingest(VID, info["title"], info["channel"], info["transcript"],
                          "transcript", info["lang"], raw=info["raw"])
    print("ok summary fallback + replace")


def test_store_reads():
    assert youtube_store.has_data()
    # by title words, forgiving case; by id; miss lists what's saved
    assert "two percent" in youtube_store.video("position sizing")
    assert "PokerEV" in youtube_store.video(VID)
    assert "No saved video matching" in youtube_store.video("cooking pasta")
    print("ok store reads")


def test_store_search():
    youtube_ingest.ingest("abcdefghijk", "Meditation Basics", "CalmChannel",
                          "Sit still. Breathe. #focus", "summary")
    out = youtube_store.search("risk two percent")
    assert "[Position Sizing Masterclass]" in out and "two percent" in out
    assert "Meditation" not in out
    assert "#focus" in youtube_store.search("#focus")
    assert "No matches" in youtube_store.search("#foc")  # exact tag only
    assert "No matches" in youtube_store.search("zebra unicorn")
    print("ok store search")


def test_staleness_and_banner():
    assert youtube_store.staleness_note() == ""
    youtube_ingest.record_error("save exploded")
    assert "FAILED" in youtube_store.staleness_note()
    assert "save exploded" in bot.health_banner()
    # a later successful save clears it
    youtube_ingest.ingest("abcdefghijk", "Meditation Basics", "CalmChannel",
                          "Sit still. Breathe. #focus", "summary")
    assert youtube_store.staleness_note() == ""
    print("ok staleness + banner")


def test_bot_wiring():
    names = [t.get("name") for t in bot.current_tools()]
    assert "search_youtube" in names and "youtube_video" in names
    assert "two percent" in bot.handle_tool("search_youtube", {"query": "two percent"})
    assert "PokerEV" in bot.handle_tool("youtube_video", {"name": "position sizing"})
    note = youtube_store.prompt_note()
    assert "search_youtube" in note and "manual summary" in note and len(note) <= 700
    # bank absent -> tools disappear (gated on data, not env)
    shutil.rmtree(youtube_store.VIDEOS_DIR)
    assert "search_youtube" not in [t.get("name") for t in bot.current_tools()]
    assert youtube_store.prompt_note() == ""
    print("ok bot wiring")


if __name__ == "__main__":
    try:
        test_find_link()
        test_fetch_success()
        test_fetch_degrades()
        test_ingest_writes_bank()
        test_summary_fallback_and_replace()
        test_store_reads()
        test_store_search()
        test_staleness_and_banner()
        test_bot_wiring()
        print("ALL YOUTUBE TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
