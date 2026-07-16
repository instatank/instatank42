"""Nightly backup + visibility mirror of the whole memory/ tree to a private
git repo (instatank/2ndbrain).

Two jobs at once (founder decision 2026-07-16):
  - A real BACKUP. The DayOS and playbook banks are rebuildable — delete them
    and the next sync restores them from Firestore / the git remote. But the
    WhatsApp exports, YouTube transcripts, and anything the founder pasted in
    are NOT rebuildable from any source of truth; if the VPS dies they're gone.
    This copies them off-box every night.
  - VISIBILITY. The founder can finally SEE his brain's actual files — browse
    them on GitHub, or point an Obsidian vault at a clone of the repo — instead
    of them living only on a server he never logs into.

Git handling mirrors playbook_sync.py: the auth token is read from env, used
only on the fetch/clone/push command line, and NEVER written to the on-disk
remote or any log.

Config (.env):
    BACKUP_REPO_URL      https://github.com/instatank/2ndbrain.git
    BACKUP_REPO_TOKEN    fine-grained GitHub token, Contents:read+write on that
                         one repo (needed to PUSH — the repo is private)
    BACKUP_REPO_BRANCH   defaults to main
    BACKUP_WORK_DIR      where the working clone + status live; defaults to
                         <app dir>/.brain-backup (OUTSIDE memory/, so the backup
                         never tries to back up its own clone)

Unset BACKUP_REPO_URL = not configured = the job skips green (same as the sync
jobs pre-configuration). The mirror lands under a `memory/` subfolder of the
repo, so it sits alongside the repo's existing `sessions/` lane (the
/save-to-brain session digests) without touching it.

Safety: memory/ contains NO secrets by design — the .env and Firebase key live
outside it (/opt/instatank-agent/.env, .firebase-sa.json). Rebuildable git-
mirror checkouts inside memory/ (e.g. playbook/repo) are skipped: they'd bloat
the backup with a whole other repo's history and re-clone on demand anyway.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import memory

DEST_SUBDIR = "memory"  # the mirror lands under <repo>/memory/


class BackupConfigError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def configured() -> bool:
    return bool(_env("BACKUP_REPO_URL"))


def _work_dir() -> Path:
    return Path(_env("BACKUP_WORK_DIR") or (memory.MEMORY_DIR.parent / ".brain-backup"))


def _clone_dir() -> Path:
    return _work_dir() / "repo"


def _status_path() -> Path:
    return _work_dir() / "status.json"


def _auth_url() -> str:
    url = _env("BACKUP_REPO_URL")
    token = _env("BACKUP_REPO_TOKEN")
    if token and url.startswith("https://"):
        return "https://x-access-token:" + token + "@" + url[len("https://"):]
    return url


def _scrub(text: str) -> str:
    token = _env("BACKUP_REPO_TOKEN")
    return text.replace(token, "***") if token else text


def _log(msg: str) -> None:
    print(f"[memory-backup] {_scrub(msg)}", flush=True)


def _git(args: list, cwd=None) -> str:
    """One git command with prompts + user/system config disabled, so it behaves
    identically under systemd (no HOME) and in tests (mirrors playbook_sync)."""
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    })
    proc = subprocess.run(
        ["git"] + args, cwd=cwd, env=env, capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[-400:]
        raise RuntimeError(f"git {args[0]} failed: {_scrub(detail)}")
    return proc.stdout


def _copy_memory(dest: Path) -> int:
    """Replace dest with a fresh copy of memory/, skipping `.git` dirs and any
    nested git-mirror checkout wholesale (a dir containing `.git` = a mirrored
    external repo, rebuildable). Returns the number of files copied."""
    src = memory.MEMORY_DIR
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for root, dirs, files in os.walk(src):
        rootp = Path(root)
        if rootp != src and ".git" in dirs:
            dirs[:] = []          # nested checkout — skip its whole subtree
            continue
        dirs[:] = [d for d in dirs if d != ".git"]
        rel = rootp.relative_to(src)
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for f in sorted(files):
            shutil.copy2(rootp / f, dest / rel / f)
            count += 1
    return count


def _ensure_clone(branch: str) -> Path:
    """Clone the backup repo (or update an existing checkout to origin/branch).
    The on-disk remote never carries the token — auth rides only on the
    explicit fetch/clone URLs passed here."""
    clone = _clone_dir()
    plain_url = _env("BACKUP_REPO_URL")
    if clone.exists() and not (clone / ".git").exists():
        shutil.rmtree(clone)  # half-made dir from a failed clone — disposable
    if not clone.exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--branch", branch, _auth_url(), str(clone)])
        _git(["remote", "set-url", "origin", plain_url], cwd=clone)
    else:
        _git(["remote", "set-url", "origin", plain_url], cwd=clone)
        _git(["fetch", _auth_url(), branch], cwd=clone)
        _git(["reset", "--hard", "FETCH_HEAD"], cwd=clone)
    return clone


def _commit_and_push(clone: Path, branch: str, stamp: str) -> bool:
    """Stage the memory/ subtree, commit if anything changed, push. Returns True
    if a commit was pushed, False if the mirror was already up to date. On a
    non-fast-forward (a concurrent /save-to-brain push to sessions/), rebase
    onto the new remote head once and retry — our commit only touches memory/,
    so it never conflicts with the sessions/ lane."""
    _git(["add", "-A", DEST_SUBDIR], cwd=clone)
    if not _git(["status", "--porcelain", DEST_SUBDIR], cwd=clone).strip():
        return False
    _git(["-c", "user.name=DayOS brain backup",
          "-c", "user.email=backup@instatank.local",
          "commit", "-m", f"Brain memory backup {stamp}"], cwd=clone)
    try:
        _git(["push", _auth_url(), f"HEAD:{branch}"], cwd=clone)
    except RuntimeError:
        _git(["fetch", _auth_url(), branch], cwd=clone)
        _git(["rebase", "FETCH_HEAD"], cwd=clone)
        _git(["push", _auth_url(), f"HEAD:{branch}"], cwd=clone)
    return True


def _notify_failure(text: str) -> None:
    """Best-effort Telegram alert so a silent backup failure can't hide (memory
    banks aren't in the bot's health banner). Never raises — a notify failure
    must not mask the real error."""
    try:
        import httpx
        token = _env("TELEGRAM_BOT_TOKEN")
        chat_id = _env("TELEGRAM_ALLOWED_USER_ID")
        if not token or not chat_id:
            return
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text}, timeout=30,
        )
    except Exception as e:  # noqa: BLE001 — best-effort, swallow everything
        _log(f"(failure alert could not be sent: {type(e).__name__})")


def load_status() -> dict:
    p = _status_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_status(status: dict) -> None:
    _work_dir().mkdir(parents=True, exist_ok=True)
    _status_path().write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def sync() -> dict:
    """Run one backup. Returns the status dict it wrote. Raises on failure
    (after recording the error + alerting), so systemd sees a red exit."""
    status = load_status()
    status["last_attempt"] = memory.now().isoformat()
    started = time.monotonic()
    try:
        if not configured():
            raise BackupConfigError("BACKUP_REPO_URL is not set in .env")
        if not memory.MEMORY_DIR.exists():
            raise RuntimeError("no memory/ directory to back up yet")
        branch = _env("BACKUP_REPO_BRANCH") or "main"
        clone = _ensure_clone(branch)
        n_files = _copy_memory(clone / DEST_SUBDIR)
        stamp = memory.now().strftime("%Y-%m-%d %H:%M IST")
        pushed = _commit_and_push(clone, branch, stamp)
        commit = _git(["rev-parse", "--short", "HEAD"], cwd=clone).strip()
        status.update({
            "last_success": memory.now().isoformat(),
            "files": n_files,
            "pushed": pushed,
            "branch": branch,
            "commit": commit,
            "duration_s": round(time.monotonic() - started, 1),
        })
        status.pop("last_error", None)
        status.pop("last_error_time", None)
    except Exception as e:
        status["last_error"] = _scrub(f"{type(e).__name__}: {e}")
        status["last_error_time"] = memory.now().isoformat()
        _write_status(status)
        _notify_failure(f"⚠️ Brain backup FAILED: {status['last_error']}")
        raise
    _write_status(status)
    _log(f"done in {status['duration_s']}s — {n_files} files, "
         + ("pushed " + commit if pushed else "no changes"))
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description="Back up memory/ to the private brain repo")
    ap.add_argument("--status", action="store_true", help="print status and exit")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(load_status(), indent=2))
        return 0
    if not configured():
        # Pre-configuration this is expected — exit green so the timer doesn't
        # flag red before the founder has added the repo URL + token.
        _log("not configured (set BACKUP_REPO_URL in .env) — skipping")
        return 0
    try:
        sync()
        return 0
    except BackupConfigError as e:
        _log(f"CONFIG ERROR: {e}")
        return 2
    except Exception as e:
        _log(f"BACKUP FAILED: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
