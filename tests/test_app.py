import json
import re

import pytest
from fastapi.testclient import TestClient

from app import STYLE, RateLimiter, create_app

DOC_ID = "abababababab"
RECORD = {"document_id": DOC_ID, "source_url": "https://example.test/a.pdf",
          "pages": [{"page": 1, "text": "Séance <script>alert(1)</script>"}]}
INDEX = {"count": 1, "documents": [{
    "document_id": DOC_ID, "filename": "A <b>x</b>.pdf", "source_url": "https://example.test/a.pdf",
    "meeting_date": {"value": "2024-09-18"}, "draft_suspected": True,
    "ocr_pages": [2], "needs_review_pages": [2], "version": 2, "versions": 2}]}
POINTERS = {"entries": [
    {"label_fr": "Agenda", "label_en": "Events calendar", "url": "https://www.montolieu.fr/agenda/"},
    {"label_fr": "Piège", "label_en": "x", "url": "javascript:alert(1)"}]}


@pytest.fixture
def client(tmp_path):
    public, data = tmp_path / "public", tmp_path / "data"
    (public / "minutes").mkdir(parents=True)
    data.mkdir()
    (public / "index.json").write_text(json.dumps(INDEX), encoding="utf-8")
    (public / "minutes" / f"{DOC_ID}.json").write_text(
        json.dumps({**RECORD, "version": 2}), encoding="utf-8")
    (public / "minutes" / DOC_ID).mkdir()
    (public / "minutes" / DOC_ID / "v1.json").write_text(
        json.dumps({**RECORD, "version": 1}), encoding="utf-8")
    (public / "minutes" / DOC_ID / "diff-v1-v2.json").write_text(
        json.dumps({"from_version": 1, "to_version": 2}), encoding="utf-8")
    (data / "where_to_find_mairie.json").write_text(json.dumps(POINTERS), encoding="utf-8")
    # A private folder next to public must never be reachable.
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "people.json").write_text('{"M-1": {"names_seen": ["SECRET"]}}')
    return TestClient(create_app(public, data, RateLimiter(limit=1000)))


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_api_serves_index_document_and_pointers(client):
    assert client.get("/api/minutes").json()["count"] == 1
    assert client.get(f"/api/minutes/{DOC_ID}").json()["document_id"] == DOC_ID
    assert client.get("/api/where-to-find").json()["entries"][0]["label_fr"] == "Agenda"
    assert "max-age" in client.get("/api/minutes").headers["cache-control"]


@pytest.mark.parametrize("bad", ["../private/people", "..%2Fprivate%2Fpeople", "ABABABABABAB",
                                 "abababababab.json", "abab", "0" * 12, "%2e%2e"])
def test_document_ids_are_validated_and_traversal_is_blocked(client, bad):
    r = client.get(f"/api/minutes/{bad}")
    assert r.status_code == 404 and "SECRET" not in r.text


def test_private_data_is_not_served_anywhere(client):
    for path in ("/", "/api/minutes", "/private/people.json", "/people.json", "/docs",
                 "/openapi.json"):
        assert "SECRET" not in client.get(path).text


