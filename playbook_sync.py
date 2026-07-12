"""Sync the founder's playbook (time-tracker repo) into the agent's memory bank.

Keeps a read-only, shallow git checkout under memory/playbook/repo/ — never a
copied fork that can rot (the playbook's own rule). Run directly
(`python playbook_sync.py`) or let the systemd timer call it alongside
dayos_sync. Config lives in .env:

    PLAYBOOK_REPO_URL     https://github.com/instatank/time-tracker.git
    PLAYBOOK_REPO_TOKEN   fine-grained GitHub token, Contents:read on that one
                          repo — only needed if the repo is private
    PLAYBOOK_REPO_BRANCH  defaults to main

Unset PLAYBOOK_REPO_URL = not configured = the sync skips green and the bot's
playbook tools stay hidden. Sync state lives in memory/playbook/
sync_status.json — the bot reads it to warn loudly when the mirror is stale
or the last run failed. The token is used only on the command line for
fetch/clone and is scrubbed from anything written to disk or printed.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import memory
import playbook_store


class PlaybookConfigError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def configured() -> bool:
    return bool(_env("PLAYBOOK_REPO_URL"))


def _auth_url() -> str:
    url = _env("PLAYBOOK_REPO_URL")
    token = _env("PLAYBOOK_REPO_TOKEN")
    if token and url.startswith("https://"):
        return "https://x-access-token:" + token + "@" + url[len("https://"):]
    return url


def _scrub(text: str) -> str:
    token = _env("PLAYBOOK_REPO_TOKEN")
    return text.replace(token, "***") if token else text


def _log(msg: str) -> None:
    print(f"[playbook-sync] {_scrub(msg)}", flush=True)


def _git(args: list, cwd=None) -> str:
    """Run one git command with prompts and user/system config disabled, so it
    behaves identically under systemd (no HOME) and in tests."""
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    })
    proc = subprocess.run(
        ["git"] + args, cwd=cwd, env=env, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[-400:]
        raise RuntimeError(f"git {args[0]} failed: {_scrub(detail)}")
    return proc.stdout


def _checkout(branch: str) -> str:
    """Clone or update the mirror; return the short commit hash it landed on.
    The on-disk remote URL never contains the token — auth rides only on the
    explicit fetch/clone URL."""
    repo = playbook_store.REPO_DIR
    plain_url = _env("PLAYBOOK_REPO_URL")
    if repo.exists() and not (repo / ".git").exists():
        shutil.rmtree(repo)  # half-created dir from a failed clone — disposable
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--depth", "1", "--branch", branch, _auth_url(), str(repo)])
        _git(["remote", "set-url", "origin", plain_url], cwd=repo)
    else:
        _git(["fetch", "--depth", "1", _auth_url(), branch], cwd=repo)
        _git(["reset", "--hard", "FETCH_HEAD"], cwd=repo)
    return _git(["rev-parse", "--short", "HEAD"], cwd=repo).strip()


def sync() -> dict:
    """Run one sync. Returns the status dict it wrote. Raises on failure
    (after recording the error), so callers/systemd see a loud red exit."""
    status = playbook_store.load_status()
    status["last_attempt"] = memory.now().isoformat()
    started = time.monotonic()
    try:
        if not configured():
            raise PlaybookConfigError("PLAYBOOK_REPO_URL is not set in .env")
        branch = _env("PLAYBOOK_REPO_BRANCH") or "main"
        commit = _checkout(branch)
        files = len(playbook_store.doc_files())
        if files == 0:
            raise RuntimeError(
                "checkout succeeded but contains no playbook docs — wrong repo or branch?")
        status.update({
            "last_success": memory.now().isoformat(),
            "commit": commit,
            "branch": branch,
            "files": files,
            "duration_s": round(time.monotonic() - started, 1),
        })
        status.pop("last_error", None)
        status.pop("last_error_time", None)
    except Exception as e:
        status["last_error"] = _scrub(f"{type(e).__name__}: {e}")
        status["last_error_time"] = memory.now().isoformat()
        _write_status(status)
        raise
    _write_status(status)
    _log(f"done in {status['duration_s']}s — commit {commit}, {files} docs")
    return status


def _write_status(status: dict) -> None:
    playbook_store.PLAYBOOK_DIR.mkdir(parents=True, exist_ok=True)
    playbook_store.STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync the playbook into agent memory")
    ap.add_argument("--status", action="store_true", help="print sync status and exit")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(playbook_store.load_status(), indent=2))
        return 0
    if not configured():
        # Pre-configuration this is expected — exit green so the systemd timer
        # doesn't flag red before he has even added the URL.
        _log("not configured (set PLAYBOOK_REPO_URL in .env) — skipping")
        return 0
    try:
        sync()
        return 0
    except PlaybookConfigError as e:
        _log(f"CONFIG ERROR: {e}")
        return 2
    except Exception as e:
        _log(f"SYNC FAILED: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
