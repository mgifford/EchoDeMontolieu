import re
from pathlib import Path

import pytest

from echo_montolieu import site
from echo_montolieu.site import LANGS, build, render_markdown

ROOT = Path(__file__).resolve().parent.parent


def _meeting(public, folder, fr=None, en=None, nl=None, doc_id="abababababab"):
    d = public / "meetings" / folder
    d.mkdir(parents=True, exist_ok=True)
    front = f"---\ntitle: x\ndocument_id: {doc_id}\nlanguage: {{}}\n---\n"
    for suffix, lang, text in (("", "fr", fr), (".en", "en", en), (".nl", "nl", nl)):
        if text:
            (d / f"minutes{suffix}.md").write_text(front.format(lang) + text)


def _site(tmp_path, **texts):
    public, data = tmp_path / "public", tmp_path / "data"
    public.mkdir(); data.mkdir()
    _meeting(public, "2024-09-18", **texts)
    return build(tmp_path / "_site", public, data)


def test_every_page_exists_in_all_three_languages_with_navigation_and_a_language_switcher(tmp_path):
    out = _site(tmp_path, fr="# Procès-verbal\n\nTexte.\n")
    for lang in LANGS:
        page = (out / lang / "meetings" / "2024-09-18" / "minutes.html").read_text()
        assert f'<html lang="{lang}">' in page and 'class="skip"' in page and '<main id="main"' in page
        assert page.count('<nav aria-label=') == 2                        # main navigation and language switcher
        assert page.count('data-setlang=') == 3 and page.count('hreflang="x-default"') == 1
        for other in LANGS:                                               # the switcher points at the same page
            assert f'href="../../../{other}/meetings/2024-09-18/minutes.html"' in page
        assert page.count('aria-current="true"') == 1
        assert "AI disclosure." in page or "Information sur l’IA." in page or "Informatie over AI." in page


def test_a_missing_translation_falls_back_with_a_visible_notice_and_the_right_language_mark(tmp_path):
    out = _site(tmp_path, fr="# Procès-verbal\n\nTexte français.\n")
    en = (out / "en/meetings/2024-09-18/minutes.html").read_text()
    assert 'class="notice"' in en and "not available in English yet" in en and "shown in French" in en
    assert '<div lang="fr">' in en and "Texte français" in en
    nl = (out / "nl/meetings/2024-09-18/minutes.html").read_text()
    assert "nog niet beschikbaar in het Nederlands" in nl and '<div lang="fr">' in nl
    fr = (out / "fr/meetings/2024-09-18/minutes.html").read_text()
    assert 'class="notice"' not in fr and '<div lang=' not in fr


def test_a_translation_is_used_when_it_exists_and_only_for_its_language(tmp_path):
    out = _site(tmp_path, fr="# Procès-verbal\n\nTexte.\n", en="# Minutes\n\nEnglish text.\n")
    en = (out / "en/meetings/2024-09-18/minutes.html").read_text()
    assert "English text." in en and 'class="notice"' not in en and "<title>Minutes" in en
    assert "Texte." in (out / "nl/meetings/2024-09-18/minutes.html").read_text()      # Dutch still falls back


def test_markdown_never_lets_raw_html_or_script_links_through():
    out = render_markdown("# T\n\n<script>alert(1)</script> and [x](javascript:alert(1)) and <b>bold</b>\n", "Table")
    assert "<script>" not in out and "<b>" not in out and 'href="javascript' not in out
    assert "&lt;script&gt;" in out


def test_md_links_become_html_links_and_headings_get_the_ids_the_contents_list_uses():
    out = render_markdown("- [a](minutes.md) [b](../topics/x-2024.md#top) [c](minutes.en.md) [d](https://e.test/x.md)\n\n"
                          "## Agricole du midi.\n\n## Agricole du midi.\n\n[t](#agricole-du-midi)\n", "Table")
    assert 'href="minutes.html"' in out and 'href="../topics/x-2024.html#top"' in out
    assert out.count('href="minutes.html"') == 2 and 'href="https://e.test/x.md"' in out
    assert 'id="agricole-du-midi"' in out and 'id="agricole-du-midi-1"' in out


def test_tables_scroll_in_a_labelled_focusable_region_with_column_headers():
    out = render_markdown("| A | B |\n|---|---|\n| 1 | 2 |\n", "Tableau")
    assert 'role="region" aria-label="Tableau 1" tabindex="0"' in out and '<th scope="col">A</th>' in out


