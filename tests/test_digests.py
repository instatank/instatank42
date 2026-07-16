"""Offline tests for the weekly synthesis — no network, no real API.
Run: venv/bin/python tests/test_digests.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import budget
import memory

tmp = Path(tempfile.mkdtemp())
memory.MEMORY_DIR = tmp
budget.USAGE_DIR = tmp / "usage"

import dayos_store

dayos_store.DAYOS_DIR = tmp / "dayos"
dayos_store.STATUS_PATH = dayos_store.DAYOS_DIR / "sync_status.json"
dayos_store.RAW_DIR = dayos_store.DAYOS_DIR / "raw"

import playbook_store

playbook_store.PLAYBOOK_DIR = tmp / "playbook"
playbook_store.REPO_DIR = playbook_store.PLAYBOOK_DIR / "repo"
playbook_store.STATUS_PATH = playbook_store.PLAYBOOK_DIR / "sync_status.json"

import digests

digests.DIGESTS_DIR = tmp / "digests"
digests.STATUS_PATH = digests.DIGESTS_DIR / "status.json"

import bot

THIS_WEEK = digests.week_start_of(memory.now())
LAST_MONTH = digests.resolve_month("last")


def fake_client(reply_text="**The week in one line**\nSolid deep-work week.",
                stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=2000, output_tokens=400,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    content = [SimpleNamespace(type="text", text=reply_text)] if reply_text else []
    response = SimpleNamespace(content=content, usage=usage, stop_reason=stop_reason)
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    return SimpleNamespace(messages=Messages(), calls=calls)


def make_dayos_fixture():
    (dayos_store.DAYOS_DIR / "weeks").mkdir(parents=True, exist_ok=True)
    (dayos_store.DAYOS_DIR / "days").mkdir(parents=True, exist_ok=True)
    (dayos_store.DAYOS_DIR / "index.md").write_text("# DayOS index\n", encoding="utf-8")
    (dayos_store.DAYOS_DIR / "weeks" / f"{THIS_WEEK}.md").write_text(
        "# Week rollup\nDeep Work 12.0h\nDFT done: 5/6\n", encoding="utf-8")
    today = memory.now().strftime("%Y-%m-%d")
    (dayos_store.DAYOS_DIR / "days" / f"{today}.md").write_text(
        "# Day\n08:00 120m Deep Work — DayOS build\n", encoding="utf-8")


def test_resolve_and_load_missing():
    assert digests.resolve_week("this week") == THIS_WEEK
    assert digests.resolve_week("garbage") == ""
    assert "No synthesis written" in digests.load("this week")
    assert "Could not parse" in digests.load("garbage")
    print("ok resolve/load-missing")


def test_build_input():
    text = digests.build_input(THIS_WEEK)
    assert "Deep Work 12.0h" in text
    assert "DayOS build" in text
    assert "previous synthesis" in text
    print("ok build input")


def test_generate():
    client = fake_client()
    spend_before = budget.today_spend()
    result = digests.generate_week("", client)
    assert result["week"] == THIS_WEEK
    assert digests.path_for(THIS_WEEK).exists()
    stored = digests.load("this week")
    assert "Agent-written weekly synthesis" in stored     # the opinion label
    assert "Solid deep-work week." in stored
    assert budget.today_spend() > spend_before            # cost hit the ledger
    assert client.calls[0]["model"] == digests.MODEL
    assert client.calls[0]["thinking"] == {"type": "disabled"}  # see empty-reply test below
    status = json.loads(digests.STATUS_PATH.read_text())
    assert status["week"] == THIS_WEEK
    print("ok generate")


def test_empty_reply_raises_loud():
    # Sonnet defaults to adaptive thinking when `thinking` is omitted, which
    # can eat the whole (small) max_tokens budget and leave zero text — the
    # exact bug this reproduces: a response with no text block at all. Must
    # raise (and thus alert loudly on Telegram) rather than silently write a
    # label-only file, which is what happened before this guard existed.
    empty = fake_client(reply_text="", stop_reason="max_tokens")
    try:
        digests.generate_week("", empty)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "no synthesis text" in str(e) and "max_tokens" in str(e)

    empty_m = fake_client(reply_text="", stop_reason="max_tokens")
    try:
        digests.generate_month("2025-11", empty_m)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "no synthesis text" in str(e) and "max_tokens" in str(e)
    assert not digests.month_path("2025-11").exists()      # nothing written on failure

    # edge case: text present but nothing BEFORE the marker (would otherwise
    # write the exact "label with no content" bug the founder hit)
    marker_first = fake_client("===THEMES===\n- some theme")
    try:
        digests.generate_month("2025-10", marker_first)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "no month-synthesis text" in str(e)
    assert not digests.month_path("2025-10").exists()
    print("ok empty reply raises loud")


def test_resolve_month():
    assert digests.resolve_month("2026-06") == "2026-06"
    assert digests.resolve_month("last month") == LAST_MONTH
    assert digests.resolve_month("") == LAST_MONTH
    assert digests.resolve_month("garbage") == ""
    print("ok resolve month")


def test_generate_month():
    # a weekly synthesis inside last month + the DayOS month rollup feed the input
    wk = digests.week_start_of(
        memory.datetime.fromisoformat(LAST_MONTH + "-01") + digests.timedelta(days=10))
    digests.DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    digests.path_for(wk).write_text("wk synth: strong deep work\n", encoding="utf-8")
    (dayos_store.DAYOS_DIR / "months").mkdir(parents=True, exist_ok=True)
    (dayos_store.DAYOS_DIR / "months" / f"{LAST_MONTH}.md").write_text(
        "# Month rollup\nDeep Work 40.0h\n", encoding="utf-8")
    text = digests.build_month_input(LAST_MONTH)
    assert "Deep Work 40.0h" in text
    assert "strong deep work" in text
    assert "themes file" in text

    reply = ("**The month in one line**\nA grinding, honest month.\n"
             "===THEMES===\n"
             "- Ships in bursts (first seen 2026-06, last seen 2026-07)")
    client = fake_client(reply)
    result = digests.generate_month("last", client)
    assert result["month"] == LAST_MONTH and result["themes_updated"]
    assert client.calls[0]["max_tokens"] == digests.MAX_TOKENS_MONTH
    assert client.calls[0]["thinking"] == {"type": "disabled"}
    stored = digests.load(LAST_MONTH)
    assert "Agent-written monthly synthesis" in stored    # the opinion label
    assert "grinding, honest month" in stored
    assert "===THEMES===" not in stored                   # themes split out
    themes = digests.load("themes")
    assert "Standing themes" in themes and "Ships in bursts" in themes
    status = json.loads(digests.STATUS_PATH.read_text())
    assert status["month"] == LAST_MONTH and status["themes_updated"]

    # a malformed reply (no marker) must never destroy the standing themes file
    result = digests.generate_month("2025-12", fake_client("month text only, no marker"))
    assert not result["themes_updated"]
    assert "Ships in bursts" in digests.load("themes")
    print("ok generate month")


def test_budget_cap_blocks_generation():
    budget.add_spend(budget.DAILY_CAP_USD + 1)
    try:
        digests.generate_week("", fake_client())
        raise AssertionError("expected BudgetCapError")
    except digests.BudgetCapError:
        pass
    # reset the ledger for anything after us
    (budget.USAGE_DIR / f"{memory.now().strftime('%Y-%m')}.json").unlink()
    print("ok budget cap")


def test_bot_wiring():
    names = [t["name"] for t in bot.current_tools()]
    assert "digest" in names                              # a digest exists now
    out = bot.handle_tool("digest", {"period": "this week"})
    assert "Solid deep-work week." in out
    out = bot.handle_tool("digest", {"period": "last week"})
    assert "No synthesis written" in out
    out = bot.handle_tool("digest", {"period": LAST_MONTH})
    assert "grinding, honest month" in out
    assert "Ships in bursts" in bot.handle_tool("digest", {"period": "themes"})
    assert "No monthly synthesis" in bot.handle_tool("digest", {"period": "2025-01"})
    print("ok bot wiring")


def test_send_telegram_chunks():
    sent = []

    class FakeResp:
        def raise_for_status(self):
            pass

    import httpx
    orig = httpx.post
    httpx.post = lambda url, json, timeout: (sent.append((url, json)), FakeResp())[1]
    try:
        os.environ["TELEGRAM_BOT_TOKEN"] = "t0k"
        os.environ["TELEGRAM_ALLOWED_USER_ID"] = "42"
        digests.send_telegram("x" * 5000)                 # > 4000 → two messages
    finally:
        httpx.post = orig
    assert len(sent) == 2
    assert "t0k" in sent[0][0] and sent[0][1]["chat_id"] == "42"
    print("ok telegram chunking")


if __name__ == "__main__":
    try:
        make_dayos_fixture()
        test_resolve_and_load_missing()
        test_build_input()
        test_generate()
        test_empty_reply_raises_loud()
        test_resolve_month()
        test_generate_month()
        test_budget_cap_blocks_generation()
        test_bot_wiring()
        test_send_telegram_chunks()
        print("ALL DIGEST TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
