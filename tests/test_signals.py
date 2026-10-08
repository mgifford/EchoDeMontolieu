import pytest

from echo_montolieu.signals import (find_amounts, find_exceptions, find_followups,
                                    find_legal_refs, find_place_candidates, find_topics,
                                    is_property_transaction, parse_number, parse_votes,
                                    sentences)

# Realistic fragments, with invented names.


def test_sentences_split_on_sentence_ends_only():
    s = sentences("Le conseil vote. Mme X s’abstient. M. le Maire propose 12,5 % de hausse.")
    assert len(s) == 3 and s[2].endswith("hausse.")


def test_vote_unanimous_majority_and_counts():
    assert parse_votes("Vote du conseil à l’unanimité.")["result"] == "unanimous"
    maj = parse_votes("Vote du conseil à la majorité, Mme Durand s’abstient.")
    assert maj["result"] == "majority" and maj["votes"][0]["abstentions"] == 1
    counted = parse_votes("La proposition est retenue par 10 voix pour et une abstention.")
    assert counted["result"] == "majority"
    assert counted["votes"][0]["for"] == 10 and counted["votes"][0]["abstentions"] == 1
    assert parse_votes("Vote : 9 voix pour, 2 contre, deux abstentions.")["votes"][0]["against"] == 2


def test_unanimous_vote_against_preempting_is_still_unanimous():
    r = parse_votes("Le conseil vote à l’unanimité contre l’exercice du droit de préemption")
    assert r["result"] == "unanimous"


def test_mixed_votes_in_one_item_are_a_majority_and_rejection_wins():
    text = "Vote à l’unanimité. Ensuite, vote à la majorité (1 abstention)."
    assert parse_votes(text)["result"] == "majority"
    assert parse_votes("La proposition est rejetée à la majorité.")["result"] == "rejected"


def test_no_vote_found_is_none_not_unanimous():
    assert parse_votes("Le maire présente le dossier.") == {"result": None, "votes": []}
    assert parse_votes("") == {"result": None, "votes": []}


def test_did_not_take_part_is_counted():
    v = parse_votes("Vote à la majorité, M. Martin ne prend pas part au vote.")["votes"][0]
    assert v["did_not_vote"] == 1


