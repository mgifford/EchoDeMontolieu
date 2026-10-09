import json

from echo_montolieu.meeting import (PLACEHOLDER, attendance_names, display_title, parse_meeting,
                                    scrub_names, title_key)
from echo_montolieu.render import render_all, render_minutes, render_facts, render_todo
from echo_montolieu.text import clean_page_lines, is_heading, is_table_line, paragraphs

# Invented minutes in the style of the real ones. All names are fictional.
PAGE1 = """
1
CONSEIL MUNICIPAL DU 5 MARS 2025
L’an deux mille vingt-cinq et le 5 mars à 19 h 00, le Conseil Municipal s’est réuni
sous la Présidence de Monsieur ARNAUD Paul, Maire de Montolieu.

Etaient présents :
Claire DUBOIS, Marc LEFEBVRE, Paul ARNAUD, Sonia MARTIN.

Etaient absents :
Luc BERNARD procuration à Marc LEFEBVRE.

Ordre du jour
- Décision modificative budgétaire
- Droits de préemption

DECISION MODIFICATIVE BUDGETAIRE

Suite à l’achat d’une parcelle au lieu-dit Fontbelle, il convient d’ajuster le budget.
Une dépense de 12 500,00 € est inscrite, conformément à l’article L2121-29 du code
général des collectivités territoriales. Le dossier sera réétudié lors d’un prochain
conseil. Mme DUBOIS Claire s’abstient. M. Pierre MOREL, habitant du hameau, demande une réponse.
Vote du conseil à la majorité (1 abstention)
"""
PAGE2 = """
2
DROITS DE PREEMPTION

Vente d’un bien rue des Écoles, prix 90 000,00 €, vendeur(s) : DURAND Jean et DURAND Anne.
Le conseil vote à l’unanimité contre l’exercice du droit de préemption
"""


def record(tmp=None):
    pages = [{"page": 1, "method": "text_layer", "status": "machine_extracted", "text": PAGE1},
             {"page": 2, "method": "text_layer", "status": "machine_extracted", "text": PAGE2}]
    return {"document_id": "aaaaaaaaaaaa", "source_url": "https://example.test/a.pdf",
            "source_sha256": "ab" * 32, "retrieved_at": "2026-10-08T00:00:00+00:00", "page_count": 2,
            "meeting_date": {"value": "2025-03-05", "status": "tentative"}, "version": 1,
            "versions": [{}], "pages": pages}


def test_heading_and_table_rules():
    assert is_heading("DECISION MODIFICATIVE BUDGETAIRE") and not is_heading("Décision modificative")
    assert not is_heading("12") and not is_heading("A B")
    assert is_table_line("1 049 853,58 1 126 826,58") and not is_table_line("La séance est ouverte à 19h04")


def test_page_number_line_is_dropped_and_wrapped_lines_are_joined():
    lines = clean_page_lines("\n1\nPremière ligne qui continue\nsur la ligne suivante.\n", 1)
    assert "1" not in lines
    blocks = paragraphs([(l, 1) for l in lines])
    paras = [b for b in blocks if b["kind"] == "paragraph"]
    assert len(paras) == 1 and paras[0]["text"] == "Première ligne qui continue sur la ligne suivante."


def test_a_wrapped_capitals_heading_is_joined():
    blocks = paragraphs([("MODIFICATION DES INDEMNITES AUX ADJOINTS ET CONSEILLERS", 1), ("DELEGUES", 1), ("", 1), ("Suite au changement.", 1)])
    assert blocks[0]["kind"] == "heading" and blocks[0]["text"].endswith("CONSEILLERS DELEGUES")


def test_attendance_names_and_scrubbing_in_any_word_order():
    present, absent, holders = attendance_names(PAGE1)
    assert "Claire DUBOIS" in present and absent == ["Luc BERNARD"] and holders == ["Marc LEFEBVRE"]
    out = scrub_names("DUBOIS Claire et Marc LEFEBVRE ont voté. Mme DUBOIS Claire s’abstient.", present + absent)
    assert "DUBOIS" not in out and "LEFEBVRE" not in out and PLACEHOLDER.split()[0] in out
    assert scrub_names("M. le Maire propose.", present) == "M. le Maire propose."   # a role is not a name


