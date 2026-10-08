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

from echo_montolieu import disclosure
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

DOC_ID_RE = re.compile(r"[0-9a-f]{12}")
VERSION_RE = re.compile(r"[1-9][0-9]{0,2}")
REPO_URL = "https://github.com/mgifford/EchoDeMontolieu"
PAGES_URL = "https://mgifford.github.io/EchoDeMontolieu/"
GITHUB_TREE = REPO_URL + "/blob/main/public/"
PANNEAUPOCKET_URL = "https://app.panneaupocket.com/ville/922810321-montolieu-11170"

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
.ai{border-left:6px solid #6b6b6b;background:#F1EFEA;padding:.25rem 1rem;margin:1rem 0}
.sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
.alerts{background:#EBF3FA;border-left:6px solid #004B87;padding:.5rem 1rem;margin:1rem 0}
.alerts h2{margin:.25rem 0;font-size:1.1rem}
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


def _landing(index, pointers, static=False):
    """static=True gives relative links and a meta CSP, for hosting without a server (GitHub Pages)."""
    e = html.escape
    docs = []
    for d in index.get("documents", []):
        when = (d.get("meeting_date") or {}).get("value")
        label = e(when) if when else "date not detected"
        name = e(d.get("filename") or d["document_id"])
        src = _https(d.get("source_url"))
        about = f'<span class="sr"> of {label}</span>'  # makes repeated links distinguishable
        links = [f'<a href="{e(src)}" lang="fr">original PDF{about}</a>'] if src else []
        doc_href = (f"minutes/{e(d['document_id'])}.json" if static
                    else f"/api/minutes/{e(d['document_id'])}")
        links.append(f'<a href="{doc_href}">extracted text (JSON){about}</a>')
        flags = ""
        n = d.get("versions", 1)
        if n > 1:
            diff_href = (f"minutes/{e(d['document_id'])}/diff-v{n - 1}-v{n}.json" if static
                         else f"/api/minutes/{e(d['document_id'])}/diff/{n - 1}/{n}")
            links.append(f'<a href="{diff_href}">what changed in version {n}{about}</a>')
            flags += f" Revised by the Mairie: {n} versions are kept."
        if d.get("ocr_pages"):
            flags += (f' OCR was used on {len(d["ocr_pages"])} page(s); '
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
    map_href = "places/map.html" if static else PAGES_URL + "places/map.html"
    data_note = ('<a href="index.json">index.json</a> and '
                 '<a href="where_to_find_mairie.json">where_to_find_mairie.json</a>' if static else
                 '<a href="/api/minutes">/api/minutes</a> and '
                 '<a href="/api/where-to-find">/api/where-to-find</a>')
    meta_csp = (f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n' if static else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta_csp}<title>L'Écho de Montolieu</title>
<meta name="description" content="Signposts and machine-extracted text of Montolieu council minutes, with links to the originals.">
<style>{STYLE}</style>
</head>
<body>
<header><h1>L'Écho de Montolieu</h1></header>
<main id="main">
<section class="alerts" aria-labelledby="alerts-heading">
<h2 id="alerts-heading">Urgent alerts</h2>
<p>For urgent, real-time notices from the Mairie (water cuts, weather warnings, emergencies), use
<a href="{PANNEAUPOCKET_URL}">PanneauPocket Montolieu</a>, an external service. This site is not
updated in real time.</p>
</section>
{disclosure.html("site")}
<p>This project helps people find information about the village of Montolieu. It
points to the pages of the Mairie and other local sites and does not replace them.
Text from council minutes is machine-extracted, may contain errors, and is always
shown with a link to the original. Check the original before relying on anything.</p>
<h2>Explore</h2>
<ul>
<li><a href="{map_href}">Map and list of places discussed</a></li>
<li><a href="{GITHUB_TREE}topics/index.md">Issues over time</a>: what keeps coming back, and what may have been dropped</li>
<li><a href="{GITHUB_TREE}finance/index.md">Finance, rules and exceptions</a>, as far as the minutes state them</li>
<li><a href="{GITHUB_TREE}meetings/index.md">Each meeting</a>: the minutes in French, with summaries and follow-ups</li>
</ul>
<p class="note">The last three open on GitHub, where Markdown is displayed as a page.</p>
<h2>Council minutes</h2>
<ul>{docs_html}</ul>
<h2>Where to find things</h2>
<ul>{"".join(where)}</ul>
<p class="note">This page is in English only for now. The data is available as JSON: {data_note}.</p>
</main>
<footer><p class="note">Open source (AGPL-3.0):
<a href="{REPO_URL}">{REPO_URL}</a>. <a href="{disclosure.AI_PAGE_URL}">About AI in this project</a>.</p></footer>
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

    @app.get("/api/minutes/{document_id}/versions/{version}")
    def minutes_version(document_id: str, version: str):
        if not (DOC_ID_RE.fullmatch(document_id) and VERSION_RE.fullmatch(version)):
            raise HTTPException(404, "Not found")
        doc = _read_json(public / "minutes" / document_id / f"v{version}.json", None)
        if doc is None:  # the current version lives in the main file
            current = _read_json(public / "minutes" / f"{document_id}.json", None)
            doc = current if current and str(current.get("version")) == version else None
        if doc is None:
            raise HTTPException(404, "Not found")
        return doc

    @app.get("/api/minutes/{document_id}/diff/{from_version}/{to_version}")
    def minutes_diff(document_id: str, from_version: str, to_version: str):
        if not (DOC_ID_RE.fullmatch(document_id) and VERSION_RE.fullmatch(from_version)
                and VERSION_RE.fullmatch(to_version)):
            raise HTTPException(404, "Not found")
        diff = _read_json(public / "minutes" / document_id
                          / f"diff-v{from_version}-v{to_version}.json", None)
        if diff is None:
            raise HTTPException(404, "Not found")
        return diff

    @app.get("/api/where-to-find")
    def where_to_find():
        return _read_json(data / "where_to_find_mairie.json", {"entries": []})

    return app


app = create_app()