def test_landing_page_escapes_content_and_drops_non_https_links(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "<b>x</b>" not in body and "A &lt;b&gt;x&lt;/b&gt;.pdf" in body
    assert "javascript:" not in body and "https://www.montolieu.fr/agenda/" in body
    assert '<html lang="en">' in body and "<title>" in body and "<h1>" in body
    assert "draft suspected" in body and "OCR was used on 1 page" in body
    assert re.search(r'<a href="https://example.test/a.pdf" lang="fr">', body)


def test_security_headers_and_csp_hash_matches_the_inline_style(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp
    import base64
    import hashlib
    h = base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
    assert f"'sha256-{h}'" in csp and f"<style>{STYLE}</style>" in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors" not in csp  # Spaces embed the app in an iframe


def test_empty_data_still_renders(tmp_path):
    c = TestClient(create_app(tmp_path / "nope", tmp_path / "nada", RateLimiter(limit=1000)))
    assert "No minutes have been published yet" in c.get("/").text
    assert c.get("/api/minutes").json() == {"count": 0, "documents": []}
    assert c.get(f"/api/minutes/{DOC_ID}").status_code == 404


def test_rate_limit_returns_429_with_retry_after_but_not_for_health(tmp_path):
    c = TestClient(create_app(tmp_path, tmp_path, RateLimiter(limit=3, window=60)))
    assert [c.get("/api/minutes").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/api/minutes")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert c.get("/health").status_code == 200


def test_rate_limiter_window_expires_and_keys_are_independent():
    t = [0.0]
    lim = RateLimiter(limit=2, window=10, clock=lambda: t[0])
    assert lim.check("a") == 0 and lim.check("a") == 0 and lim.check("a") > 0
    assert lim.check("b") == 0
    t[0] = 11
    assert lim.check("a") == 0


def test_forwarded_header_is_ignored_unless_proxy_is_trusted(tmp_path):
    def hits(trust):
        c = TestClient(create_app(tmp_path, tmp_path, RateLimiter(limit=1), trust_proxy=trust))
        a = c.get("/api/minutes", headers={"x-forwarded-for": "1.1.1.1, 9.9.9.1"}).status_code
        b = c.get("/api/minutes", headers={"x-forwarded-for": "1.1.1.1, 9.9.9.2"}).status_code
        return a, b
    assert hits(False) == (200, 429)   # spoofing the leading entry gains nothing
    assert hits(True) == (200, 200)    # trusted: last entry is the address the proxy saw


def test_no_search_or_aggregate_endpoint_exists(client):
    for path in ("/api/search?q=durant", "/api/people", "/api/minutes/search"):
        assert client.get(path).status_code == 404


def test_old_versions_current_version_and_diffs_are_served(client):
    assert client.get(f"/api/minutes/{DOC_ID}/versions/1").json()["version"] == 1
    assert client.get(f"/api/minutes/{DOC_ID}/versions/2").json()["version"] == 2  # current
    assert client.get(f"/api/minutes/{DOC_ID}/diff/1/2").json()["to_version"] == 2
    for bad in ("/versions/3", "/versions/0", "/versions/01", "/versions/1.json",
                "/versions/../../private/people", "/diff/1/3", "/diff/2/1", "/diff/x/2",
                "/diff/1/2/3"):
        r = client.get(f"/api/minutes/{DOC_ID}{bad}")
        assert r.status_code == 404 and "SECRET" not in r.text
    assert client.get("/api/minutes/zzzzzzzzzzzz/versions/1").status_code == 404


def test_landing_page_says_when_a_document_was_revised_and_links_the_diff(client):
    body = client.get("/").text
    assert "Revised by the Mairie: 2 versions are kept." in body
    assert "OCR was used on 1 page" in body   # the revision note must not replace the OCR note
    assert f'href="/api/minutes/{DOC_ID}/diff/1/2"' in body


def test_landing_page_links_the_live_alerts_service_in_a_labelled_region(client):
    body = client.get("/").text
    assert 'href="https://app.panneaupocket.com/ville/922810321-montolieu-11170"' in body
    assert 'aria-labelledby="alerts-heading"' in body and 'id="alerts-heading"' in body
    assert body.index("alerts-heading") < body.index("Council minutes")      # near the top
    assert "not updated in real time" in " ".join(body.split())              # sets expectations


def test_repeated_links_say_which_meeting_they_belong_to_for_screen_readers(client):
    body = client.get("/").text
    assert 'original PDF<span class="sr"> of 2024-09-18</span>' in body
    assert 'extracted text (JSON)<span class="sr"> of 2024-09-18</span>' in body
    assert ".sr{position:absolute" in body                     # the visually-hidden style is defined


def test_landing_page_has_an_explore_section_with_the_map_and_the_markdown_pages(client):
    body = client.get("/").text
    assert "<h2>Explore</h2>" in body and "Map and list of places discussed" in body
    assert 'href="https://mgifford.github.io/EchoDeMontolieu/places/map.html"' in body       # the Space points to Pages
    for page in ("topics/index.md", "finance/index.md", "meetings/index.md"):
        assert f'href="https://github.com/mgifford/EchoDeMontolieu/blob/main/public/{page}"' in body


def test_landing_page_carries_the_ai_disclosure_near_the_top_and_in_the_footer(client):
    body = client.get("/").text
    flat = " ".join(body.split())
    assert "AI disclosure." in flat and "written with AI assistance" in flat and "No person has checked every page" in flat
    assert body.index('class="ai"') < body.index("<h2>Explore</h2>")           # before the content, not buried
    assert body.count("blob/main/AI.md") == 2                                   # in the notice and in the footer


def test_landing_groups_minutes_by_year_with_counts_and_names_the_missing_years():
    from app import _landing
    docs = [{"document_id": f"{i:012x}", "filename": f"f{i}.pdf", "source_url": "https://www.montolieu.fr/x.pdf",
             "meeting_date": {"value": d}, "versions": 1} for i, d in enumerate(["2026-07-22", "2026-06-05", "2024-01-31", "2008-05-09"])]
    docs.append({"document_id": "f" * 12, "filename": "old.html", "source_url": "https://web.archive.org/web/1/http://x/old.html",
                 "meeting_date": {"value": "2003-04-04"}, "versions": 1})
    page = _landing({"documents": docs}, {"entries": []}, static=True)
    assert "5 sets of minutes across 4 years (2003 to 2026)" in page
    assert page.index("2026: 2 sets of minutes") < page.index("2024: 1 set of minutes") < page.index("2008: 1 set of minutes")
    assert "No minutes found for: 2004 to 2007; 2009 to 2023; 2025." in page
    assert "Internet Archive copy" in page and page.count("original PDF") == 4
    assert "<h3" in page and page.index("<h2>Council minutes</h2>") < page.index("<h3")