def test_runs_of_names_collapse_to_one_marker():
    out = scrub_names("Membres : Claire DUBOIS, Marc LEFEBVRE et Sonia MARTIN.", ["Claire DUBOIS", "Marc LEFEBVRE", "Sonia MARTIN"])
    assert out == "Membres : [names withheld]."


def test_display_title_prefers_the_accented_agenda_wording():
    assert display_title("DECISION MODIFICATIVE BUDGETAIRE", ["Décision modificative budgétaire"]) == "Décision modificative budgétaire"
    assert display_title("APPROBATION DU PV DU 3 MARS", []) == "Approbation du PV du 3 mars"
    assert title_key("Décision modificative budgétaire") == title_key("DECISION MODIFICATIVE BUDGETAIRE")


def test_parse_meeting_finds_items_votes_amounts_refs_followups_and_places():
    m = parse_meeting(record())
    assert m["attendance"] == {"present": 4, "absent": 1}
    assert [i["title"] for i in m["items"]] == ["Décision modificative budgétaire", "Droits de préemption"]
    a, b = m["items"]
    assert a["vote_result"] == "majority" and a["votes"][0]["abstentions"] == 1
    assert [x["value"] for x in a["amounts"] if x["kind"] == "eur"] == [12500.0]
    assert any(r["key"] == "CGCT L2121-29" for r in a["legal_refs"])
    assert [f["type"] for f in a["followups"]] == ["deferred"]
    assert [p["label"] for p in a["places"]] == ["Fontbelle"]
    assert "finances" in a["topics"]
    blob = json.dumps(a, ensure_ascii=False)
    assert "Mme DUBOIS Claire s’abstient" in blob              # an elected official is named
    assert "MOREL" not in blob                                  # a private person is not


def test_property_sale_items_keep_counts_only():
    b = parse_meeting(record())["items"][1]
    assert b["sensitive"] and b["sale_notices"] == 1
    assert b["amounts"] == [] and b["places"] == [] and b["snippet"] == ""
    assert "DURAND" not in json.dumps(b) and "90 000" not in json.dumps(b) and "Écoles" not in json.dumps(b)


def test_minutes_markdown_is_faithful_linked_and_keeps_names():
    md = render_minutes(record())
    assert md.startswith("---\n") and "# Conseil municipal du 5 mars 2025" in md
    assert md.count("\n# ") == 1                                # one H1: the title is not repeated
    assert "## Décision modificative budgétaire" in md and "## Droits de préemption" in md
    assert "Claire DUBOIS" in md and "DURAND Jean" in md        # faithful: names kept
    assert "https://example.test/a.pdf#page=2" in md
    assert "### Ordre du jour\n\n- Décision modificative budgétaire\n- Droits de préemption\n\n## " in md
    assert "12 500,00 €" in md


def test_summary_and_todo_cite_pages_and_carry_no_names():
    m = parse_meeting(record())
    s, t = render_facts(m), render_todo(m)
    assert "12 500 €" in s and "CGCT L2121-29" in s and "Fontbelle" in s
    assert "Decisions about sales of private property (1 notice(s))" in s
    for text in (s, t):
        assert "MOREL" not in text and "DURAND" not in text and "90 000" not in text and "Écoles" not in text
    assert "Mme DUBOIS Claire s’abstient" in s                  # officials may be named
    assert "https://example.test/a.pdf#page=1" in s
    assert "- [ ] “Le dossier sera réétudié" in t or "prochain" in t


def test_ocr_pages_are_flagged_fenced_and_never_merged_together():
    rec = record()
    for n in (3, 4):
        rec["pages"].append({"page": n, "method": "tesseract", "status": "needs_review",
                             "text": f"1 234,00 page {n}", "text_sparse": "x", "ocr": {"mean_conf": 58.7}})
    rec["page_count"] = 4
    md = render_minutes(rec)
    assert md.count("est une image lue par OCR") == 2 and "pour la ou les pages 3, 4" in md
    assert "```text\n1 234,00 page 3\n```" in md and "```text\n1 234,00 page 4\n```" in md