@pytest.mark.parametrize("raw,expected", [("12 000", 12000.0), ("12 000,50", 12000.5),
                                          ("3 522.01", 3522.01), ("1.049.853,58", 1049853.58),
                                          ("90 000,00", 90000.0), ("1861", 1861.0), ("0,5", 0.5)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == pytest.approx(expected)


def test_find_amounts_euros_and_rates_with_their_sentence():
    a = find_amounts("Une subvention de 1 500 € est votée. Le taux passe à 39,48 % de l’indice. "
                     "Le devis s’élève à 12 345,60 euros.")
    eur = [x["value"] for x in a if x["kind"] == "eur"]
    assert eur == [1500.0, 12345.6]
    assert [x["value"] for x in a if x["kind"] == "pct"] == [39.48]
    assert a[0]["sentence"].startswith("Une subvention")


def test_find_legal_refs_names_the_code_and_deduplicates():
    refs = find_legal_refs("En application de l’article L2121-21 du code général des collectivités "
                           "territoriales, le vote a lieu. Voir le décret 2022-581 et la loi n° 2023-1196. "
                           "Instruction M57 applicable.")
    keys = {r["key"] for r in refs}
    assert "CGCT L2121-21" in keys and "décret 2022-581" in keys and "loi 2023-1196" in keys
    assert "instruction M57" in keys
    assert len(refs) == len(set((r["key"], r["sentence"]) for r in refs))


def test_article_without_a_named_code_is_marked_unknown_not_guessed():
    refs = find_legal_refs("Conformément à l’article L 1111-2 il est décidé.")
    assert refs[0]["code"] is None and refs[0]["key"] == "? L1111-2"


def test_exception_markers():
    e = find_exceptions("À titre exceptionnel, la salle est prêtée. Une dérogation est accordée.")
    assert [x["marker"] for x in e] == ["à titre exceptionnel", "dérogation"]
    assert find_exceptions("Le conseil approuve le budget.") == []


def test_followup_candidates_have_types_and_skip_ordinary_sentences():
    f = find_followups("Le conseil autorise Monsieur le Maire à signer la convention. "
                       "Le dossier sera étudié lors d’un prochain conseil. "
                       "Un devis est à prévoir pour la toiture. Le conseil approuve le compte rendu.")
    assert [x["type"] for x in f] == ["authorisation", "deferred", "planned"]


def test_topics_are_ranked_and_titles_count_more():
    t = dict(find_topics("DECISION MODIFICATIVE BUDGETAIRE", "Les recettes et dépenses évoluent."))
    assert t["finances"] >= 3
    assert find_topics("QUESTIONS", "rien de spécial") == []
    assert "droit de préemption" in dict(find_topics("DROITS DE PREEMPTION", ""))


def test_property_transaction_detection():
    assert is_property_transaction("DROITS DE PREEMPTION", "")
    assert is_property_transaction("DIVERS", "Le droit de préemption ... exercice du droit de préemption")
    assert not is_property_transaction("TRAVAUX DE VOIRIE", "Réfection du chemin.")


def test_place_candidates_find_streets_and_lieux_dits_and_trim_trailing_words():
    p = find_place_candidates("Au lieu-dit Borderouge, parcelle A0041, et au 19 rue des remparts cadastré n°AB 341. "
                              "Travaux place du Marché pour la fête.")
    labels = {x["label"] for x in p}
    assert "Borderouge" in labels and "rue des remparts" in labels and "place du Marché" in labels
    assert not any("cadastr" in x["label"] for x in p)
    assert next(x for x in p if x["label"] == "rue des remparts")["number"] == "19"


def test_sentences_do_not_split_after_abbreviations_or_initials():
    s = sentences("M. Martin ne prend pas part au vote. Mme Durand et J. Petit approuvent. Fin.")
    assert len(s) == 3 and s[0].startswith("M. Martin") and "J. Petit" in s[1]


def test_a_single_sale_marker_is_enough_to_make_an_item_sensitive():
    assert is_property_transaction("VENTE PARCELLE", "Vendeur(s) : DURAND Jean et DURAND Anne.")
    assert is_property_transaction("DIVERS", "Désignation du bien vendu : une grange. Prix de vente : 90 000 EUR.")
    assert is_property_transaction("X", "Le conseil se prononce contre l’exercice du droit de préemption.")
    assert not is_property_transaction("TRAVAUX", "La commune achète un chemin pour un euro symbolique.")


def test_accounting_exceptional_categories_are_not_exceptions_but_real_ones_are():
    assert find_exceptions("Charges exceptionnelles 0,00 0,00 TOTAL FONCTIONNEMENT 1 049 853,58") == []
    assert find_exceptions("Les produits exceptionnels de l’exercice sont inscrits au budget de la commune.") == []
    assert [e["marker"] for e in find_exceptions("Une subvention exceptionnelle de 380 euros est accordée à la coopérative scolaire.")] == ["exceptionnelle"]
    assert [e["marker"] for e in find_exceptions("Les subventions sont votées à l’unanimité, à l’exception de la demande de l’association.")] == ["exception"]


def test_rule_wording_is_found_without_a_citation_and_figures_are_skipped():
    from echo_montolieu.signals import find_rule_mentions
    found = find_rule_mentions("Conformément à la réglementation, le conseil délibère. Le taux est plafonné par la loi de finances. "
                               "Le conseil remercie le public. Montant plafond 300 000 EUR 450 000 EUR 12 500,00 8 900,00 7 700 640 321.")
    assert len(found) == 2 and "Conformément" in found[0]["sentence"] and "plafonné" in found[1]["sentence"]
    assert find_rule_mentions("Le conseil approuve le compte rendu.") == []


def test_a_titre_exceptionnel_is_a_real_exception_not_an_accounting_category():
    assert [e["marker"] for e in find_exceptions("À titre exceptionnel, la salle est prêtée à l’association.")] == ["à titre exceptionnel"]


def test_notice_wording_of_a_sale_makes_an_item_sensitive():
    assert is_property_transaction("CUXAC CABARDES (11390).", "Notaire chargé de la vente : Étude de Maître X. offre d’achat vente 1 RUE DES OLIVIERS")
    assert is_property_transaction("X", "La commune décide la mise en vente de l’ancienne école.")
    assert is_property_transaction("X", "Les offres seront ouvertes. Mise à prix : 80 000 €.")


def test_a_place_followed_by_another_postal_code_is_in_another_commune():
    found = {p["label"] for p in find_place_candidates("Étude, 2 bis rue Bellevue 11390 Cuxac. Travaux rue des remparts 11170 Montolieu.")}
    assert "rue des remparts" in found and "rue Bellevue" not in found
    assert [p["label"] for p in find_place_candidates("La rue Bellevue (11390) est concernée.")] == []


def test_a_lieu_dit_followed_by_another_postal_code_is_in_another_commune():
    assert [p["label"] for p in find_place_candidates("Au lieu-dit Borderouge 11390 Cuxac, un terrain.")] == []
    assert [p["label"] for p in find_place_candidates("Au lieu-dit Borderouge 11170 Montolieu, un terrain.")] == ["Borderouge"]
