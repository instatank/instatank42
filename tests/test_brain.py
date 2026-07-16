"""Offline tests for the brain memory bank (Claude Code session digests) —
no network, no GitHub. The sync tests clone from a local file:// git repo
built in a temp dir, shaped like instatank/2ndbrain (sessions/ lane +
memory/ backup subfolder + README).
Run: venv/bin/python tests/test_brain.py
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

import brain_store

brain_store.BRAIN_DIR = tmp / "brain"
brain_store.REPO_DIR = brain_store.BRAIN_DIR / "repo"
brain_store.STATUS_PATH = brain_store.BRAIN_DIR / "sync_status.json"

import bot
import brain_sync

SRC = tmp / "source-repo"

DIGEST_1 = """# Weekly-review sync bug hunted down

- Date: 2026-07-15 (IST)
- Project/repo(s): time-tracker

## Decisions made

- Reviews sync via the meta collection, not their own docs. #decision
"""

DIGEST_2 = """# YouTube pipeline built end to end

- Date: 2026-07-16 (IST)
- Project/repo(s): instatank42

## Decisions made

- Transcript scraping is hand-rolled stdlib, zero model calls in the pipeline.

## Open threads

- The scrape is unverified against live YouTube from the sandbox.
"""


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test"] + args,
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def make_source_repo():
    (SRC / "sessions" / "2026").mkdir(parents=True)
    (SRC / "sessions" / "2026" / "2026-07-15--time-tracker--weekly-review-sync-bug.md").write_text(
        DIGEST_1, encoding="utf-8")
    (SRC / "sessions" / "2026" / "2026-07-16--instatank42--youtube-pipeline.md").write_text(
        DIGEST_2, encoding="utf-8")
    (SRC / "README.md").write_text("# 2ndbrain\n", encoding="utf-8")
    # The repo also carries the bot's own nightly backup — must never be read.
    (SRC / "memory").mkdir()
    (SRC / "memory" / "profile.md").write_text(
        "backup-only xylophone-marker\n", encoding="utf-8")
    _git(["init", "-q"], cwd=SRC)
    _git(["checkout", "-q", "-b", "main"], cwd=SRC)
    _git(["add", "-A"], cwd=SRC)
    _git(["commit", "-q", "-m", "brain v1"], cwd=SRC)


def test_unconfigured():
    for var in ("BRAIN_REPO_URL", "BACKUP_REPO_URL"):
        os.environ.pop(var, None)
    assert not brain_sync.configured()
    assert "No session digests synced yet" in brain_store.search("anything")
    assert "No session digests synced yet" in brain_store.digest("anything")
    # sync() must record the failure loudly, then raise
    try:
        brain_sync.sync()
        raise AssertionError("expected BrainConfigError")
    except brain_sync.BrainConfigError:
        pass
    assert "last_error" in brain_store.load_status()
    brain_store.STATUS_PATH.unlink()
    print("ok unconfigured")


def test_backup_fallback_config():
    # No BRAIN_* at all — the backup repo's values must carry the bank alone.
    os.environ["BACKUP_REPO_URL"] = f"file://{SRC}"
    assert brain_sync.configured()
    status = brain_sync.sync()
    assert brain_store.has_data()
    assert status["files"] == 2 and status["commit"] and status["branch"] == "main"
    # the on-disk remote never holds a token-bearing URL
    remotes = subprocess.run(["git", "remote", "-v"], cwd=brain_store.REPO_DIR,
                             capture_output=True, text=True).stdout
    assert "x-access-token" not in remotes
    print("ok backup fallback config")


def test_brain_url_precedence():
    # An explicit BRAIN_REPO_URL must win over the backup fallback — prove it
    # by pointing it somewhere broken while the fallback stays valid.
    os.environ["BRAIN_REPO_URL"] = f"file://{tmp}/nonexistent-repo"
    try:
        brain_sync.sync()
        raise AssertionError("expected the broken BRAIN_REPO_URL to be used")
    except RuntimeError:
        pass
    os.environ.pop("BRAIN_REPO_URL")
    brain_sync.sync()  # healthy again on the fallback; clears last_error
    print("ok brain url precedence")


def test_sync_update():
    (SRC / "sessions" / "2026" / "2026-07-17--instatank42--brain-mirror.md").write_text(
        "# Brain mirror bank built\n\n- Cloned the playbook pattern onto 2ndbrain.\n",
        encoding="utf-8")
    _git(["add", "-A"], cwd=SRC)
    _git(["commit", "-qam", "brain v2"], cwd=SRC)
    status = brain_sync.sync()
    assert status["files"] == 3
    assert "playbook pattern" in brain_store.search("playbook pattern")
    print("ok sync update")


def test_store_reads():
    # newest first, labels = filename stems
    labels = [label for label, _ in brain_store.digest_files()]
    assert labels[0].startswith("2026-07-17") and labels[-1].startswith("2026-07-15")
    # whole-digest reads with forgiving names
    assert "hand-rolled stdlib" in brain_store.digest(
        "2026-07-16--instatank42--youtube-pipeline")
    assert "hand-rolled stdlib" in brain_store.digest("youtube pipeline")
    assert "meta collection" in brain_store.digest("2026-07-15 time-tracker")
    ambiguous = brain_store.digest("instatank42")
    assert "2 digests match" in ambiguous and "which one?" in ambiguous
    assert "No session digest matching" in brain_store.digest("bogus-digest")
    assert "Newest first:" in brain_store.digest("")
    # search: multi-term AND (order-independent) + exact-tag mode
    assert "meta collection" in brain_store.search("sync reviews")
    assert "meta collection" in brain_store.search("#decision")
    assert "No matches" in brain_store.search("zebra unicorn")
    # the repo's memory/ backup subfolder is never part of the bank
    assert "No matches" in brain_store.search("xylophone-marker")
    print("ok store reads")


def test_staleness():
    fresh = memory.now().isoformat()
    old = (memory.now() - timedelta(days=3)).isoformat()
    brain_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    assert brain_store.staleness_note() == ""
    brain_store.STATUS_PATH.write_text(json.dumps({"last_success": old}))
    note = brain_store.staleness_note()
    assert "WARNING" in note and "stale" in note
    assert brain_store.digest("youtube pipeline").startswith("WARNING")
    brain_store.STATUS_PATH.write_text(json.dumps({
        "last_success": fresh, "last_error": "boom",
        "last_error_time": (memory.now() + timedelta(minutes=1)).isoformat(),
    }))
    assert "FAILED" in brain_store.staleness_note()
    brain_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    print("ok staleness")


def test_bot_wiring():
    names = [t["name"] for t in bot.current_tools()]
    assert "search_session_digests" in names and "session_digest" in names
    assert "hand-rolled stdlib" in bot.handle_tool(
        "session_digest", {"name": "youtube pipeline"})
    assert "meta collection" in bot.handle_tool(
        "search_session_digests", {"query": "sync reviews"})
    note = brain_store.prompt_note()
    assert "search_session_digests" in note and len(note) <= 700
    assert "2026-07-17" in note  # newest digest surfaces
    print("ok bot wiring")


def test_health_banner():
    # healthy: fresh sync, no errors -> no banner on replies
    fresh = memory.now().isoformat()
    brain_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    assert bot.health_banner() == ""
    # broken: a failed sync must surface mechanically, not via model goodwill
    brain_store.STATUS_PATH.write_text(json.dumps({
        "last_success": fresh, "last_error": "clone exploded",
        "last_error_time": (memory.now() + timedelta(minutes=1)).isoformat(),
    }))
    assert "FAILED" in bot.health_banner()
    brain_store.STATUS_PATH.write_text(json.dumps({"last_success": fresh}))
    print("ok health banner")


if __name__ == "__main__":
    try:
        make_source_repo()
        test_unconfigured()
        test_backup_fallback_config()
        test_brain_url_precedence()
        test_sync_update()
        test_store_reads()
        test_staleness()
        test_bot_wiring()
        test_health_banner()
        print("ALL BRAIN TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
