"""Sync the second brain's storehouse (instatank/2ndbrain) into the agent.

Keeps a read-only, shallow git checkout under memory/brain/repo/ — the same
git-mirror pattern as playbook_sync.py. The repo is where the /save-to-brain
skill pushes Claude Code session digests; brain_store.py reads its
`sessions/` lane. Run directly (`python brain_sync.py`) or let the systemd
timer call it alongside the other syncs. Config lives in .env:

    BRAIN_REPO_URL      https://github.com/instatank/2ndbrain.git
    BRAIN_REPO_TOKEN    fine-grained GitHub token, Contents:read on that one
                        repo (it is private)
    BRAIN_REPO_BRANCH   defaults to main

Because the nightly backup (memory_backup.py) already points at the very
same repo, an UNSET BRAIN_REPO_URL falls back to BACKUP_REPO_URL /
BACKUP_REPO_TOKEN / BACKUP_REPO_BRANCH — so a VPS with the backup configured
gets this bank with zero new configuration. Neither set = not configured =
the sync skips green and the bot's session-digest tools stay hidden. Sync
state lives in memory/brain/sync_status.json — the bot reads it to warn
loudly when the mirror is stale or the last run failed. Tokens are used only
on the command line for fetch/clone and are scrubbed from anything written
to disk or printed.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import brain_store
import memory


class BrainConfigError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _cfg() -> tuple:
    """(url, token, branch) — BRAIN_* if set, else the backup repo's values
    wholesale (they point at the same repo). Token and URL travel as a pair
    so a BACKUP token is never sent to a differently-configured BRAIN url."""
    url = _env("BRAIN_REPO_URL")
    if url:
        return url, _env("BRAIN_REPO_TOKEN"), _env("BRAIN_REPO_BRANCH") or "main"
    return (_env("BACKUP_REPO_URL"), _env("BACKUP_REPO_TOKEN"),
            _env("BRAIN_REPO_BRANCH") or _env("BACKUP_REPO_BRANCH") or "main")


def configured() -> bool:
    return bool(_cfg()[0])


def _auth_url() -> str:
    url, token, _ = _cfg()
    if token and url.startswith("https://"):
        return "https://x-access-token:" + token + "@" + url[len("https://"):]
    return url


def _scrub(text: str) -> str:
    for token in (_env("BRAIN_REPO_TOKEN"), _env("BACKUP_REPO_TOKEN")):
        if token:
            text = text.replace(token, "***")
    return text


def _log(msg: str) -> None:
    print(f"[brain-sync] {_scrub(msg)}", flush=True)


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
    repo = brain_store.REPO_DIR
    plain_url = _cfg()[0]
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
    status = brain_store.load_status()
    status["last_attempt"] = memory.now().isoformat()
    started = time.monotonic()
    try:
        if not configured():
            raise BrainConfigError(
                "BRAIN_REPO_URL is not set in .env (and no BACKUP_REPO_URL to fall back to)")
        branch = _cfg()[2]
        commit = _checkout(branch)
        if not brain_store.has_data():
            raise RuntimeError(
                "checkout succeeded but has no sessions/ folder — wrong repo or branch?")
        files = len(brain_store.digest_files())
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
    _log(f"done in {status['duration_s']}s — commit {commit}, {files} session digests")
    return status


def _write_status(status: dict) -> None:
    brain_store.BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    brain_store.STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync the 2ndbrain repo into agent memory")
    ap.add_argument("--status", action="store_true", help="print sync status and exit")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(brain_store.load_status(), indent=2))
        return 0
    if not configured():
        # Pre-configuration this is expected — exit green so the systemd timer
        # doesn't flag red before he has even added the URL.
        _log("not configured (set BRAIN_REPO_URL or BACKUP_REPO_URL in .env) — skipping")
        return 0
    try:
        sync()
        return 0
    except BrainConfigError as e:
        _log(f"CONFIG ERROR: {e}")
        return 2
    except Exception as e:
        _log(f"SYNC FAILED: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
