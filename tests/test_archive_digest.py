from echo_montolieu import archive_digest as ad

LINES = ("Etaient présents : DRIEUX. OLIVIER. DELPERIER. LASSERRE C. ETORE. RICARD.\n"
         "Etaient absents : SOULIE procuration à ETORE.\n"
         "Monsieur OLIVIER est désigné comme secrétaire de séance.\n")
BODY = ("Madame ETORE intervient au sujet du procès verbal. Monsieur PECH Frédéric souhaite acheter le terrain communal. "
        "Le Conseil accepte à l’unanimité la vente du terrain. "
        "Le budget est voté. Contre : 2 (etoré, ricard). Maître Maynadier est choisie par 7 voix pour et 2 voix contre. "
        "Le conseil décide à l’unanimité le choix de l’entreprise de maçonnerie pour un montant de 1100,32 Euros.\n")
FILLER = [{"page": 1, "text": "le conseil municipal décide de la voirie et du budget de la commune " * 5}] * 3


def rec(text, page_url="https://example.org/x.pdf#page=1"):
    return {"document_id": "d", "pages": [{"page": 1, "text": text, "page_url": page_url}] + FILLER}


def test_attendance_surnames_are_masked_in_any_accent_and_case():
    vocab = ad.Vocabulary([rec(LINES + BODY)])
    assert {"drieux", "etore", "ricard", "soulie"} <= vocab.roster
    out = vocab.scrub("Madame ETORE et Mr ricard votent contre; Étoré s’abstient.")
    assert "ETORE" not in out and "ricard" not in out.lower() and "toré" not in out and "[name withheld]" in out


def test_honorific_names_and_unknown_capitalised_words_are_masked_but_common_words_stay():
    vocab = ad.Vocabulary([rec(LINES + BODY)])
    out = vocab.scrub("Monsieur PECH Frédéric souhaite acheter ; la Commune choisit Maître Zanotti à Carcassonne.")
    assert "PECH" not in out and "Frédéric" not in out and "Zanotti" not in out
    assert "Commune" in out and "Carcassonne" in out


def test_digest_keeps_vote_sentences_drops_voter_lists_and_counts_sales():
    sale = LINES + BODY + "Droit de préemption sur la vente de la maison cadastrée AB 12 à Mme DUPUIS. Le conseil s’oppose à l’unanimité.\n"
    vocab = ad.Vocabulary([rec(sale)])
    d = ad.digest(rec(sale), vocab)
    text = " ".join(x["text"] for x in d["decisions"])
    assert d["decisions"] and all(x["kind"] for x in d["decisions"])
    for leaked in ("ETORE", "etoré", "ricard", "PECH", "Maynadier", "DUPUIS", "AB 12"):
        assert leaked.lower() not in text.lower()
    assert d["sale_notices"] == 1
    page = ad.render_facts(rec(sale), d, "2004-12-04")
    assert "Tous les noms sont remplacés" in page and "#page=1" in page and "Information sur l’IA" in page