def test_render_all_writes_one_folder_per_meeting_and_an_index(tmp_path):
    public = tmp_path / "public"
    (public / "minutes").mkdir(parents=True)
    rec = record()
    (public / "minutes" / "aaaaaaaaaaaa.json").write_text(json.dumps(rec))
    (public / "index.json").write_text(json.dumps({"count": 1, "documents": [
        {"document_id": "aaaaaaaaaaaa", "filename": "a.pdf", "meeting_date": rec["meeting_date"],
         "file": "minutes/aaaaaaaaaaaa.json"}]}))
    report, meetings = render_all(public)
    assert report["folders"] == ["2025-03-05"] and meetings[0]["folder"] == "2025-03-05"
    for name in ("minutes.md", "facts.md", "todo.md"):
        assert (public / "meetings" / "2025-03-05" / name).exists()
    index = (public / "meetings" / "index.md").read_text(encoding="utf-8")
    assert "2025-03-05" in index and "2025-03-05/facts.md" in index


def test_two_proxy_lines_on_one_run_are_two_absentees_not_one_merged_name():
    text = ("Etaient présents : Ann DURAND, Bob MARTIN. Etaient absents : Cyril PETIT procuration à Ann DURAND. "
            "Dora ROUX procuration à Bob MARTIN. La séance est ouverte à 19h.")
    present, absent, holders = attendance_names(text)
    assert absent == ["Cyril PETIT", "Dora ROUX"] and holders == ["Ann DURAND", "Bob MARTIN"]
    assert present == ["Ann DURAND", "Bob MARTIN"]


# ---- headings that are names, and table captions --------------------------------------

from echo_montolieu.meeting import scrub_title, surname_tokens  # noqa: E402

NAMES = ["Claire DUBOIS", "Marc LEFEBVRE", "Anne ETORÉ-LORTHOLARY"]


def test_a_heading_that_is_only_a_surname_is_scrubbed():
    sn = surname_tokens(NAMES)
    assert {"dubois", "lefebvre", "etore", "lortholary"} <= sn
    assert scrub_title("ETORE-LORTHOLARY", NAMES, sn) == "[name withheld]"
    assert scrub_title("DEMANDE DE MONSIEUR DIDIER ALMONT", NAMES, sn) == "DEMANDE DE [name withheld]"
    assert scrub_title("REPONSE DE DUBOIS", NAMES, sn) == "REPONSE DE [name withheld]"
    assert scrub_title("TRAVAUX DU MUSEE", NAMES, sn) == "TRAVAUX DU MUSEE"
    assert scrub_title("DEMANDE DE MONSIEUR LE MAIRE", NAMES, sn) == "DEMANDE DE MONSIEUR LE MAIRE"


def test_table_captions_without_a_sentence_fold_into_the_previous_item():
    page = """
1
CONSEIL MUNICIPAL DU 4 AVRIL 2024
Ordre du jour
- Budget

BUDGET GENERAL

Le conseil examine le budget général de la commune pour l’exercice en cours et le vote.
Vote du conseil à l’unanimité

DEPENSES DE FONCTIONNEMENT

Section de fonctionnement

FONCTIONNEMENT RECETTES

Libellé
"""
    rec = {"document_id": "bbbbbbbbbbbb", "source_url": "https://example.test/b.pdf", "source_sha256": "cd" * 32,
           "retrieved_at": "2026-10-08T00:00:00+00:00", "page_count": 1, "meeting_date": {"value": "2024-04-04", "status": "tentative"},
           "version": 1, "versions": [{}], "pages": [{"page": 1, "method": "text_layer", "status": "machine_extracted", "text": page}]}
    items = parse_meeting(rec)["items"]
    assert [i["title"] for i in items] == ["Budget"]            # captions folded in, agenda wording used
    assert items[0]["pages"] == [1, 1] and items[0]["vote_result"] == "unanimous"


# ---- elected officials are visible, everyone else is not ----------------------------------


def test_keep_leaves_officials_visible_even_with_an_honorific_but_scrubs_others():
    officials = ["Claire DUBOIS", "Marc LEFEBVRE"]
    text = "Mme DUBOIS Claire propose. Monsieur Marc LEFEBVRE répond. M. Pierre MOREL intervient."
    out = scrub_names(text, officials, keep=officials)
    assert "DUBOIS" in out and "LEFEBVRE" in out and "MOREL" not in out
    hidden = scrub_names(text, officials)                          # no keep: everything scrubbed
    assert "DUBOIS" not in hidden and "LEFEBVRE" not in hidden


