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
    "ocr_pages": [2], "needs_review_pages": [2]}]}
POINTERS = {"entries": [
    {"label_fr": "Agenda", "label_en": "Events calendar", "url": "https://www.montolieu.fr/agenda/"},
    {"label_fr": "Piège", "label_en": "x", "url": "javascript:alert(1)"}]}


@pytest.fixture
def client(tmp_path):
    public, data = tmp_path / "public", tmp_path / "data"
    (public / "minutes").mkdir(parents=True)
    data.mkdir()
    (public / "index.json").write_text(json.dumps(INDEX), encoding="utf-8")
    (public / "minutes" / f"{DOC_ID}.json").write_text(json.dumps(RECORD), encoding="utf-8")
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
