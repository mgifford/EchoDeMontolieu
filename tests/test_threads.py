import json

from echo_montolieu import threads as th
from echo_montolieu.signals import find_followups

URL = "https://example.test/{}.pdf"


def item(n, date, title, text, followups=(), sensitive=False, topics=("finances",), amounts=()):
    return {"id": f"{date}-{n:02d}", "title": title, "title_key": th._fold(title).replace("'", " "),
            "pages": [n, n], "topics": list(topics), "vote_result": "unanimous", "votes": [],
            "sensitive": sensitive, "amounts": [{"kind": "eur", "value": v, "raw": "", "sentence": ""} for v in amounts],
            "legal_refs": [], "exceptions": [], "followups": [{"type": t, "sentence": s} for t, s in followups],
            "places": [], "snippet": text[:80], "text": "" if sensitive else text}


def meeting(date, items, tokens=()):
    return {"meeting": {"date": date, "source_url": URL.format(date), "items": items, "page_count": 5},
            "folder": date, "name_tokens": set(tokens)}


TRESO = "Renouvellement de la ligne de trésorerie auprès de la banque pour le financement des besoins courants de la commune"
PLU = "Le PLU et son règlement : le PLU est étudié, les zones et les OAP sont discutées avec le bureau d'études"


def sample():
    return [
        meeting("2024-01-10", [item(1, "2024-01-10", "Ligne de trésorerie", TRESO, amounts=(300000,)),
                               item(2, "2024-01-10", "Approbation du PV du 1er décembre", "Le procès-verbal est approuvé.", ),
                               item(3, "2024-01-10", "Droits de préemption", "x", sensitive=True)]),
        meeting("2024-03-10", [item(1, "2024-03-10", "Renouvellement ligne de trésorerie", TRESO + " pour 2024", amounts=(250000,)),
                               item(2, "2024-03-10", "Règlement du PLU", PLU, followups=(("deferred", "Le point sera revu au prochain conseil."),))]),
        meeting("2024-05-10", [item(1, "2024-05-10", "Subvention aux associations", "Les associations sportives reçoivent une subvention pour la saison."),
                               item(2, "2024-05-10", "Travaux du PLU", PLU + " et les remarques des personnes publiques associées")]),
        meeting("2024-07-10", [item(1, "2024-07-10", "Ligne de trésorerie", TRESO + " renouvelée", amounts=(300000,)),
                               item(2, "2024-07-10", "Questions diverses", "Aucune question.")]),
        meeting("2024-09-10", [item(1, "2024-09-10", "Réunion de rentrée", "La rentrée scolaire est évoquée en séance.")]),
        meeting("2024-11-10", [item(1, "2024-11-10", "Voirie", "Les travaux de voirie du hameau sont programmés.")]),
    ]


def test_items_on_the_same_subject_are_linked_across_meetings():
    r = th.build_threads(sample())
    treso = next(t for t in r["threads"] if "treso" in " ".join(t["label_terms"]) or "tresorerie" in " ".join(t["label_terms"]))
    assert treso["meetings"] == ["2024-01-10", "2024-03-10", "2024-07-10"] and treso["status"] == "recurring"


def _vocab(start, n=40):
    import itertools
    return " ".join("".join(w) for w in list(itertools.product("abcdefgh", repeat=5))[start:start + n])


def test_a_rare_acronym_in_a_title_links_items_whose_other_words_differ():
    a = item(1, "2024-03-10", "Règlement du PLU", f"Le PLU prévoit des zones. Le PLU est discuté. {_vocab(0)}")
    b = item(1, "2024-05-10", "Concertation", f"Réunion publique sur le PLU. Le PLU est présenté. {_vocab(100)}")
    rows = [meeting("2024-03-10", [a]), meeting("2024-05-10", [b])]
    # Precondition: by word overlap alone these two are NOT similar enough to link.
    va, vb = th.item_terms(a, set()), th.item_terms(b, set())
    shared = {t for t in va if t in vb}
    assert shared == {"plu"} or len(shared) <= 2
    plu = next((t for t in th.build_threads(rows)["threads"] if "plu" in t["label_terms"]), None)
    assert plu is not None and plu["meetings"] == ["2024-03-10", "2024-05-10"]


def test_an_acronym_in_a_title_but_only_once_in_the_text_does_not_link():
    a = item(1, "2024-03-10", "Règlement du PLU", f"Le PLU prévoit des zones. {_vocab(0)}")
    b = item(1, "2024-05-10", "Concertation PLU", f"Réunion publique. {_vocab(100)}")
    assert th.build_threads([meeting("2024-03-10", [a]), meeting("2024-05-10", [b])])["threads"][0]["n_meetings"] == 1


