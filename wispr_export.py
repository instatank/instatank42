"""Wispr Flow dictation-history exporter — a personal utility script, not
part of the deployed bot. Wispr Flow's SQLite database lives on the founder's
Mac, not the VPS, so this runs locally (by hand, or on a launchd/cron
schedule) and writes to ~/WisprFlowExports/. It is version-controlled here
for the same reason dayos_sync.py and playbook_sync.py live in this repo:
one reusable, reviewable script rather than a one-off shell session.

READ-ONLY CONTRACT: this script must never write to Wispr Flow's live
database. It opens the source via a read-only SQLite URI connection and uses
SQLite's own online-backup API to produce a consistent snapshot in a temp
file — the only thing ever touched on the source path is a read.

Wispr Flow's real table/column names are NOT hardcoded here on purpose (the
brief explicitly says not to assume them). On first run this script prints
the actual schema, guesses which table holds dictation entries and which
columns map to text/timestamp/app/word-count/duration using keyword
matching, and saves that guess to .schema_map.json for you to eyeball and
correct if needed (edit the file directly, or re-run with --reconfigure).
Every field from the source row still lands in full-history.json regardless
of the guess — the column map only drives the Markdown rendering and the
incremental "since" filter.

Usage:
    python3 wispr_export.py                 # incremental (or first full) export
    python3 wispr_export.py --inspect-only  # print schema + guessed mapping, write nothing
    python3 wispr_export.py --full          # ignore saved state, re-pull everything
    python3 wispr_export.py --reconfigure   # re-guess the column mapping
    python3 wispr_export.py --db PATH       # skip discovery, use this file directly
"""

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EXPORT_DIR = Path.home() / "WisprFlowExports"
STATE_PATH = EXPORT_DIR / ".last_export.json"
MAP_PATH = EXPORT_DIR / ".schema_map.json"
JSON_PATH = EXPORT_DIR / "full-history.json"
MD_PATH = EXPORT_DIR / "full-history.md"

APP_SUPPORT = Path.home() / "Library" / "Application Support"
NAME_HINTS = ("wispr",)
DB_SUFFIXES = (".sqlite", ".sqlite3", ".db")

TEXT_RAW_HINTS = ("raw", "asr", "original", "transcript")
TEXT_FMT_HINTS = ("formatted", "clean", "edited", "final", "text", "content")
TIMESTAMP_HINTS = ("timestamp", "created", "date", "time", "inserted", "recorded")
APP_HINTS = ("app", "application", "bundle", "source", "target")
WORDCOUNT_HINTS = ("word_count", "wordcount", "words", "word")
DURATION_HINTS = ("duration", "length", "seconds", "elapsed")

# Core Data's reference date (macOS/Swift apps commonly store timestamps as
# seconds/ms since this epoch, not Unix epoch) — a real gotcha, not a guess
# to skip: silently treating one as the other is off by 31 years.
COREDATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


class DatabaseAccessError(Exception):
    pass


# --- 1. Locate --------------------------------------------------------------

def find_candidates() -> list:
    """Likely locations first (~/Library/Application Support/*wispr*), then a
    broader ~ search — mirrors the two-step search the brief specifies."""
    found = []
    if APP_SUPPORT.is_dir():
        for entry in APP_SUPPORT.iterdir():
            if entry.is_dir() and any(h in entry.name.lower() for h in NAME_HINTS):
                found += [p for p in entry.rglob("*") if p.suffix.lower() in DB_SUFFIXES]
    if found:
        return _dedup(found)

    def onerror(_exc):
        pass  # permission-denied directories are common and not fatal here

    import os
    for root, dirs, files in os.walk(Path.home(), onerror=onerror):
        for name in files:
            lname = name.lower()
            if "wispr" in lname and any(lname.endswith(s) for s in DB_SUFFIXES):
                found.append(Path(root) / name)
    return _dedup(found)