def test_official_surname_heading_stays_but_an_unlisted_person_heading_does_not():
    names = ["Claire DUBOIS"]
    assert scrub_title("DUBOIS", names, set(), keep=names) == "DUBOIS"
    assert scrub_title("DEMANDE DE MONSIEUR PIERRE MOREL", names, set(), keep=names) == "DEMANDE DE [name withheld]"


def test_officials_visible_can_be_switched_off():
    m = parse_meeting(record(), officials_visible=False)
    assert "DUBOIS" not in json.dumps(m, ensure_ascii=False)


def test_seller_names_are_scrubbed_everywhere_not_only_in_the_sale_item():
    rec = record()
    rec["pages"][1]["text"] = PAGE2 + "\nPlus loin, DURAND Jean est cité dans une autre phrase."
    text = json.dumps(parse_meeting(rec), ensure_ascii=False)
    assert "DURAND" not in text


# ---- regressions found on the real minutes ---------------------------------------------------

from echo_montolieu.meeting import honorific_names  # noqa: E402


def test_a_role_after_an_honorific_is_not_a_name():
    officials = ["Claire DUBOIS"]
    for text in ("Monsieur Le Maire propose.", "M. Le Maire propose.", "Madame la Présidente répond.",
                 "Monsieur le Trésorier précise."):
        assert scrub_names(text, officials, keep=officials) == text


def test_an_official_followed_by_a_title_is_still_recognised():
    officials = ["Céline SALA"]
    out = scrub_names("Madame SALA Céline Conseillère déléguée présente.", officials, keep=officials)
    assert "SALA" in out
    assert honorific_names("M. AGASSE Baptiste Mme JACOB Sabine arrivent.") == ["AGASSE Baptiste", "JACOB Sabine"]


def test_a_person_named_with_an_honorific_is_scrubbed_in_later_mentions_without_one():
    rec = record()
    rec["pages"][0]["text"] += "\nM. Pierre MOREL demande la parole. Plus tard, MOREL Pierre précise le devis. Enfin MOREL conclut."
    text = json.dumps(parse_meeting(rec), ensure_ascii=False)
    assert "MOREL" not in text


def test_a_namesake_of_an_official_is_scrubbed_but_the_official_is_not():
    rec = record()
    rec["pages"][0]["text"] += "\nMonsieur Jérôme DUBOIS (habitant) intervient. Mme DUBOIS Claire répond."
    blob = json.dumps(parse_meeting(rec), ensure_ascii=False)
    assert "Jérôme" not in blob and "Mme DUBOIS Claire" in blob



# ---- language versions ---------------------------------------------------------------------


def test_minutes_render_in_each_language_with_its_own_labels_and_notice():
    fr, en, nl = (render_minutes(record(), lang=l, ai_model="test-model") for l in ("fr", "en", "nl"))
    assert "language: fr" in fr and "language: en" in en and "language: nl" in nl
    assert "Sommaire" in fr and "Contents" in en and "Inhoud" in nl
    assert "Machine translation" in en and "Automatische vertaling" in nl and "Machine translation" not in fr
    assert fr.startswith("---\ntitle: \"Procès-verbal") and "Notulen" in nl.split("---")[1]


def test_tr_translates_prose_headings_and_bullets_but_never_tables_or_ocr_text():
    rec = record()
    rec["pages"][0]["text"] += "\n\n1 049 853,58 1 126 826,58\n"
    rec["pages"].append({"page": 3, "method": "tesseract", "status": "needs_review",
                         "text": "Total dépenses 1 234,00", "text_sparse": "", "ocr": {"mean_conf": 58.7}})
    seen = []

    def tr(text, page=None):
        seen.append(text)
        return "«" + text + "»"

    md = render_minutes(rec, lang="en", tr=tr, ai_model="test-model")
    assert "## «Décision modificative budgétaire»" in md and "- «Décision modificative budgétaire»" in md
    assert "```text\n1 049 853,58 1 126 826,58\n```" in md                # table: untouched
    assert "```text\nTotal dépenses 1 234,00\n```" in md                  # OCR page: untouched
    assert not any("1 049 853" in t or "Total dépenses" in t for t in seen)  # never sent for translation
    assert any(t.startswith("L’an deux mille vingt-cinq") for t in seen)


