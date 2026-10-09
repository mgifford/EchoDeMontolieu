"""A read-only MCP server over the public, derived database.

It answers questions about the council minutes for AI assistants, with the same guardrails as
`/api/search`: it opens only `data/echo.db` (names scrubbed, property sales as counts), read-only,
clamps every input, and never reads the faithful text, `private/`, the network or the file system.
Everything it returns says that the text is machine-extracted or AI-written and links to the original.
"""
import json
import re
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import db as database
from . import disclosure

SITE_URL = "https://mgifford.github.io/EchoDeMontolieu/"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_ITEMS = 60
INSTRUCTIONS = (
    "Read-only access to the council minutes of Montolieu (Aude, France), 2003-2008 and 2024 onwards where "
    "available. Text is machine-extracted and summaries are written by AI models; none of it is checked by a "
    "person. Always cite the original link returned with each result and tell the user to check it. Names are "
    "scrubbed and private property sales appear only as counts. Minutes for 2009-2023 were not found. "
    "This is not legal advice.")


def _connect(db_path):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _meeting_page(row, lang):
    return f"{SITE_URL}{lang}/meetings/{row['folder']}/summary.html" if row["folder"] else None


def build_server(db_path, allowed_hosts=()):
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *allowed_hosts]
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                         allowed_origins=[f"https://{h}" for h in allowed_hosts] + ["http://127.0.0.1:*", "http://localhost:*"])
    mcp = FastMCP("L'Écho de Montolieu", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
                  streamable_http_path="/mcp", transport_security=security)
    notice = {"ai_disclosure": disclosure.AI_PAGE_URL, "disclaimer": disclosure.text("rules", "en")}

    @mcp.tool()
    def search_minutes(query: str, limit: int = 10, lang: str | None = None) -> dict:
        """Search the scrubbed text of the council minutes and the AI-written summaries.

        `lang` (fr, en or nl) limits the search to summaries in that language; minutes text is French.
        Each result has the meeting date, a snippet and a link to the original document."""
        if lang not in (None, "fr", "en", "nl"):
            raise ValueError("lang must be fr, en or nl")
        if len(query) > database.MAX_QUERY_CHARS:
            raise ValueError(f"query longer than {database.MAX_QUERY_CHARS} characters")
        return {"query": query, "results": database.search_public(db_path, query, limit, lang),
                "layer": "derived: names scrubbed, property sales not searchable", **notice}

    @mcp.tool()
    def list_meetings() -> dict:
        """Every meeting in the database, newest first: date, item and vote counts, link to the original."""
        db = _connect(db_path)
        try:
            rows = db.execute("SELECT id, date, source_url, items, sensitive_items, folder FROM meetings ORDER BY date DESC").fetchall()
        finally:
            db.close()
        return {"meetings": [{"date": r["date"], "items": r["items"], "private_property_sales": r["sensitive_items"],
                              "original": r["source_url"], "site_page": _meeting_page(r, "en")} for r in rows],
                "note": "2003-2008 minutes are on the website but not in this database yet; none were found for 2009-2023.", **notice}

    @mcp.tool()
    def get_meeting_summary(date: str, lang: str = "en") -> dict:
        """The AI-written summary of the meeting on `date` (YYYY-MM-DD) in fr, en or nl, when one exists."""
        if not DATE_RE.fullmatch(date):
            raise ValueError("date must look like 2025-06-24")
        if lang not in ("fr", "en", "nl"):
            raise ValueError("lang must be fr, en or nl")
        db = _connect(db_path)
        try:
            m = db.execute("SELECT id, source_url, folder FROM meetings WHERE date = ?", (date,)).fetchone()
            if not m:
                return {"found": False, "message": f"No meeting dated {date} in the database.", **notice}
            s = db.execute("SELECT body, produced_by, human_reviewed FROM summaries WHERE meeting_id = ? AND lang = ?",
                           (m["id"], lang)).fetchone()
        finally:
            db.close()
        if not s:
            return {"found": False, "message": f"No {lang} summary for {date} yet.", "original": m["source_url"], **notice}
        return {"found": True, "date": date, "lang": lang, "summary": s["body"], "written_by": s["produced_by"],
                "human_reviewed": bool(s["human_reviewed"]), "original": m["source_url"],
                "site_page": _meeting_page(m, lang), **notice}

    @mcp.tool()
    def get_meeting_items(date: str) -> dict:
        """The agenda items of the meeting on `date` with vote result, pages and a link to each page of the original.
        Private property sales appear as a neutral title only."""
        if not DATE_RE.fullmatch(date):
            raise ValueError("date must look like 2025-06-24")
        db = _connect(db_path)
        try:
            m = db.execute("SELECT id, source_url FROM meetings WHERE date = ?", (date,)).fetchone()
            if not m:
                return {"found": False, "message": f"No meeting dated {date} in the database.", **notice}
            rows = db.execute("SELECT ordinal, title, vote_result, first_page, last_page, page_url, sensitive, topics "
                              "FROM items WHERE meeting_id = ? ORDER BY ordinal LIMIT ?", (m["id"], MAX_ITEMS)).fetchall()
        finally:
            db.close()
        return {"found": True, "date": date, "original": m["source_url"], "items": [
            {"n": r["ordinal"], "title": r["title"], "vote": r["vote_result"], "pages": [r["first_page"], r["last_page"]],
             "original_page": r["page_url"], "private_property_sale": bool(r["sensitive"]), "topics": json.loads(r["topics"])}
            for r in rows], **notice}

    return mcp


def allowed_hosts_from(environ):
    raw = environ.get("ECHO_MCP_HOSTS", "mgifford-echodemontolieu.hf.space")
    return [h.strip() for h in raw.split(",") if h.strip()]
