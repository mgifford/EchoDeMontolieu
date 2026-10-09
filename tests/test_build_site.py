import json

from echo_montolieu.site import build

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
    (public / "redacted" / "secret.md").write_text("# Redacted page\n")
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
    assert files == [".nojekyll", "assets/site.css", "assets/site.js", "en/index.html", "en/meetings/index.html",
                     "fr/index.html", "fr/meetings/index.html", "index.html",
                     "index.json", "minutes/abababababab.json", "minutes/abababababab/diff-v1-v2.json",
                     "nl/index.html", "nl/meetings/index.html", "where_to_find_mairie.json"]
    (public / "places").mkdir()
    for name in ("map.html", "places.json"):
        (public / "places" / name).write_text(name)
    out = build(tmp_path / "_site2", public, data)
    assert (out / "places" / "map.html").exists() and (out / "places" / "places.json").exists()
    assert "SECRET" not in "".join(p.read_text() for p in out.rglob("*") if p.is_file())
    assert not (out / "redacted").exists() and "Redacted page" not in "".join(p.read_text() for p in out.rglob("*.html"))
