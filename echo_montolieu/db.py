"""The public database: a derived, scrubbed, searchable copy of what the minutes say.

Built from public/ (never from private/), by rules only. It holds the same scrubbed items the facts
pages show, plus the model-written summaries once they exist, indexed with SQLite FTS5. Property
sales are in it as a count and a neutral title, nothing more. Archived (2003-2008) minutes are not in
it yet because their layout has not been checked for names.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import disclosure
from .meeting import parse_meeting

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"
MAX_QUERY_CHARS = 200
MAX_RESULTS = 20
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _front(text):
    m = _FRONT.match(text)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end():] if m else text


def _folders(public):
    out = {}
    for p in (Path(public) / "meetings").glob("*/minutes.md"):
        meta, _ = _front(p.read_text(encoding="utf-8"))
        if meta.get("document_id"):
            out[meta["document_id"]] = p.parent.name
    return out


def _summary_body(text):
    """The summary text without front matter and without the leading AI-disclosure blockquote."""
    _, body = _front(text)
    lines = body.splitlines()
    while lines and (lines[0].startswith(">") or not lines[0].strip() or lines[0].startswith("# ")):
        lines.pop(0)
    return "\n".join(lines).strip()


def build_public(public_dir, out_path):
    public, out = Path(public_dir), Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    db = sqlite3.connect(out)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    folders = _folders(public)
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    counts = {"meetings": 0, "items": 0, "sensitive_items": 0, "summaries": 0, "skipped_archived": 0}
    for entry in index["documents"]:
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        if rec.get("origin"):
            counts["skipped_archived"] += 1     # no digest yet: names in the 2003-2008 layout are unchecked
            continue
        m = parse_meeting(rec)
        if not m["date"]:
            continue
        sensitive = sum(1 for it in m["items"] if it["sensitive"])
        db.execute("INSERT INTO meetings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (m["document_id"], m["date"], m["date_status"], m["title"], m["source_url"], m["source_sha256"],
                    m["version"], m["page_count"], len(m["items"]), sensitive, folders.get(m["document_id"])))
        counts["meetings"] += 1
        for n, it in enumerate(m["items"], start=1):
            body = "" if it["sensitive"] else it["text"]
            db.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (it["id"], m["document_id"], n, it["title"], json.dumps(it["topics"], ensure_ascii=False),
                        it["vote_result"], it["pages"][0], it["pages"][1], f"{m['source_url']}#page={it['pages'][0]}",
                        int(it["sensitive"]), json.dumps([] if it["sensitive"] else [
                            {k: a[k] for k in ("kind", "value", "raw", "sentence")} for a in it["amounts"]], ensure_ascii=False), body))
            counts["items"] += 1
            counts["sensitive_items"] += int(it["sensitive"])
            if not it["sensitive"]:
                db.execute("INSERT INTO search VALUES ('item', ?, 'fr', ?, ?)", (it["id"], it["title"], body))
        folder = folders.get(m["document_id"])
        for lang, name in (("fr", "summary.md"), ("en", "summary.en.md"), ("nl", "summary.nl.md")):
            path = public / "meetings" / (folder or "") / name
            if folder and path.exists():
                meta, _ = _front(path.read_text(encoding="utf-8"))
                body = _summary_body(path.read_text(encoding="utf-8"))
                if body and meta.get("produced_by", "").startswith("AI model"):
                    db.execute("INSERT INTO summaries VALUES (?,?,?,?,0)", (m["document_id"], lang, body, meta["produced_by"]))
                    db.execute("INSERT INTO search VALUES ('summary', ?, ?, ?, ?)", (m["document_id"], lang, f"{m['date']}", body))
                    counts["summaries"] += 1
    info = {"layer": "derived (names scrubbed, property sales as counts only)", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": json.dumps(counts), "ai_disclosure": disclosure.AI_PAGE_URL, "disclaimer": disclosure.text("rules", "en")}
    db.executemany("INSERT INTO build_info VALUES (?,?)", info.items())
    db.commit()
    db.close()
    return counts


def _fts_query(q):
    """Words only, each quoted, so user input can never act as an FTS5 operator; the last gets a prefix match."""
    words = re.findall(r"\w+", q[:MAX_QUERY_CHARS], re.UNICODE)[:12]
    if not words:
        return None
    return " ".join([f'"{w}"' for w in words[:-1]] + [f'"{words[-1]}"*'])


def search_public(db_path, q, limit=10, lang=None):
    """Matches for `q` as plain dicts with a highlighted snippet, newest meeting first among equal scores."""
    query = _fts_query(q or "")
    if not query:
        return []
    limit = max(1, min(int(limit), MAX_RESULTS))
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        sql = """
          SELECT s.kind, s.ref, s.lang, snippet(search, 4, '[', ']', '…', 24) AS snippet, bm25(search) AS score,
                 COALESCE(i.meeting_id, s.ref) AS meeting_id
          FROM search s LEFT JOIN items i ON s.kind = 'item' AND i.id = s.ref
          WHERE search MATCH ? {lang} ORDER BY score LIMIT ?"""
        args = [query] + ([lang] if lang else []) + [limit]
        rows = db.execute(sql.format(lang="AND s.lang = ?" if lang else ""), args).fetchall()
        out = []
        for r in rows:
            m = db.execute("SELECT date, source_url, folder FROM meetings WHERE id = ?", (r["meeting_id"],)).fetchone()
            item = db.execute("SELECT title, page_url FROM items WHERE id = ?", (r["ref"],)).fetchone() if r["kind"] == "item" else None
            out.append({"kind": r["kind"], "lang": r["lang"], "meeting_date": m["date"], "meeting_folder": m["folder"],
                        "title": item["title"] if item else f"Summary of the meeting of {m['date']} (written by an AI model)", "snippet": r["snippet"],
                        "original": item["page_url"] if item else m["source_url"],
                        "ai_written": r["kind"] == "summary"})
        return out
    finally:
        db.close()


def info(db_path):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return dict(db.execute("SELECT key, value FROM build_info").fetchall())
    finally:
        db.close()