def test_routine_and_sensitive_items_are_standing_not_issues():
    r = th.build_threads(sample())
    names = " ".join(r["standing"])
    assert "property sales" in names and "Approval of the previous minutes" in names
    assert all("Approbation" not in t["title"] and "préemption" not in t["title"] for t in r["threads"])
    assert any("Questions diverses" in x["item"]["title"] for rows in r["standing"].values() for x in rows)


def test_table_items_are_ignored():
    rows = [meeting("2024-01-10", [item(1, "2024-01-10", "Depenses de fonctionnement", "1 049 853,58 1 126 826,58 " * 20)]),
            meeting("2024-02-10", [item(1, "2024-02-10", "Depenses de fonctionnement", "1 049 853,58 1 126 826,58 " * 20)])]
    assert th.build_threads(rows)["threads"] == []


def test_possibly_dropped_needs_deferred_wording_and_enough_later_meetings():
    r = th.build_threads(sample())
    plu = next(t for t in r["threads"] if "plu" in t["label_terms"])
    assert plu["possibly_dropped"] is False        # its last item (2024-05-10) has no postponement wording
    rows = sample()
    rows[2]["meeting"]["items"][1]["followups"] = [{"type": "deferred", "sentence": "Reporté au prochain conseil."}]
    plu = next(t for t in th.build_threads(rows)["threads"] if "plu" in t["label_terms"])
    assert plu["possibly_dropped"] is True and plu["later_meetings"] == 3
    rows[2]["meeting"]["items"][1]["followups"] = [{"type": "planned", "sentence": "Un devis est à prévoir."}]
    plu = next(t for t in th.build_threads(rows)["threads"] if "plu" in t["label_terms"])
    assert plu["possibly_dropped"] is False        # a plan alone is not enough


def test_a_recent_postponement_is_not_called_dropped_yet():
    rows = sample()[:2]
    rows[1]["meeting"]["items"][1]["followups"] = [{"type": "deferred", "sentence": "Le point sera revu."}]
    assert not any(t["possibly_dropped"] for t in th.build_threads(rows)["threads"])


def test_todo_status_says_when_an_issue_returned_or_that_it_did_not():
    r = th.build_threads(sample())
    status = th.todo_status(r)
    assert status["2024-03-10-02"] == "the issue comes back on 2024-05-10"
    rows = sample()
    rows[2]["meeting"]["items"][1]["followups"] = [{"type": "deferred", "sentence": "Reporté."}]
    status = th.todo_status(th.build_threads(rows))
    assert "no later mention found in the 3 meeting(s) that followed" in status["2024-05-10-02"]


def test_names_are_kept_out_of_the_vocabulary():
    a = item(1, "2024-01-10", "Point", "Madame Dubois présente le dossier du hangar agricole")
    assert "dubois" not in th.item_terms(a, {"dubois"}) and "hangar" in th.item_terms(a, {"dubois"})


def test_thread_page_lists_the_timeline_amounts_and_the_caveat():
    r = th.build_threads(sample())
    treso = next(t for t in r["threads"] if "tresorerie" in t["label_terms"])
    md = th.render_thread(treso)
    assert "Machine-generated grouping" in md and "Linked by shared words" in md
    assert "### 2024-01-10:" in md and "#page=1" in md and "../meetings/2024-01-10/facts.md" in md
    assert "## Amounts across meetings" in md and "300 000 €" in md and "250 000 €" in md


def test_index_themes_and_pages_are_written_and_stale_pages_removed(tmp_path):
    m = sample()
    r = th.build_threads(m)
    topics = tmp_path / "topics"
    topics.mkdir()
    (topics / "stale-2020-01-01.md").write_text("old")
    n = th.write_topics(tmp_path, r, m)
    names = sorted(p.name for p in topics.glob("*.md"))
    assert "index.md" in names and "themes.md" in names and "stale-2020-01-01.md" not in names and n == len(names) - 2
    index = (topics / "index.md").read_text(encoding="utf-8")
    assert "## Recurring issues" in index and "## Possibly dropped" in index and "## Standing items" in index
    themes = (topics / "themes.md").read_text(encoding="utf-8")
    assert "2024-Q1" in themes and "| finances |" in themes and "**All items**" in themes


def test_accounting_carry_over_is_not_a_postponement_and_figures_are_not_followups():
    assert find_followups("Le déficit reporté de 2024 s’élève à un montant important pour le budget.") == []
    assert find_followups("Résultat reporté 12 500,00 € 1 234,00 € report 55 000,00") == []
    assert [f["type"] for f in find_followups("Le dossier est reporté au prochain conseil municipal.")] == ["deferred"]
