"""Offline tests for the playbook memory bank — no network, no GitHub.
The sync test clones from a local file:// git repo built in a temp dir.
Run: venv/bin/python tests/test_playbook.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import memory

tmp = Path(tempfile.mkdtemp())
memory.MEMORY_DIR = tmp

import playbook_store

playbook_store.PLAYBOOK_DIR = tmp / "playbook"
playbook_store.REPO_DIR = playbook_store.PLAYBOOK_DIR / "repo"
playbook_store.STATUS_PATH = playbook_store.PLAYBOOK_DIR / "sync_status.json"

import bot
import playbook_sync

SRC = tmp / "source-repo"

PLAYBOOK_MD = """# PLAYBOOK — global rules

## Rule 1 — One change at a time. No bundled fixes.

A commit contains the one thing that was asked for.

## Rule 4 — The silent-failure question.

If this goes wrong silently, how would the founder ever find out? #dft
"""

NORTH_STAR_MD = """# NORTH_STAR — the builder's path

Marketable = L3 in all four tracks, L4 in at least one.
"""


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test"] + args,
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def make_source_repo():
    (SRC / "playbook" / "templates").mkdir(parents=True)
    (SRC / "playbook" / "PLAYBOOK.md").write_text(PLAYBOOK_MD, encoding="utf-8")
    (SRC / "playbook" / "NORTH_STAR.md").write_text(NORTH_STAR_MD, encoding="utf-8")
    (SRC / "playbook" / "templates" / "BUILD_BRIEF.md").write_text(
        "# BUILD BRIEF — template\n", encoding="utf-8")
    (SRC / "LEARNINGS.md").write_text(
        "# LEARNINGS\n\n### 2026-07-02 — The /tmp test sims were gone\n", encoding="utf-8")
    _git(["init", "-q"], cwd=SRC)
    _git(["checkout", "-q", "-b", "main"], cwd=SRC)
    _git(["add", "-A"], cwd=SRC)
    _git(["commit", "-q", "-m", "playbook v1"], cwd=SRC)


def test_unconfigured():
    os.environ.pop("PLAYBOOK_REPO_URL", None)
    assert not playbook_sync.configured()
    assert "No playbook synced yet" in playbook_store.search("anything")
    # sync() must record the failure loudly, then raise
    try:
        playbook_sync.sync()
        raise AssertionError("expected PlaybookConfigError")
    except playbook_sync.PlaybookConfigError:
        pass
    assert "last_error" in playbook_store.load_status()
    playbook_store.STATUS_PATH.unlink()
    print("ok unconfigured")


def test_sync_clone():
    os.environ["PLAYBOOK_REPO_URL"] = f"file://{SRC}"
    assert playbook_sync.configured()
    status = playbook_sync.sync()
    assert playbook_store.has_data()
    assert status["files"] == 4 and status["commit"]
    # the on-disk remote never holds a token-bearing URL
    remotes = subprocess.run(["git", "remote", "-v"], cwd=playbook_store.REPO_DIR,
                             capture_output=True, text=True).stdout
    assert "x-access-token" not in remotes
    print("ok sync clone")


def test_sync_update():
    (SRC / "playbook" / "PLAYBOOK.md").write_text(
        PLAYBOOK_MD + "\n## Rule 7 — Ask before anything irreversible.\n", encoding="utf-8")
    _git(["commit", "-qam", "playbook v2"], cwd=SRC)
    playbook_sync.sync()
    assert "irreversible" in playbook_store.search("irreversible")
    print("ok sync update")


def test_store_reads():
    # whole-doc reads with forgiving names
    for name in ("playbook", "PLAYBOOK.md", "play book"):
        assert "One change at a time" in playbook_store.doc(name), name
    assert "builder's path" in playbook_store.doc("north star")
    assert "template" in playbook_store.doc("build brief")
    assert "/tmp test sims" in playbook_store.doc("learnings")
    assert "Available:" in playbook_store.doc("bogus-doc")
    # search: multi-term AND (order-independent) + exact-tag mode
    assert "goes wrong silently" in playbook_store.search("silently founder")
    assert "goes wrong silently" in playbook_store.search("#dft")
    assert "No matches" in playbook_store.search("zebra unicorn")
    print("ok store reads")


def test_staleness():
    fresh = memory.now().isoformat()
    old = (memory.now() - timedelta(days=3)).isoformat()
    playbook_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    assert playbook_store.staleness_note() == ""
    playbook_store.STATUS_PATH.write_text(json.dumps({"last_success": old}))
    note = playbook_store.staleness_note()
    assert "WARNING" in note and "stale" in note
    assert playbook_store.doc("playbook").startswith("WARNING")
    playbook_store.STATUS_PATH.write_text(json.dumps({
        "last_success": fresh, "last_error": "boom",
        "last_error_time": (memory.now() + timedelta(minutes=1)).isoformat(),
    }))
    assert "FAILED" in playbook_store.staleness_note()
    playbook_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    print("ok staleness")


def test_bot_wiring():
    names = [t["name"] for t in bot.current_tools()]
    assert "search_playbook" in names and "playbook_doc" in names
    assert "One change at a time" in bot.handle_tool("playbook_doc", {"name": "playbook"})
    assert "goes wrong silently" in bot.handle_tool("search_playbook", {"query": "silently founder"})
    note = playbook_store.prompt_note()
    assert "search_playbook" in note and len(note) <= 700
    print("ok bot wiring")


if __name__ == "__main__":
    try:
        make_source_repo()
        test_unconfigured()
        test_sync_clone()
        test_sync_update()
        test_store_reads()
        test_staleness()
        test_bot_wiring()
        print("ALL PLAYBOOK TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
