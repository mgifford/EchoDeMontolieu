import json

from echo_montolieu.site import UI, build, is_french, mark_french, places_section


def test_french_titles_are_recognised_and_english_dutch_and_short_text_are_not():
    assert is_french("Approbation du proces verbal du conseil du 23 octobre 2024")
    assert is_french("Taux de la taxe d’aménagement")
    assert is_french("Mise en place d’une video protection en location")
    assert not is_french("Decisions and votes: the council of the commune")
    assert not is_french("Deze namen zijn met een patroon uit de notulen gehaald")
    assert not is_french("Budget") and not is_french("la carte")                 # under three words
    assert not is_french("cites: CGCT L.2122-21; CGCT L2122-22")


def test_only_text_without_its_own_language_is_marked():
    html = ('<p>Hello <a href="x">Convention de mise a disposition de terrain pour le SYADEN</a> (page 3)</p>'
            '<p lang="fr">Le conseil est pour les travaux</p><div lang="nl"><p>Le conseil est pour les travaux</p></div>'
            '<code>le la les des du</code><title>Le conseil pour les travaux</title>')
    out = mark_french(html)
    assert '<a href="x"><span lang="fr">Convention de mise a disposition de terrain pour le SYADEN</span></a>' in out
    assert out.count('<span lang="fr">') == 1                                        # the rest already had a language or is code or <title>


def test_the_places_section_carries_the_visitors_language_even_inside_french_minutes():
    found = {"confirmed": [{"label": "Rue X", "kind": "street", "pages": [(1, "https://example.org/a.pdf")], "osm": "https://osm.org/x"}], "unconfirmed": []}
    assert places_section("nl", found).startswith('<div lang="nl">')


def test_a_built_english_page_marks_the_french_titles_it_quotes(tmp_path):
    pub = tmp_path / "public"
    (pub / "finance").mkdir(parents=True)
    (pub / "index.json").write_text(json.dumps({"count": 0, "documents": []}), encoding="utf-8")
    (pub / "finance/index.md").write_text("---\nlanguage: en\n---\n# Finance\n\nItems:\n\n- 2025-03-06: Affectation d’un don au profit du CCAS\n- Total spent was high\n",
                                          encoding="utf-8")
    build(tmp_path / "out", pub, tmp_path / "none")
    for lang in ("en", "nl", "fr"):
        page = (tmp_path / "out" / lang / "finance/index.html").read_text(encoding="utf-8")
        assert '<span lang="fr">2025-03-06: Affectation d’un don au profit du CCAS</span>' in page, lang
        assert 'lang="fr">Total spent' not in page
    assert UI["en"]["nav"]


def test_a_trailing_note_in_the_pages_own_language_stays_outside_the_french_span():
    out = mark_french("<li>avenue du Mail (street): <a href='x'>link</a></li><li>); 2024-04-04: Transfert de propriete au profit de la commune des (</li>")
    assert '<span lang="fr">avenue du Mail</span> (street):' in out
    assert '); <span lang="fr">2024-04-04: Transfert de propriete au profit de la commune des</span> (' in out
