import json

from echo_montolieu import resources
from echo_montolieu.site import build


def data(tmp_path, entries=None):
    f = tmp_path / "resources.json"
    f.write_text(json.dumps({"entries": entries if entries is not None else [
        {"id": "a", "url": "https://example.gouv.fr/", "title": {"fr": "T fr", "en": "T en", "nl": "T nl"}, "about": {"fr": "A fr", "en": "A en", "nl": "A nl"}},
        {"id": "bad", "url": "http://insecure.example/", "title": {"fr": "x", "en": "x", "nl": "x"}, "about": {"fr": "x", "en": "x", "nl": "x"}}]}), encoding="utf-8")
    return f


def test_pages_in_three_languages_list_only_https_links_and_say_they_do_not_use_the_minutes(tmp_path):
    info = resources.write(tmp_path / "public", data(tmp_path), "2026-10-10")
    assert info == {"links": 1}
    en = (tmp_path / "public/resources/index.en.md").read_text(encoding="utf-8")
    assert "[T en](https://example.gouv.fr/): A en" in en and "insecure" not in en and "does not use the minutes" in en and "AI disclosure" in en
    fr = (tmp_path / "public/resources/index.md").read_text(encoding="utf-8")
    assert "language: fr" in fr and "[T fr](https://example.gouv.fr/)" in fr and "état des risques et pollutions" in fr
    assert "# Lokale risico" in (tmp_path / "public/resources/index.nl.md").read_text(encoding="utf-8")


def test_the_real_list_has_a_title_and_a_sentence_in_every_language():
    for e in resources.load("data/resources.json"):
        for lang in ("fr", "en", "nl"):
            assert e["title"][lang].strip() and e["about"][lang].strip() and e["url"].startswith("https://")


def test_the_home_page_links_to_the_page_in_every_language_when_it_exists(tmp_path):
    pub = tmp_path / "public"
    pub.mkdir()
    (pub / "index.json").write_text(json.dumps({"count": 0, "documents": []}), encoding="utf-8")
    build(tmp_path / "a", pub, tmp_path / "none")
    assert "resources/index.html" not in (tmp_path / "a/en/index.html").read_text(encoding="utf-8")
    resources.write(pub, data(tmp_path))
    build(tmp_path / "b", pub, tmp_path / "none")
    for lang in ("fr", "en", "nl"):
        assert 'href="resources/index.html"' in (tmp_path / "b" / lang / "index.html").read_text(encoding="utf-8"), lang
    assert "T nl" in (tmp_path / "b/nl/resources/index.html").read_text(encoding="utf-8")
