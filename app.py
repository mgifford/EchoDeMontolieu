"""Read-only API and landing page for L'Echo de Montolieu (Hugging Face Space).

Serves only published, already-public data: public/minutes (the faithful record
of the council minutes) and the pointer list in data/. It never reads private/.
There is deliberately no search or cross-document endpoint yet: aggregating
across documents is where people could be profiled, and that design comes next.
"""
import base64
import hashlib
import html
import json
import os
import re
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

DOC_ID_RE = re.compile(r"[0-9a-f]{12}")
REPO_URL = "https://github.com/mgifford/EchoDeMontolieu"

STYLE = """
:root{color-scheme:light}
body{margin:0;font:1rem/1.6 system-ui,-apple-system,sans-serif;background:#FBF9F5;color:#1A1A1A}
header{background:#004B87;color:#fff;padding:1rem 1.5rem}
header h1{margin:0;font-size:1.5rem}
main,footer{max-width:50rem;margin:0 auto;padding:1rem 1.5rem;overflow-wrap:anywhere}
a{color:#004B87}
a:focus-visible{outline:3px solid #005A9C;outline-offset:2px}
li{margin:.75rem 0}
.note{font-size:.95rem}
"""
STYLE_HASH = "sha256-" + base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
CSP = (f"default-src 'none'; style-src '{STYLE_HASH}'; base-uri 'none'; form-action 'none'")


class RateLimiter:
    """Sliding-window limiter, in memory. Resets when the process restarts."""

    def __init__(self, limit=30, window=60.0, clock=time.monotonic, max_keys=10_000):
        self.limit, self.window, self.clock, self.max_keys = limit, window, clock, max_keys
        self._hits = {}

    def check(self, key):
        """0 if allowed, otherwise seconds until the client may retry."""
        now = self.clock()
        if len(self._hits) > self.max_keys:
            self._hits = {k: q for k, q in self._hits.items() if q and q[-1] > now - self.window}
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(1, int(q[0] + self.window - now) + 1)
        q.append(now)
        return 0


def client_key(request, trust_proxy):
    """Client address. Behind a single trusted proxy the last X-Forwarded-For entry is
    the address that proxy saw; earlier entries are client-supplied. Off by default
    because the Hugging Face proxy chain has not been checked."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _https(url):
    return url if isinstance(url, str) and url.startswith("https://") else None


def _landing(index, pointers):
    e = html.escape
    docs = []
    for d in index.get("documents", []):
        when = (d.get("meeting_date") or {}).get("value")
        label = e(when) if when else "date not detected"
        name = e(d.get("filename") or d["document_id"])
        src = _https(d.get("source_url"))
        links = [f'<a href="{e(src)}" lang="fr">original PDF</a>'] if src else []
        links.append(f'<a href="/api/minutes/{e(d["document_id"])}">extracted text (JSON)</a>')
        flags = ""
        if d.get("ocr_pages"):
            flags = (f' OCR was used on {len(d["ocr_pages"])} page(s); '
                     f'{len(d.get("needs_review_pages", []))} need review.')
        docs.append(f"<li><strong>{label}</strong> <span lang=\"fr\">{name}</span>"
                    f"{' (draft suspected)' if d.get('draft_suspected') else ''}: "
                    f"{', '.join(links)}.{e(flags)}</li>")
    where = []
    for p in pointers.get("entries", []):
        url = _https(p.get("url"))
        if url:
            where.append(f'<li><a href="{e(url)}" lang="fr">{e(p["label_fr"])}</a> '
                         f'({e(p["label_en"])}), <span class="note">on '
                         f'{e(p.get("owner") or "the Mairie site")}; check there for current '
                         f"details.</span></li>")
    docs_html = "".join(docs) or "<li>No minutes have been published yet.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>L'Écho de Montolieu</title>
<meta name="description" content="Signposts and machine-extracted text of Montolieu council minutes, with links to the originals.">
<style>{STYLE}</style>
</head>
<body>
<header><h1>L'Écho de Montolieu</h1></header>
<main id="main">
<p>This project helps people find information about the village of Montolieu. It
points to the pages of the Mairie and other local sites and does not replace them.
Text from council minutes is machine-extracted, may contain errors, and is always
shown with a link to the original. Check the original before relying on anything.</p>
<h2>Council minutes</h2>
<ul>{docs_html}</ul>
<h2>Where to find things</h2>
<ul>{"".join(where)}</ul>
<p class="note">This page is in English only for now. The data is available as JSON at
<a href="/api/minutes">/api/minutes</a> and
<a href="/api/where-to-find">/api/where-to-find</a>.</p>
</main>
<footer><p class="note">Open source (AGPL-3.0):
<a href="{REPO_URL}">{REPO_URL}</a></p></footer>
</body>
</html>"""


def create_app(public_dir=None, data_dir=None, limiter=None, trust_proxy=None):
    public = Path(public_dir or os.environ.get("ECHO_PUBLIC_DIR", "public"))
    data = Path(data_dir or os.environ.get("ECHO_DATA_DIR", "data"))
    limiter = limiter or RateLimiter(int(os.environ.get("ECHO_RATE_LIMIT", "30")),
                                     float(os.environ.get("ECHO_RATE_WINDOW", "60")))
    if trust_proxy is None:
        trust_proxy = os.environ.get("ECHO_TRUST_PROXY") == "1"
    app = FastAPI(title="L'Écho de Montolieu", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path != "/health":
            wait = limiter.check(client_key(request, trust_proxy))
            if wait:
                return JSONResponse({"detail": "Too many requests"}, status_code=429,
                                    headers={"Retry-After": str(wait)})
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "public, max-age=300"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def landing():
        return _landing(_read_json(public / "index.json", {}),
                        _read_json(data / "where_to_find_mairie.json", {}))

    @app.get("/api/minutes")
    def minutes_index():
        return _read_json(public / "index.json", {"count": 0, "documents": []})

    @app.get("/api/minutes/{document_id}")
    def minutes_document(document_id: str):
        if not DOC_ID_RE.fullmatch(document_id):
            raise HTTPException(404, "Not found")
        doc = _read_json(public / "minutes" / f"{document_id}.json", None)
        if doc is None:
            raise HTTPException(404, "Not found")
        return doc

    @app.get("/api/where-to-find")
    def where_to_find():
        return _read_json(data / "where_to_find_mairie.json", {"entries": []})

    return app


app = create_app()
