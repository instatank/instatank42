"""Telegram file-drop ingestion — shared building block #2 (docs/BACKLOG.md).

The generic upload→detect→confirm→ingest pipeline: the bot hands any document
the founder uploads to detect(), which asks every registered parser whether it
recognizes the file; the bot shows the winning parser's preview and waits for
an explicit button press (confirm-first — nothing enters the brain silently);
run() then executes the ingest. Adding a future source (trading-journal CSVs,
broker statements, ...) means writing one parser module with the PARSER
contract below and adding it to PARSERS — this file shouldn't need to change.

Parser contract (see whatsapp_ingest.PARSER):
    name          str, unique
    detect(filename, text)  -> {"preview": str, ...} when recognized, else None
    ingest(filename, text)  -> summary str (raises on failure)
    record_error(err)       (optional) persist the failure so the bank's
                            staleness/health machinery surfaces it (Rule 4)
"""

import io
import zipfile

import whatsapp_ingest

PARSERS = [whatsapp_ingest.PARSER]

MAX_FILE_BYTES = 8_000_000   # exports are text; anything bigger is suspect


def extract_text(filename: str, data: bytes) -> tuple:
    """Uploaded bytes -> (filename_for_detection, text). Unwraps the iOS-style
    .zip export (takes the largest .txt member, skips media); raises ValueError
    for anything that isn't usable text."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"file is {len(data) / 1e6:.1f} MB — over the {MAX_FILE_BYTES / 1e6:.0f} MB ingest cap")
    name = filename or "upload"
    if name.lower().endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("file has a .zip name but isn't a valid zip")
        txts = [i for i in zf.infolist() if i.filename.lower().endswith(".txt")]
        if not txts:
            raise ValueError("zip contains no .txt file")
        inner = max(txts, key=lambda i: i.file_size)
        if inner.file_size > MAX_FILE_BYTES:
            raise ValueError("the .txt inside the zip is over the ingest cap")
        data = zf.read(inner)
        # iOS zips hold an anonymous "_chat.txt" — the outer name carries the
        # chat name, so keep it for detection in that case.
        if not inner.filename.rsplit("/", 1)[-1].startswith("_chat"):
            name = inner.filename.rsplit("/", 1)[-1]
    try:
        return name, data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("file isn't UTF-8 text — is this really a chat export?")


def detect(filename: str, text: str) -> tuple:
    """Ask each parser in turn. Returns (parser, info) or (None, reason)."""
    for parser in PARSERS:
        info = parser["detect"](filename, text)
        if info:
            return parser, info
    known = ", ".join(p["name"] for p in PARSERS)
    return None, (
        "I didn't recognize that file as anything I can ingest "
        f"(I currently understand: {known} exports). Nothing was saved."
    )


def run(parser_name: str, filename: str, text: str) -> str:
    """Execute a confirmed ingest. Failures are recorded to the bank's status
    file (so the health banner picks them up) and re-raised for the caller
    to report on Telegram — loud in both places, silent in neither."""
    parser = next(p for p in PARSERS if p["name"] == parser_name)
    try:
        return parser["ingest"](filename, text)
    except Exception as e:
        if parser.get("record_error"):
            parser["record_error"](str(e))
        raise
