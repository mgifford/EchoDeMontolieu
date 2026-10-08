from types import SimpleNamespace

from echo_montolieu.meeting import parse_meeting
from echo_montolieu.summarise import (SECTIONS, SYSTEM, check_summary, summarise, summary_input)
from echo_montolieu.translate import ChatModel
from tests.test_meeting_render import record

GOOD = """## Résumé
Le conseil municipal s’est réuni pour ajuster le budget de la commune et statuer sur des droits de préemption. Une dépense de 12 500,00 € a été inscrite. La séance s’est tenue à la mairie de Montolieu avec la majorité des élus présents ce soir-là.
## Points abordés
- **Décision modificative budgétaire** : une dépense de 12 500,00 € est inscrite. Vote : à la majorité. [p.1]
- **Droits de préemption** : des décisions ont été prises sur des ventes, sans détail. Vote : à l’unanimité. [p.2]
## Suites annoncées
- Le dossier sera réétudié lors d’un prochain conseil. [p.1]"""


class Client:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature, max_tokens):
        self.calls.append(messages)
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def test_the_model_is_given_scrubbed_text_and_no_private_sale_details():
    text = summary_input(parse_meeting(record()))
    assert "Mme DUBOIS Claire" in text                          # an elected official may be named
    assert "MOREL" not in text and "DURAND" not in text         # private people are not
    assert "90 000" not in text and "Écoles" not in text        # nor a sale's price or place
    assert "Décisions relatives à des ventes de biens privés : 1 avis. Aucun détail fourni." in text
    assert "### Point 1 : Décision modificative budgétaire (p.1)" in text


def test_a_good_summary_passes_every_check():
    source = summary_input(parse_meeting(record()))
    checks = check_summary(GOOD, source, page_count=2)
    assert all(checks.values()), checks


def test_checks_catch_an_invented_figure_a_bad_page_wrong_language_and_missing_sections():
    source = summary_input(parse_meeting(record()))
    assert not check_summary(GOOD.replace("12 500,00", "15 000,00"), source, 2)["figures_in_source"]
    assert not check_summary(GOOD.replace("[p.2]", "[p.9]"), source, 2)["pages_exist"]
    assert not check_summary(GOOD.replace(" [p.1]", "").replace(" [p.2]", ""), source, 2)["pages_cited"]
    assert not check_summary(GOOD.replace("## Suites annoncées", "## Suites"), source, 2)["sections_present"]
    english = ("## Résumé\nThe council met to adjust the budget and the decision was taken by the majority of the "
               "members present at the meeting of the evening in the town hall of the village and they voted. " * 3)
    assert not check_summary(english, source, 2)["is_french"]
    assert not check_summary("Voici le résumé : " + GOOD, source, 2)["no_preamble"]
    assert not check_summary(GOOD + " [name withheld]", source, 2)["no_placeholder"]


def test_small_numbers_are_not_flagged_but_amounts_are():
    source = "Point 1 : une dépense de 12 500,00 € le 22 juillet 2026."
    ok = check_summary("## Résumé\n## Points abordés\n## Suites annoncées\n[p.1] Trois points, 4 votes, le 22 juillet 2026 pour 12 500,00 €.", source, 1)
    assert ok["figures_in_source"]
    assert not check_summary("## Résumé\n## Points abordés\n## Suites annoncées\n[p.1] 99 999 €", source, 1)["figures_in_source"]


def test_summarise_writes_provenance_labels_and_marks_status():
    meeting = parse_meeting(record())
    md, checks, status = summarise(meeting, ChatModel("m", client=Client(GOOD)))
    assert status == "ok" and all(checks.values())
    for line in ("language: fr", "machine_generated: true", "summary_model: m", "status: ok", "prompt_version: 1"):
        assert line in md
    assert "écrit automatiquement par un modèle d’IA" in md and "[procès-verbal](minutes.md)" in md
    assert md.count("## ") == 3 + 0 and all(h in md for h in SECTIONS)


def test_a_failing_summary_gets_one_corrective_retry_and_the_better_one_is_kept():
    bad = GOOD.replace("12 500,00", "15 000,00")
    client = Client(bad, GOOD)
    md, checks, status = summarise(parse_meeting(record()), ChatModel("m", client=client))
    assert status == "ok" and len(client.calls) == 2
    assert "figures_in_source" in client.calls[1][-1]["content"]          # the retry says what failed
    assert "15 000" not in md


def test_a_summary_that_still_fails_is_published_but_marked_for_review():
    bad = GOOD.replace("12 500,00", "15 000,00")
    md, checks, status = summarise(parse_meeting(record()), ChatModel("m", client=Client(bad)))
    assert status == "needs_review" and not checks["figures_in_source"]
    assert "status: needs_review" in md and "À relire" in md and "figures_in_source" in md


def test_the_prompt_forbids_inventing_naming_private_people_and_sale_detail():
    for phrase in ("ne devine rien", "Ne nomme pas de personne privée", "ventes de biens privés", "Cite toujours la page"):
        assert phrase.lower() in SYSTEM.lower()