def test_translation_links_in_the_meetings_table_are_dropped_because_each_language_has_its_own_tree(tmp_path):
    public, data = tmp_path / "public", tmp_path / "data"
    (public / "meetings").mkdir(parents=True); data.mkdir()
    (public / "meetings" / "index.md").write_text("# Council meetings\n\n| Read |\n|---|\n| [minutes](d/minutes.md) · [minutes EN](d/minutes.en.md) |\n")
    out = build(tmp_path / "_site", public, data)
    page = (out / "en/meetings/index.html").read_text()
    assert "minutes EN" not in page and 'href="d/minutes.html"' in page


def test_landing_groups_by_year_in_each_language_with_proper_plurals(tmp_path):
    public, data = tmp_path / "public", tmp_path / "data"
    public.mkdir(); data.mkdir()
    docs = [{"document_id": f"{i:012x}", "filename": f"f{i}.pdf", "source_url": "https://www.montolieu.fr/x.pdf",
             "meeting_date": {"value": d}, "versions": 1} for i, d in enumerate(["2026-07-22", "2026-06-05", "2024-01-31", "2003-04-04"])]
    import json
    (public / "index.json").write_text(json.dumps({"documents": docs}))
    out = build(tmp_path / "_site", public, data)
    assert "4 sets of minutes across 3 years (2003–2026)" in (out / "en/index.html").read_text()
    assert "2026: 2 sets of minutes" in (out / "en/index.html").read_text() and "2024: 1 set of minutes" in (out / "en/index.html").read_text()
    fr = (out / "fr/index.html").read_text()
    assert "4 procès-verbaux sur 3 années (2003–2026)" in fr and "2026 : 2 procès-verbaux" in fr and "2024 : 1 procès-verbal" in fr
    assert "Aucun procès-verbal trouvé pour : 2004–2023" in fr
    assert "4 sets notulen uit 3 jaar" in (out / "nl/index.html").read_text()


def test_chooser_sends_visitors_with_a_saved_or_browser_language_and_stays_usable_without_script(tmp_path):
    out = _site(tmp_path, fr="# P\n")
    root = (out / "index.html").read_text()
    assert "data-chooser" in root and all(f'href="{c}/"' in root for c in LANGS)
    js = (out / "assets/site.js").read_text()
    assert "navigator.languages" in js and "localStorage" in js and "location.replace" in js and site.KEY in js
    assert "script-src 'self'" in root and "unsafe-inline" not in root


def _check_links(out):
    """Every relative href/src in the built site resolves to a file, and every #fragment to an id on that page."""
    problems, ids_cache = [], {}
    for page in Path(out).rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for attr, ref in re.findall(r'(href|src)="([^"]*)"', text):
            if re.match(r"^(https?:|mailto:|data:)", ref) or not ref:
                continue
            path, _, frag = ref.partition("#")
            target = (page.parent / path).resolve() if path else page
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                problems.append(f"{page.relative_to(out)} -> {ref} (missing file)")
                continue
            if frag and target.suffix == ".html":
                ids = ids_cache.setdefault(target, set(re.findall(r'id="([^"]+)"', target.read_text(encoding="utf-8"))))
                if frag not in ids:
                    problems.append(f"{page.relative_to(out)} -> {ref} (missing id)")
    return problems


def test_the_real_site_has_no_broken_internal_links_or_anchors(tmp_path):
    if not (ROOT / "public" / "index.json").exists():
        pytest.skip("no published data")
    out = build(tmp_path / "_site", ROOT / "public", ROOT / "data")
    problems = _check_links(out)
    assert not problems, "\n".join(problems[:20])
    assert len(list(out.rglob("*.html"))) > 100


def test_heading_ids_ignore_the_trailing_page_mark_so_contents_links_work():
    out = render_markdown("- [Budget](#budget)\n\n## Budget [p.6](https://e.test/a.pdf#page=6)\n", "Table")
    assert 'id="budget"' in out


def test_map_link_in_the_places_list_points_at_the_shared_map():
    assert 'href="../../places/map.html"' in render_markdown("[map](map.html)\n", "Table", root="../../")


def test_two_tables_on_one_page_get_different_region_names():
    out = render_markdown("| A |\n|---|\n| 1 |\n\ntext\n\n| B |\n|---|\n| 2 |\n", "Table")
    assert 'aria-label="Table 1"' in out and 'aria-label="Table 2"' in out
