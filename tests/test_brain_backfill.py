"""Offline tests for brain_backfill.py — no network (the API seam is faked), no
real Claude Code data (synthetic JSONL fixtures, since the true schema only
exists on the founder's Mac). Validates the mechanism: enumeration, tool-noise
stripping, filters, skip-already-done, naming, and the write+commit path.
Run: venv/bin/python tests/test_brain_backfill.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import brain_backfill as bb

tmp = Path(tempfile.mkdtemp())
PROJECTS = tmp / "projects"
REPO = tmp / "2ndbrain"


def _line(role, content, ts, **extra):
    obj = {"type": role, "message": {"role": role, "content": content},
           "timestamp": ts, "sessionId": "x"}
    obj.update(extra)
    return json.dumps(obj)


def write_fixtures():
    d = PROJECTS / "-Users-ankit-Code-instatank42"
    d.mkdir(parents=True)
    # A real session: user prose, assistant text + a tool_use block (must be
    # stripped), a user turn that's purely a tool_result (no prose -> dropped).
    (d / "1111aaaa-0000-0000-0000-000000000000.jsonl").write_text("\n".join([
        _line("user", "Help me design the YouTube pipeline for the brain.",
              "2026-07-16T09:00:00Z"),
        _line("assistant", [
            {"type": "text", "text": "We chose send-a-link tagging over playlists."},
            {"type": "tool_use", "name": "Write", "input": {"secret": "sk-SHOULD-NOT-APPEAR"}},
        ], "2026-07-16T09:01:00Z"),
        _line("user", [{"type": "tool_result", "content": "file written"}],
              "2026-07-16T09:01:30Z"),
        _line("assistant", "Silent auto-fetch from DayOS was your call.",
              "2026-07-16T09:02:00Z"),
        _line("user", "Great, ship it.", "2026-07-16T09:03:00Z"),
        # a subagent sidechain line — must be ignored
        _line("assistant", "sidechain noise", "2026-07-16T09:02:30Z", isSidechain=True),
    ]), encoding="utf-8")
    # A trivial session (below min-turns) in a different project.
    d2 = PROJECTS / "-Users-ankit-Code-scratch"
    d2.mkdir(parents=True)
    (d2 / "2222bbbb-0000-0000-0000-000000000000.jsonl").write_text(
        _line("user", "hi", "2026-05-01T10:00:00Z") + "\n" +
        _line("assistant", "hello", "2026-05-01T10:00:05Z"), encoding="utf-8")


def fake_api(system, transcript, model):
    fake_api.calls.append((system, transcript, model))
    assert "SHOULD-NOT-APPEAR" not in transcript, "tool input leaked into transcript"
    return "# Test Digest\n\n## Decisions made\n- Chose tagging over playlists."
fake_api.calls = []


def init_repo():
    REPO.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=REPO, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=REPO, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=REPO, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=REPO, check=True)
    # brain_backfill runs `git pull --ff-only`; give it a no-op upstream
    bare = tmp / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=REPO, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=REPO, check=True)
    subprocess.run(["git", "branch", "-q", "--set-upstream-to=origin/main"], cwd=REPO, check=True)


class Args:
    def __init__(self, **kw):
        self.list = self.dry_run = self.push = self.yes = False
        self.repo = str(REPO)
        self.projects_dir = str(PROJECTS)
        self.since = self.project = self.limit = None
        self.min_turns = bb.MIN_TURNS
        self.model = "claude-sonnet-5"
        self.__dict__.update(kw)


def test_parse_strips_noise():
    files = bb.iter_session_files(PROJECTS)
    assert len(files) == 2
    real = bb.parse_session(PROJECTS / "-Users-ankit-Code-instatank42" /
                            "1111aaaa-0000-0000-0000-000000000000.jsonl")
    assert real["project"] == "instatank42"
    # tool_use block, tool_result-only user turn, and sidechain line all gone
    texts = [t for _r, t in real["turns"]]
    assert "We chose send-a-link tagging" in texts[1]
    assert not any("SHOULD-NOT-APPEAR" in t for t in texts)
    assert not any("file written" in t for t in texts)
    assert not any("sidechain" in t for t in texts)
    assert real["first_user"].startswith("Help me design")
    assert real["start"].strftime("%Y-%m-%d") == "2026-07-16"
    print("ok parse strips noise")


def test_select_filters():
    parsed = [bb.parse_session(f) for f in bb.iter_session_files(PROJECTS)]
    # min-turns drops the 2-line scratch session
    assert [s["project"] for s in bb.select(parsed, Args())] == ["instatank42"]
    # project filter
    assert bb.select(parsed, Args(project="scratch", min_turns=1))[0]["project"] == "scratch"
    # since filter excludes the May session
    assert len(bb.select(parsed, Args(since="2026-07-01", min_turns=1))) == 1
    # limit
    assert len(bb.select(parsed, Args(limit=1, min_turns=1))) == 1
    print("ok select filters")


def test_naming_and_cost():
    s = bb.parse_session(PROJECTS / "-Users-ankit-Code-instatank42" /
                         "1111aaaa-0000-0000-0000-000000000000.jsonl")
    p = bb.digest_path(REPO, s)
    assert p.parent == REPO / "sessions" / "2026"
    assert p.name.startswith("2026-07-16--instatank42--help-me-design")
    assert "claude-sonnet-5" in bb.cost_line([s], "claude-sonnet-5")
    print("ok naming + cost")


def test_backfill_writes_commits_and_skips():
    bb._call_api = fake_api
    # real run
    rc = bb.run(Args(yes=True))
    assert rc == 0 and len(fake_api.calls) == 1
    digests = list((REPO / "sessions").rglob("*.md"))
    assert len(digests) == 1
    body = digests[0].read_text(encoding="utf-8")
    assert "# Test Digest" in body
    assert "<!-- session-id: 1111aaaa-0000-0000-0000-000000000000 -->" in body
    # committed
    log = subprocess.run(["git", "log", "--oneline"], cwd=REPO,
                         capture_output=True, text=True).stdout
    assert "backfill: 1 Claude Code session digest" in log
    # re-run: the one session is now marked done -> skipped, no new API call
    fake_api.calls.clear()
    rc = bb.run(Args(yes=True))
    assert rc == 0 and fake_api.calls == []
    assert len(list((REPO / "sessions").rglob("*.md"))) == 1
    print("ok backfill writes, commits, and skips on re-run")


def test_list_and_dry_run_write_nothing():
    shutil.rmtree(REPO / "sessions")
    subprocess.run(["git", "commit", "-aqm", "clear"], cwd=REPO, check=True)
    before = len(list((REPO / "sessions").rglob("*.md"))) if (REPO / "sessions").exists() else 0
    bb.run(Args(list=True))                     # prints, writes nothing
    bb.run(Args(dry_run=True))                  # plan + cost, writes nothing
    after = len(list((REPO / "sessions").rglob("*.md"))) if (REPO / "sessions").exists() else 0
    assert before == after == 0
    print("ok list + dry-run write nothing")


def test_empty_projects_dir():
    empty = tmp / "empty"
    empty.mkdir()
    assert bb.iter_session_files(empty) == []
    # run --list against it just prints the "nothing found" guidance, rc 0
    assert bb.run(Args(list=True, projects_dir=str(empty))) == 0
    print("ok empty projects dir")


if __name__ == "__main__":
    try:
        write_fixtures()
        init_repo()
        test_parse_strips_noise()
        test_select_filters()
        test_naming_and_cost()
        test_backfill_writes_commits_and_skips()
        test_list_and_dry_run_write_nothing()
        test_empty_projects_dir()
        print("ALL BRAIN-BACKFILL TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
