"""The private database: the faithful text of the minutes, searchable, with the parcels the sales name.

Built only on the maintainer's machine and written only under a `private/` folder (git-ignored). It
holds names exactly as published and cadastral parcel references, so it must never reach the website,
the API, the Hugging Face Space or an MCP server. The public database (db.py) is the only one they read.

Parcel references are read by rules from two forms of the minutes: inline ("cadastrée C0551") and the
pre-emption tables ("Réf. Cadastrale | AB | 490 | ... Superficie totale"), plus bare codes such as AB0423
on pages that mention the cadastre. Pages read by OCR make mistakes, so every parcel carries `ocr` and a
`form`, and none is trusted until someone has looked at the page.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .db import MAX_RESULTS, _fts_query

SCHEMA = """
PRAGMA journal_mode = DELETE;
CREATE TABLE meetings (id TEXT PRIMARY KEY, date TEXT, source_url TEXT NOT NULL, source_sha256 TEXT, version INTEGER, folder TEXT);
CREATE TABLE pages (meeting_id TEXT NOT NULL REFERENCES meetings(id), page INTEGER NOT NULL, method TEXT, status TEXT,
                    page_url TEXT, text TEXT NOT NULL, PRIMARY KEY (meeting_id, page));
CREATE VIRTUAL TABLE pages_fts USING fts5(meeting_id UNINDEXED, page UNINDEXED, text, tokenize = 'unicode61 remove_diacritics 2');
CREATE TABLE parcels (meeting_id TEXT NOT NULL REFERENCES meetings(id), page INTEGER NOT NULL, section TEXT NOT NULL,
                      number TEXT NOT NULL, form TEXT NOT NULL, ocr INTEGER NOT NULL, context TEXT NOT NULL,
                      PRIMARY KEY (meeting_id, page, section, number));
CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# OCR turns "AB" into "ÆB"; only accept the substitution on pages that were read by OCR.
_OCR_LETTERS = {"Æ": "A", "Œ": "O"}
_INLINE = re.compile(r"(?i:cadastr[ée]e?s?)\s*(?:section\s*)?([A-ZÆ]{1,2})\s*(?:n°\s*)?0*(\d{1,4})\b")
_TABLE = re.compile(r"\|\s*([A-ZÆ]{1,2})\s*\|\s*0*(\d{1,4})\s*\|")
_BARE = re.compile(r"\b([A-Z]{2})\s?0(\d{3})\b")
_CADASTRE = re.compile(r"cadastr", re.I)
# Pre-emption tables in the text layer come out stacked, one cell per line: header cells, then section, number, place, area.
_STACKED = re.compile(r"Superficie totale\s*\n((?:[^\n]*\n){1,12}?)\s*Usage", re.I)
_SECTION_LINE = re.compile(r"[A-ZÆ]{1,2}")
_NUMBER_LINE = re.compile(r"0*(\d{1,4})")


def require_private_path(path):
    """The private database may only be written inside a folder named `private`."""
    if "private" not in Path(path).resolve().parts:
        raise ValueError(f"refusing to write {path}: the private database must live under a private/ folder")
    return Path(path)


def parcel_references(text, ocr=False):
    """[(section, number, form, context)] found on one page. `number` is 4 digits, as the cadastre writes it."""
    if not _CADASTRE.search(text) and "Superficie" not in text:
        return []
    found = {}
    matches = [(form, m.group(1), m.group(2), m.start(), m.end()) for form, rx in
               (("inline", _INLINE), ("table", _TABLE), ("bare", _BARE)) for m in rx.finditer(text)]
    for block in _STACKED.finditer(text):
        lines = [ln.strip() for ln in block.group(1).splitlines() if ln.strip()]
        for a, b in zip(lines, lines[1:]):
            if _SECTION_LINE.fullmatch(a) and _NUMBER_LINE.fullmatch(b):
                matches.append(("table", a, _NUMBER_LINE.fullmatch(b).group(1), block.start(), block.end()))
    for form, section, number, start, end in matches:
        if any(ch in _OCR_LETTERS for ch in section):
            if not ocr:
                continue
            section = "".join(_OCR_LETTERS.get(ch, ch) for ch in section)
        context = re.sub(r"\s+", " ", text[max(0, start - 80):end + 80]).strip()
        found.setdefault((section, number.zfill(4)), (section, number.zfill(4), form, context))
    return list(found.values())


def build_private(public_dir, out_path):
    """Write the private database from the faithful record in public/minutes. Returns counts."""
    public, out = Path(public_dir), require_private_path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    folders = {}
    for p in (public / "meetings").glob("*/minutes.md"):
        m = re.search(r"^document_id:\s*(\S+)", p.read_text(encoding="utf-8"), re.M)
        if m:
            folders[m.group(1)] = p.parent.name
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    counts = {"meetings": 0, "pages": 0, "parcels": 0, "ocr_parcels": 0}
    for entry in index["documents"]:
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        date = (rec.get("meeting_date") or {}).get("value")
        db.execute("INSERT INTO meetings VALUES (?,?,?,?,?,?)", (rec["document_id"], date, rec["source_url"],
                   rec.get("source_sha256"), rec.get("version", 1), folders.get(rec["document_id"])))
        counts["meetings"] += 1
        for pg in rec["pages"]:
            text = pg.get("text") or ""
            ocr = (pg.get("method") or "text_layer") != "text_layer"
            db.execute("INSERT INTO pages VALUES (?,?,?,?,?,?)", (rec["document_id"], pg["page"], pg.get("method"),
                                                                 pg.get("status"), pg.get("page_url"), text))
            db.execute("INSERT INTO pages_fts VALUES (?,?,?)", (rec["document_id"], pg["page"], text))
            counts["pages"] += 1
            for section, number, form, context in parcel_references(text, ocr):
                db.execute("INSERT OR IGNORE INTO parcels VALUES (?,?,?,?,?,?,?)",
                           (rec["document_id"], pg["page"], section, number, form, int(ocr), context))
                counts["parcels"] += 1
                counts["ocr_parcels"] += int(ocr)
    info = {"layer": "PRIVATE: faithful text with names and parcel references. Never publish.",
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "counts": json.dumps(counts)}
    db.executemany("INSERT INTO build_info VALUES (?,?)", info.items())
    db.commit()
    db.close()
    return counts


def search_private(db_path, q, limit=10):
    """Faithful-text matches for `q`, with the page of the original to check."""
    query = _fts_query(q or "")
    if not query:
        return []
    limit = max(1, min(int(limit), MAX_RESULTS))
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("""SELECT f.meeting_id, f.page, snippet(pages_fts, 2, '[', ']', '…', 24) AS snippet, m.date, p.page_url
                             FROM pages_fts f JOIN meetings m ON m.id = f.meeting_id
                             JOIN pages p ON p.meeting_id = f.meeting_id AND p.page = f.page
                             WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts) LIMIT ?""", (query, limit)).fetchall()
        return [{"meeting_date": r["date"], "page": r["page"], "snippet": r["snippet"], "original": r["page_url"]} for r in rows]
    finally:
        db.close()