def _dedup(paths: list) -> list:
    seen, out = set(), []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def find_database(explicit: str = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise DatabaseAccessError(f"--db path does not exist: {p}")
        return p
    candidates = find_candidates()
    if not candidates:
        raise DatabaseAccessError(
            "No Wispr Flow database found under ~/Library/Application Support/ "
            "or anywhere else under your home directory. If Wispr Flow stores "
            "data somewhere unusual, pass --db /path/to/file.sqlite directly."
        )
    if len(candidates) > 1:
        print("Multiple candidate files found — using the largest (most likely "
              "the real database, not a backup/cache):", file=sys.stderr)
        for c in candidates:
            print(f"  {c}", file=sys.stderr)
    return max(candidates, key=lambda p: p.stat().st_size)


# --- 2. Safe read-only copy --------------------------------------------------

def safe_copy(db_path: Path) -> Path:
    """Read-only source connection + SQLite's online-backup API -> a fresh
    temp-file copy. Never opens the source for writing, never touches WAL/SHM
    sidecars directly, and works even while Wispr Flow itself has the file open."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="wispr_export_"))
    dest = tmp_dir / db_path.name
    try:
        src_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        src_conn.execute("SELECT 1")
    except sqlite3.OperationalError as e:
        raise DatabaseAccessError(
            "Could not open the Wispr Flow database for reading — this is very "
            "likely macOS Full Disk Access blocking it, not a bug in this script.\n"
            "Fix: System Settings -> Privacy & Security -> Full Disk Access -> "
            "enable it for the terminal app you're running this from (Terminal.app "
            "or iTerm2) -> restart that terminal -> re-run this script.\n"
            f"(Underlying error: {e})"
        ) from e
    dest_conn = sqlite3.connect(dest)
    with dest_conn:
        src_conn.backup(dest_conn)
    src_conn.close()
    dest_conn.close()
    return dest


# --- 3. Inspect schema --------------------------------------------------------

def inspect_schema(conn: sqlite3.Connection) -> dict:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    schema = {}
    for t in tables:
        cols = conn.execute(f"PRAGMA table_info('{t}')").fetchall()
        count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        schema[t] = {
            "columns": [{"name": c[1], "type": c[2]} for c in cols],
            "row_count": count,
        }
    return schema


def print_schema(schema: dict) -> None:
    print("\n=== Database schema ===")
    for table, info in schema.items():
        print(f"\n{table}  ({info['row_count']} rows)")
        for c in info["columns"]:
            print(f"    {c['name']}  {c['type']}")


def _best_match(col_names: list, hints: tuple) -> str:
    lowered = [(c.lower(), c) for c in col_names]
    for hint in hints:
        for lc, orig in lowered:
            if hint in lc:
                return orig
    return None


def guess_table_and_map(schema: dict):
    """Score every table by how strongly its columns look like dictation
    entries, then map likely field names by keyword. This is a starting
    guess, not ground truth — .schema_map.json is meant to be reviewed."""
    scored = []
    for table, info in schema.items():
        cols_lower = [c["name"].lower() for c in info["columns"]]
        text_score = sum(1 for c in cols_lower if any(h in c for h in TEXT_FMT_HINTS + TEXT_RAW_HINTS))
        ts_score = sum(1 for c in cols_lower if any(h in c for h in TIMESTAMP_HINTS))
        score = text_score * 2 + ts_score + (1 if info["row_count"] > 0 else 0)
        scored.append((score, table))
    scored.sort(key=lambda x: (-x[0], x[1]))
    if not scored or scored[0][0] == 0:
        return None, None
    best_table = scored[0][1]
    cols = [c["name"] for c in schema[best_table]["columns"]]
    colmap = {
        "text_formatted": _best_match(cols, TEXT_FMT_HINTS),
        "text_raw": _best_match(cols, TEXT_RAW_HINTS),
        "timestamp": _best_match(cols, TIMESTAMP_HINTS),
        "app": _best_match(cols, APP_HINTS),
        "word_count": _best_match(cols, WORDCOUNT_HINTS),
        "duration": _best_match(cols, DURATION_HINTS),
    }
    return best_table, colmap


def load_or_guess_map(schema: dict, reconfigure: bool) -> dict:
    if MAP_PATH.exists() and not reconfigure:
        try:
            return json.loads(MAP_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    table, colmap = guess_table_and_map(schema)
    if table is None:
        raise DatabaseAccessError(
            "Couldn't find a table that looks like dictation history in this "
            "database. Run with --inspect-only, look at the schema printed "
            "above, and if there's a plausible table, write .schema_map.json "
            "by hand (see the format this script would otherwise save)."
        )
    result = {"table": table, "columns": colmap, "timestamp_format": "auto"}
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    MAP_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\n=== Guessed column mapping (saved to .schema_map.json — edit it "
          "by hand if anything below looks wrong, then re-run) ===")
    print(json.dumps(result, indent=2))
    return result


# --- Timestamp handling -------------------------------------------------------

def detect_timestamp_format(sample_values: list) -> str:
    """Pick between ISO text, Unix seconds/ms, and Core Data seconds/ms —
    ambiguous ranges are a known trap for Swift/macOS apps, so this only
    commits to a numeric interpretation when the resulting date is plausibly
    recent; otherwise it's left for a human to confirm."""
    for v in sample_values:
        if isinstance(v, str):
            return "iso"
    numeric = [v for v in sample_values if isinstance(v, (int, float))]
    if not numeric:
        return "unknown"
    v = numeric[0]
    now_unix = datetime.now(timezone.utc).timestamp()
    now_coredata = now_unix - COREDATA_EPOCH.timestamp()
    candidates = [
        ("unix_seconds", abs(v - now_unix)),
        ("unix_millis", abs(v / 1000 - now_unix)),
        ("coredata_seconds", abs(v - now_coredata)),
        ("coredata_millis", abs(v / 1000 - now_coredata)),
    ]
    fmt, delta = min(candidates, key=lambda x: x[1])
    return fmt if delta < 60 * 60 * 24 * 365 * 3 else "unknown"  # within ~3 years of "now"


def _to_naive_utc(dt: datetime) -> datetime:
    """Every branch below funnels through here so sort/compare never mixes
    naive and aware datetimes (a real TypeError trap when some rows have
    offset-bearing ISO strings and others don't)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_ts(value, fmt: str):
    if value is None:
        return None
    try:
        if fmt == "iso":
            s = str(value).replace("Z", "+00:00")
            return _to_naive_utc(datetime.fromisoformat(s))
        if fmt == "unix_seconds":
            return _to_naive_utc(datetime.fromtimestamp(float(value), tz=timezone.utc))
        if fmt == "unix_millis":
            return _to_naive_utc(datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc))
        if fmt == "coredata_seconds":
            return _to_naive_utc(datetime.fromtimestamp(COREDATA_EPOCH.timestamp() + float(value), tz=timezone.utc))
        if fmt == "coredata_millis":
            return _to_naive_utc(datetime.fromtimestamp(COREDATA_EPOCH.timestamp() + float(value) / 1000, tz=timezone.utc))
    except (ValueError, OverflowError, OSError, TypeError):
        return None
    return None


# --- 4. Export ----------------------------------------------------------------

def fetch_rows(conn: sqlite3.Connection, table: str, ts_col: str, since_iso: str = None) -> list:
    try:
        cur = conn.execute(f'SELECT rowid AS _wispr_rowid, * FROM "{table}"')
        has_rowid = True
    except sqlite3.OperationalError:
        cur = conn.execute(f'SELECT * FROM "{table}"')
        has_rowid = False
    col_names = [d[0] for d in cur.description]
    rows = [dict(zip(col_names, row)) for row in cur.fetchall()]

    fmt = detect_timestamp_format([r.get(ts_col) for r in rows[:20] if r.get(ts_col) is not None]) if ts_col else "unknown"
    for r in rows:
        r["_parsed_ts"] = parse_ts(r.get(ts_col), fmt) if ts_col else None
        r["_key"] = _row_key(r, has_rowid)

    rows.sort(key=lambda r: r["_parsed_ts"] or datetime.min)
    if since_iso:
        since_dt = datetime.fromisoformat(since_iso)
        rows = [r for r in rows if r["_parsed_ts"] and r["_parsed_ts"] > since_dt]
    return rows, fmt


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: dict) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _row_key(row: dict, has_rowid: bool) -> str:
    """A stable identity for dedup across runs. Computed once at fetch time
    from the real columns only (never from internal _-prefixed fields) and
    persisted as "_key" in the JSON output, so re-loading it later needs no
    reconstruction — that mismatch (fresh-row dict shape vs. stored-entry
    shape) is exactly what silently broke dedup on --full re-pulls before."""
    if has_rowid and row.get("_wispr_rowid") is not None:
        return f"rowid:{row['_wispr_rowid']}"
    cols = {k: v for k, v in row.items() if not k.startswith("_")}
    return f"hash:{hash(json.dumps(cols, sort_keys=True, default=str))}"


def load_accumulated() -> list:
    if JSON_PATH.exists():
        try:
            return json.loads(JSON_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def merge_entries(existing: list, new_rows: list) -> list:
    def strip(r):
        return {k: v for k, v in r.items() if k not in ("_parsed_ts",)}

    seen = {e.get("_key") for e in existing}
    merged = list(existing)
    for r in new_rows:
        if r["_key"] not in seen:
            out = strip(r)
            out["_exported_ts"] = r["_parsed_ts"].isoformat() if r["_parsed_ts"] else None
            merged.append(out)
            seen.add(r["_key"])
    return merged


def render_markdown(entries: list, colmap: dict) -> str:
    by_date = {}
    for e in entries:
        ts = e.get("_exported_ts")
        date_key = ts[:10] if ts else "unknown-date"
        by_date.setdefault(date_key, []).append(e)

    lines = ["# Wispr Flow — Full Dictation History", ""]
    for date_key in sorted(by_date, reverse=True):
        lines.append(f"## {date_key}")
        lines.append("")
        day_entries = sorted(by_date[date_key], key=lambda e: e.get("_exported_ts") or "", reverse=True)
        for e in day_entries:
            ts = e.get("_exported_ts")
            time_str = ts[11:19] if ts else "unknown time"
            app = e.get(colmap.get("app")) if colmap.get("app") else None
            header = f"**{time_str}** — _{app or 'unknown app'}_"
            wc = e.get(colmap.get("word_count")) if colmap.get("word_count") else None
            dur = e.get(colmap.get("duration")) if colmap.get("duration") else None
            meta = [f"{wc} words"] if wc is not None else []
            if dur is not None:
                meta.append(f"{dur}s")
            if meta:
                header += f" ({', '.join(meta)})"
            lines.append(header)
            lines.append("")
            formatted = e.get(colmap.get("text_formatted")) if colmap.get("text_formatted") else None
            raw = e.get(colmap.get("text_raw")) if colmap.get("text_raw") else None
            if formatted:
                lines.append(str(formatted).strip())
                if raw and str(raw).strip() and str(raw).strip() != str(formatted).strip():
                    lines.append("")
                    lines.append(f"<details><summary>raw ASR</summary>\n\n{str(raw).strip()}\n\n</details>")
            elif raw:
                lines.append(str(raw).strip())
            else:
                lines.append("_(no transcript text found in the mapped columns — check .schema_map.json)_")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def write_outputs(entries: list, colmap: dict) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")
    MD_PATH.write_text(render_markdown(entries, colmap), encoding="utf-8")


# --- Orchestration --------------------------------------------------------------

def run(db_arg: str = None, inspect_only: bool = False, full: bool = False, reconfigure: bool = False) -> dict:
    db_path = find_database(db_arg)
    print(f"Using database: {db_path}")
    copy_path = safe_copy(db_path)
    conn = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
    try:
        schema = inspect_schema(conn)
        print_schema(schema)
        if inspect_only:
            guess_table_and_map(schema)  # preview only, don't persist
            return {}

        mapping = load_or_guess_map(schema, reconfigure)
        table, colmap, ts_col = mapping["table"], mapping["columns"], mapping["columns"].get("timestamp")

        state = {} if full else load_state()
        since = state.get("last_exported_ts")
        rows, ts_format = fetch_rows(conn, table, ts_col, since)

        existing = [] if full else load_accumulated()
        merged = merge_entries(existing, rows)
        write_outputs(merged, colmap)

        last_ts = max((r["_parsed_ts"] for r in rows if r["_parsed_ts"]), default=None)
        if last_ts:
            save_state({"last_exported_ts": last_ts.isoformat(), "timestamp_format": ts_format})

        all_ts = [e.get("_exported_ts") for e in merged if e.get("_exported_ts")]
        summary = {
            "total_entries": len(merged),
            "new_this_run": len(rows),
            "date_range": (min(all_ts)[:10], max(all_ts)[:10]) if all_ts else (None, None),
            "timestamp_format_detected": ts_format,
            "table_used": table,
        }
        return summary
    finally:
        conn.close()
        copy_path.unlink(missing_ok=True)
        copy_path.parent.rmdir()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspect-only", action="store_true", help="print schema + guessed mapping, write nothing")
    ap.add_argument("--full", action="store_true", help="ignore saved state, re-pull everything from the DB")
    ap.add_argument("--reconfigure", action="store_true", help="re-guess the column mapping and overwrite .schema_map.json")
    ap.add_argument("--db", help="path to the Wispr Flow SQLite file (skips discovery)")
    args = ap.parse_args()

    try:
        summary = run(db_arg=args.db, inspect_only=args.inspect_only, full=args.full, reconfigure=args.reconfigure)
    except DatabaseAccessError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.inspect_only:
        print("\n(--inspect-only: nothing was written)")
        return

    print("\n=== Export summary ===")
    print(f"Table used:        {summary['table_used']}")
    print(f"Timestamp format:  {summary['timestamp_format_detected']}  "
          f"(if this looks wrong, edit timestamp_format in .schema_map.json)")
    print(f"Total entries:     {summary['total_entries']}")
    print(f"New this run:      {summary['new_this_run']}")
    print(f"Date range:        {summary['date_range'][0]} -> {summary['date_range'][1]}")
    print(f"\nWritten to {JSON_PATH} and {MD_PATH}")


if __name__ == "__main__":
    main()
