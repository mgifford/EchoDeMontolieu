import json
from pathlib import Path

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


def test_site_builder_needs_only_markdown_it_not_requests_or_the_pipeline(tmp_path):
    """The Pages workflow installs markdown-it-py alone; an import of anything heavier broke the deploy once."""
    import subprocess
    import sys
    code = ("import sys\n"
            "for name in ('requests', 'fitz', 'pytesseract', 'huggingface_hub', 'bs4', 'lxml', 'PIL', 'fastapi', 'mcp'):\n"
            "    sys.modules[name] = None\n"
            "from echo_montolieu.site import build\n"
            "print(build(sys.argv[1], 'public', 'data'))\n")
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path / "_site")], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert done.returncode == 0, done.stderr[-600:]


def test_map_is_published_in_each_language_with_the_site_navigation_and_old_links_still_work(tmp_path):
    public, data = tmp_path / "public", tmp_path / "data"
    (public / "places").mkdir(parents=True); data.mkdir()
    page = ("<!doctype html><html lang=\"{lang}\"><head><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
            "script-src 'sha256-s' https://unpkg.com; style-src 'sha256-x' https://unpkg.com\"><style>body{{}}</style></head><body>\n"
            "<a class=\"skip\" href=\"#list\">Skip {lang}</a>\n<header><h1>Places {lang}</h1></header>\n<main></main></body></html>")
    for lang, name in (("en", "map.html"), ("fr", "map.fr.html"), ("nl", "map.nl.html")):
        (public / "places" / name).write_text(page.format(lang=lang))
    out = build(tmp_path / "_site", public, data)
    for lang, label in (("en", ">Map<"), ("fr", ">Carte<"), ("nl", ">Kaart<")):
        text = (out / lang / "places" / "map.html").read_text()
        assert f"Places {lang}" in text and text.index(f"Skip {lang}") < text.index("<nav aria-label=") < text.index(f"<h1>Places {lang}</h1>")
        assert 'aria-current="page">' in text and label in text and "(English only)" not in text
        assert 'href="../whats-new/index.html"' in text and 'href="../index.html"' in text
        assert 'href="../../fr/places/map.html"' in text and 'href="../../nl/places/map.html"' in text and 'href="../../en/places/map.html"' in text
        assert 'href="../../assets/site.css"' in text and "style-src 'self' 'sha256-x'" in text and "script-src 'self' 'sha256-s'" in text
    old = (out / "places" / "map.html").read_text()                      # links that predate the languages still land somewhere useful
    assert 'url=../en/places/map.html' in old and all(f'href="../{c}/places/map.html"' in old for c in ("en", "fr", "nl"))
    for lang in ("en", "fr", "nl"):
        nav = (out / lang / "index.html").read_text()
        assert 'href="places/map.html"' in nav
