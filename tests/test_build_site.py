import json

from build_site import build

INDEX = {"count": 1, "documents": [{
    "document_id": "abababababab", "filename": "A.pdf", "source_url": "https://example.test/a.pdf",
    "meeting_date": {"value": "2024-09-18"}, "version": 2, "versions": 2,
    "ocr_pages": [], "needs_review_pages": []}]}


def make(tmp_path):
    public, data = tmp_path / "public", tmp_path / "data"
    (public / "minutes" / "abababababab").mkdir(parents=True)
    (public / "redacted" / "minutes").mkdir(parents=True)
    (public / "index.json").write_text(json.dumps(INDEX))
    (public / "minutes" / "abababababab.json").write_text('{"ok": 1}')
    (public / "minutes" / "abababababab" / "diff-v1-v2.json").write_text('{"d": 1}')
    (public / "redacted" / "minutes" / "x.json").write_text('{"pseudonymised": 1}')
    data.mkdir()
    (data / "where_to_find_mairie.json").write_text(json.dumps({"entries": [
        {"label_fr": "Agenda", "label_en": "Events", "url": "https://www.montolieu.fr/agenda/"}]}))
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "people.json").write_text('{"SECRET": 1}')
    return public, data


def test_site_contains_only_published_data(tmp_path):
    public, data = make(tmp_path)
    out = build(tmp_path / "_site", public, data)
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert files == [".nojekyll", "index.html", "index.json", "minutes/abababababab.json",
                     "minutes/abababababab/diff-v1-v2.json", "where_to_find_mairie.json"]
    assert "SECRET" not in "".join(p.read_text() for p in out.rglob("*") if p.is_file())
    assert not (out / "redacted").exists()          # pseudonymised data is not published here


def test_static_page_uses_relative_links_that_resolve_to_built_files(tmp_path):
    public, data = make(tmp_path)
    out = build(tmp_path / "_site", public, data)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="/api/' not in html and 'href="/' not in html.replace('href="//', "")
    for href in ("minutes/abababababab.json", "minutes/abababababab/diff-v1-v2.json",
                 "index.json", "where_to_find_mairie.json"):
        assert f'href="{href}"' in html and (out / href).exists()


def test_static_page_carries_a_meta_csp_and_rebuilding_cleans_old_files(tmp_path):
    public, data = make(tmp_path)
    out = build(tmp_path / "_site", public, data)
    assert 'http-equiv="Content-Security-Policy"' in (out / "index.html").read_text()
    (out / "stale.txt").write_text("x")
    build(out, public, data)
    assert not (out / "stale.txt").exists()


def test_empty_public_folder_still_builds(tmp_path):
    out = build(tmp_path / "_site", tmp_path / "nope", tmp_path / "nada")
    assert "No minutes have been published yet" in (out / "index.html").read_text()