def test_contents_and_anchors_follow_the_translated_headings():
    md = render_minutes(record(), lang="en", tr=lambda t, page=None: "Budget amendment" if t == "Décision modificative budgétaire" else t, ai_model="test-model")
    assert "- [Budget amendment](#budget-amendment)" in md and "## Budget amendment" in md


def test_items_carry_scrubbed_text_and_sale_items_carry_none():
    a, b = parse_meeting(record())["items"]
    assert "12 500,00 €" in a["text"] and "MOREL" not in a["text"] and "Mme DUBOIS Claire" in a["text"]
    assert b["text"] == ""                                          # a model is never given a sale notice


def test_known_names_lists_officials_sellers_and_honorific_names():
    from echo_montolieu.meeting import known_names
    names = known_names(record())
    assert {"Claire DUBOIS", "Marc LEFEBVRE", "DURAND Jean", "Pierre MOREL"} <= set(names)


def test_a_translated_render_must_name_its_model():
    import pytest
    with pytest.raises(ValueError, match="name the AI model"):
        render_minutes(record(), lang="en")
    with pytest.raises(ValueError):
        render_minutes(record(), lang="nl")
    assert render_minutes(record())                                      # French needs none: it is the original wording


def test_sale_items_never_keep_a_title_that_names_a_parcel_or_an_address():
    from echo_montolieu.meeting import SALE_TITLE_NEUTRAL, parse_meeting
    rec = {"document_id": "a" * 12, "source_url": "https://e/x.pdf", "source_sha256": "a" * 64, "page_count": 1, "version": 1,
           "meeting_date": {"value": "2026-06-05", "status": "tentative"},
           "pages": [{"page": 1, "method": "text_layer", "status": "machine_extracted", "page_url": "https://e/x.pdf#page=1",
                      "text": "ORDRE DU JOUR\n- Vente d'un immeuble cadastré C0551\n- Droits de préemption\n\n"
                              "VENTE D'UN IMMEUBLE CADASTREE C 551\nM. le maire propose la vente de l'immeuble cadastrée C0551 situé au 1 rue des Oliviers. "
                              "Prix de vente : 100 000 euros.\nVote du conseil à l'unanimité\n\n"
                              "DROITS DE PREEMPTION\nDésignation du bien vendu : Réf. Cadastrale : Section N° AB 221 13 rue des Remparts\n"}]}
    m = parse_meeting(rec)
    sale = [i for i in m["items"] if i["sensitive"]]
    assert sale and all("551" not in i["title"] and "oliviers" not in i["title"].lower() for i in sale)
    assert SALE_TITLE_NEUTRAL in {i["title"] for i in sale}
    assert all(not i["text"] and not i["snippet"] for i in sale)


def test_an_address_heading_split_off_a_sale_notice_stays_part_of_the_sale():
    from echo_montolieu.meeting import parse_meeting
    rec = {"document_id": "b" * 12, "source_url": "https://e/x.pdf", "source_sha256": "b" * 64, "page_count": 1, "version": 1,
           "meeting_date": {"value": "2026-06-05", "status": "tentative"},
           "pages": [{"page": 1, "method": "text_layer", "status": "machine_extracted", "page_url": "https://e/x.pdf#page=1",
                      "text": "ORDRE DU JOUR\n- Vente d'un immeuble\n- Questions diverses\n\n"
                              "VENTE D'UN IMMEUBLE\nM. le maire propose la vente. Prix de vente : 100 000 euros.\nNotaire chargé de la vente :\n\n"
                              "11390 – CUXAC CABARDES.\nPublicité de la vente : affichage. Il propose de passer au vote.\n\n"
                              "QUESTIONS DIVERSES\nRien à signaler.\n"}]}
    items = parse_meeting(rec)["items"]
    assert [i["sensitive"] for i in items][:2] == [True, True]
    assert not any("cuxac" in (i["title"] + i["text"] + i["snippet"]).lower() for i in items)
