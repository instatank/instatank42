"""Offline tests for the nightly memory backup — no network, no GitHub.

The "remote" is a local bare git repo (file://), the same trick the playbook
sync tests use. Verifies: the mirror lands under memory/ in the repo without
touching the repo's other lanes (sessions/), rebuildable git-mirror checkouts
are excluded, unchanged runs skip the commit, and changes push a new commit.
Run: venv/bin/python tests/test_backup.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import memory

tmp = Path(tempfile.mkdtemp())
memory.MEMORY_DIR = tmp / "memory"

import memory_backup

BRANCH = "main"


def _git(args, cwd):
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null"})
    return subprocess.run(["git"] + args, cwd=cwd, env=env, check=True,
                          capture_output=True, text=True)


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_remote() -> Path:
    """A bare repo pre-seeded with a README + a sessions/ lane, so the backup
    has a real 'main' to clone and something the mirror must NOT clobber."""
    bare = tmp / "remote.git"
    _git(["init", "--bare", "-b", BRANCH, str(bare)], cwd=tmp)
    seed = tmp / "seed"
    seed.mkdir()
    _git(["init", "-b", BRANCH, str(seed)], cwd=tmp)
    _write(seed / "README.md", "# 2ndbrain\n")
    _write(seed / "sessions" / "2026" / "first.md", "a session digest\n")
    _git(["add", "-A"], cwd=seed)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"], cwd=seed)
    _git(["push", str(bare), f"HEAD:{BRANCH}"], cwd=seed)
    return bare


def _seed_memory():
    """A realistic memory/ tree: rebuildable banks + non-rebuildable ones + a
    nested git-mirror checkout (playbook/repo) that must be excluded."""
    _write(memory.MEMORY_DIR / "profile.md", "# profile\n")
    _write(memory.MEMORY_DIR / "whatsapp" / "chats" / "mom" / "2026-07.md", "chat\n")
    _write(memory.MEMORY_DIR / "youtube" / "videos" / "abc.md", "transcript\n")
    _write(memory.MEMORY_DIR / "dayos" / "days" / "2026-07-01.md", "a day\n")
    # a nested checkout: has a .git dir -> the whole subtree must be skipped
    _write(memory.MEMORY_DIR / "playbook" / "repo" / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(memory.MEMORY_DIR / "playbook" / "repo" / "index.html", "<html>huge</html>\n")
    _write(memory.MEMORY_DIR / "playbook" / "sync_status.json", "{}\n")


def _clone_of_remote(bare: Path, name: str) -> Path:
    dest = tmp / name
    _git(["clone", "--branch", BRANCH, str(bare), str(dest)], cwd=tmp)
    return dest


BARE = None  # the seeded remote, shared across the ordered tests below


def test_backup_roundtrip():
    global BARE
    BARE = _seed_remote()
    _seed_memory()
    os.environ["BACKUP_REPO_URL"] = f"file://{BARE}"
    os.environ["BACKUP_WORK_DIR"] = str(tmp / "work")
    os.environ.pop("BACKUP_REPO_TOKEN", None)
    os.environ.pop("BACKUP_REPO_BRANCH", None)

    assert memory_backup.configured()
    status = memory_backup.sync()
    assert status["pushed"] is True
    assert "last_error" not in status
    assert status["files"] >= 4

    # Verify the pushed contents from a fresh clone of the remote.
    v = _clone_of_remote(BARE, "verify1")
    assert (v / "memory" / "profile.md").exists()
    assert (v / "memory" / "whatsapp" / "chats" / "mom" / "2026-07.md").exists()
    assert (v / "memory" / "youtube" / "videos" / "abc.md").exists()
    assert (v / "memory" / "dayos" / "days" / "2026-07-01.md").exists()
    # rebuildable git-mirror checkout excluded; its sibling status file kept
    assert not (v / "memory" / "playbook" / "repo").exists()
    assert (v / "memory" / "playbook" / "sync_status.json").exists()
    # the repo's OTHER lane is untouched by the backup
    assert (v / "README.md").exists()
    assert (v / "sessions" / "2026" / "first.md").exists()
    print("ok backup roundtrip")


def test_no_change_skips_commit():
    # Second run with an unchanged memory/ must NOT create a commit.
    before = memory_backup.sync()
    assert before["pushed"] is False
    # Now change one file -> a new commit is pushed.
    _write(memory.MEMORY_DIR / "whatsapp" / "chats" / "mom" / "2026-08.md", "more\n")
    after = memory_backup.sync()
    assert after["pushed"] is True
    v = _clone_of_remote(BARE, "verify2")
    assert (v / "memory" / "whatsapp" / "chats" / "mom" / "2026-08.md").exists()
    print("ok no-change skip + incremental push")


def test_not_configured_skips_green():
    saved = os.environ.pop("BACKUP_REPO_URL", None)
    try:
        assert not memory_backup.configured()
        assert memory_backup.main() == 0        # skips green, no raise
    finally:
        if saved is not None:
            os.environ["BACKUP_REPO_URL"] = saved
    print("ok not-configured skip")


if __name__ == "__main__":
    try:
        test_backup_roundtrip()
        test_no_change_skips_commit()
        test_not_configured_skips_green()
        print("ALL BACKUP TESTS PASSED")
    except AssertionError as e:
        print(f"FAIL: {e}")
        raise
