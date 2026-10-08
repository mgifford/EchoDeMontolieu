import csv
import json
from types import SimpleNamespace

import pytest

from echo_montolieu import trial
from echo_montolieu.translate import (ChatTranslator, build_messages, check_translation, glossary_for,
                                      mask_names, number_cores, unmask)

# Names are invented.


class FakeClient:
    """Stands in for the Hugging Face client; counts calls and echoes a canned reply."""

    def __init__(self, reply=lambda text, lang: f"[{lang}] {text}"):
        self.calls, self.reply = [], reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature, max_tokens):
        text, system = messages[1]["content"], messages[0]["content"]
        lang = "nl" if "Dutch" in system else "en"
        self.calls.append((model, text, lang, system))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply(text, lang)))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


def test_names_are_masked_before_sending_and_restored_after():
    text = "Mme DUBOIS Claire propose. Marc LEFEBVRE vote contre. Claire DUBOIS conclut."
    masked, mapping = mask_names(text, ["Claire DUBOIS", "Marc LEFEBVRE"])
    assert "DUBOIS" not in masked and "LEFEBVRE" not in masked and masked.count("⟦N") == 3
    assert unmask(masked, mapping) == text


def test_number_cores_ignore_separators_and_formats():
    assert number_cores("12 000,50 € et 3 %") == number_cores("€12,000.50 and 3%")
    assert number_cores("article L2121-21") != number_cores("article L2121-22")


def test_checks_catch_changed_numbers_lost_tokens_preambles_and_wrong_language():
    src = "Le conseil vote à l’unanimité la dépense de 12 500,00 € pour ⟦N1⟧ conformément à l’article L2121-29."
    good = "The council unanimously approves the expense of €12,500.00 for ⟦N1⟧ under article L2121-29."
    c = check_translation(src, good, "en", {"⟦N1⟧": "X"})
    assert all(c.values()), c
    assert not check_translation(src, good.replace("12,500", "12,800"), "en", {"⟦N1⟧": "X"})["numbers_preserved"]
    assert not check_translation(src, good.replace("⟦N1⟧", "Mr X"), "en", {"⟦N1⟧": "X"})["placeholders_preserved"]
    assert not check_translation(src, "Here is the translation: " + good, "en")["no_preamble"]
    assert not check_translation(src, good.replace("L2121-29", "L2121-30"), "en")["legal_refs_preserved"]
    assert not check_translation(src, src, "en")["is_target_language"]          # left in French
    assert not check_translation(src, "ok", "en")["length_plausible"]


def test_glossary_terms_are_pinned_in_the_prompt_and_checked_in_the_output():
    src = "Le conseil vote contre l’exercice du droit de préemption à l’unanimité des membres présents ce soir."
    assert "droit de préemption" in glossary_for(src, "en")
    system = build_messages(src, "nl")[0]["content"]
    assert "voorkooprecht" in system and "Dutch" in system
    assert check_translation(src, "De raad stemt unaniem tegen het voorkooprecht van de leden hier aanwezig vanavond.", "nl")["glossary_honoured"]
    assert not check_translation(src, "De raad stemt tegen de aankoop van de leden hier aanwezig vanavond ten slotte.", "nl")["glossary_honoured"]


def test_translations_are_cached_by_text_model_language_and_prompt_version(tmp_path):
    client = FakeClient()
    t = ChatTranslator("m1", client=client, cache_path=tmp_path / "c.json")
    first = t.translate("Bonjour le conseil.", "en")
    second = t.translate("Bonjour le conseil.", "en")
    assert first.text == "[en] Bonjour le conseil." and not first.cached and second.cached and len(client.calls) == 1
    t.translate("Bonjour le conseil.", "nl")                         # another language: a new call
    assert len(client.calls) == 2
    reopened = ChatTranslator("m1", client=FakeClient(), cache_path=tmp_path / "c.json")
    assert reopened.translate("Bonjour le conseil.", "en").cached     # survives a restart
    other_model = ChatTranslator("m2", client=client, cache_path=tmp_path / "c.json")
    assert not other_model.translate("Bonjour le conseil.", "en").cached


def record(text, date="2025-03-05"):
    return {"source_url": "https://example.test/a.pdf", "meeting_date": {"value": date},
            "pages": [{"page": 1, "method": "text_layer", "text":
                       "Etaient présents : Claire DUBOIS, Marc LEFEBVRE.\n\n" + text}]}


TEXTS = ["Le conseil vote à l’unanimité la proposition de Mme DUBOIS Claire pour la mairie de la commune.\n\n"
         "Une dépense de 12 500,00 € est inscrite conformément à l’article L2121-29 du code général des collectivités.\n\n"
         "Le dossier sera réétudié lors d’un prochain conseil municipal, une fois les devis reçus par la mairie.\n\n"
         "Vendeur(s) : DURAND Jean. Le conseil se prononce contre l’exercice du droit de préemption sur ce bien vendu.\n\n"
         "La commune ouvre une consultation pour les travaux de réfection de la toiture de la salle des fêtes."]


def test_sample_is_deterministic_varied_and_never_includes_private_property_sales():
    recs = [record(TEXTS[0])]
    a, b = trial.pick_sample(recs, per_category=2), trial.pick_sample(recs, per_category=2)
    assert [s["text"] for s in a] == [s["text"] for s in b]
    assert {s["category"] for s in a} >= {"vote", "amounts", "followup", "plain"}
    assert not any("DURAND" in s["text"] or "préemption" in s["text"] for s in a)
    assert all(s["names"] for s in a) and [s["id"] for s in a] == sorted(s["id"] for s in a)


def test_estimate_and_price_lookup():
    listing = [{"id": "a/m", "providers": [{"provider": "p1", "status": "live", "pricing": {"input": 0.5, "output": 1.0}},
                                            {"provider": "p2", "status": "live", "pricing": {"input": 0.1, "output": 0.2}},
                                            {"provider": "p3", "status": "down", "pricing": {"input": 0.0, "output": 0.0}}]}]
    assert trial.price_per_million("a/m", listing) == ("p2", 0.1, 0.2)
    assert trial.price_per_million("a/missing", listing) is None
    est = trial.estimate([{"text": "x" * 320}], ["en", "nl"], {"a/m": ("p2", 0.1, 0.2), "b/unknown": None})
    assert est["a/m"]["calls"] == 2 and est["a/m"]["usd"] > 0 and est["b/unknown"]["usd"] is None


def run(tmp_path, max_usd=1.0, clients=None):
    sample = trial.pick_sample([record(TEXTS[0])], per_category=1)
    models = ["m1", "m2"]
    clients = clients or {m: FakeClient() for m in models}
    translators = {m: ChatTranslator(m, client=clients[m]) for m in models}
    prices = {"m1": ("p", 1.0, 2.0), "m2": ("p", 3.0, 6.0)}
    rows, spent = trial.run_trial(sample, models, ["en", "nl"], translators, prices, max_usd, tmp_path / "out")
    return sample, rows, spent, clients


def test_trial_masks_names_in_what_it_sends_and_restores_them_in_the_report(tmp_path):
    sample, rows, spent, clients = run(tmp_path)
    sent = " ".join(call[1] for c in clients.values() for call in c.calls)
    assert "DUBOIS" not in sent and "⟦N" in sent                    # nothing named left the machine
    assert any("DUBOIS" in r["translation"] for r in rows)           # restored for the reader
    assert len(rows) == len(sample) * 2 * 2 and spent > 0


def test_trial_writes_report_and_a_blind_sheet_with_a_separate_key(tmp_path):
    sample, rows, spent, _ = run(tmp_path)
    out = tmp_path / "out"
    assert (out / "results.json").exists() and "Spent $" in (out / "report.md").read_text()
    sheet = list(csv.DictReader(open(out / "rating_sheet.csv", encoding="utf-8")))
    key = json.loads((out / "key.json").read_text())
    assert len(sheet) == len(sample) * 2 and set(key[sheet[0]["id"]]) == {"A", "B"}
    assert "m1" not in open(out / "rating_sheet.csv", encoding="utf-8").read()      # models hidden
    assert {key[r["id"]]["A"] for r in sheet} == {"m1", "m2"}                        # order is shuffled


def test_trial_stops_at_the_spending_cap(tmp_path):
    with pytest.raises(trial.BudgetExceeded):
        run(tmp_path, max_usd=0.00001)


# ---- batching ---------------------------------------------------------------------------------

from echo_montolieu.translate import build_batch, chunk_texts, parse_batch  # noqa: E402


def batch_client(transform=lambda seg, lang: f"[{lang}] {seg}", break_markers=False):
    """A client that understands batches: it translates each marked segment with `transform`."""
    def reply(text, lang):
        if text.startswith("[[1]]"):
            parts = parse_batch(text, text.count("[[") )
            out = "\n".join(f"[[{i}]]\n{transform(seg, lang)}" for i, seg in enumerate(parts, start=1))
            return out.replace("[[2]]", "<<2>>") if break_markers else out
        return transform(text, lang)
    return FakeClient(reply)


def test_batch_markers_round_trip_and_reject_broken_replies():
    texts = ["Un.", "Deux\nlignes.", "Trois."]
    assert parse_batch(build_batch(texts), 3) == texts
    assert parse_batch("[[1]]\na\n[[3]]\nc", 3) is None             # a missing marker
    assert parse_batch("[[2]]\na\n[[1]]\nb", 2) is None             # wrong order
    assert parse_batch("intro\n[[1]]\na", 1) is None                # text before the first marker
    assert chunk_texts(["a" * 10] * 5, limit=25, max_items=12) == [[0, 1], [2, 3], [4]]
    assert chunk_texts(["a"] * 30, limit=10_000, max_items=12) == [list(range(12)), list(range(12, 24)), list(range(24, 30))]


def test_many_segments_go_in_one_call_with_names_masked_and_restored():
    client = batch_client()
    t = ChatTranslator("m", client=client)
    texts = ["Mme DUBOIS Claire propose le budget de la commune.", "Le conseil vote à l’unanimité pour 1 200 €.",
             "Marc LEFEBVRE s’abstient lors du vote de ce soir."]
    out = t.translate_many(texts, "en", names=["Claire DUBOIS", "Marc LEFEBVRE"])
    assert len(client.calls) == 1                                    # three segments, one request
    assert all(ok for _, ok, _ in out)
    assert "DUBOIS" not in client.calls[0][1] and "LEFEBVRE" not in client.calls[0][1]
    assert "DUBOIS" in out[0][0] and "LEFEBVRE" in out[2][0]         # restored for the reader


def test_broken_markers_fall_back_to_one_call_per_segment():
    client = batch_client(break_markers=True)
    t = ChatTranslator("m", client=client)
    out = t.translate_many(["Premier paragraphe du texte.", "Deuxième paragraphe du texte."], "en")
    assert [o[0] for o in out] == ["[en] Premier paragraphe du texte.", "[en] Deuxième paragraphe du texte."]
    assert len(client.calls) == 3                                    # the batch, then two singles


def test_a_segment_whose_number_changed_is_retried_alone_then_reported_failed():
    def corrupt(seg, lang):
        return seg.replace("1 200", "1 300") if "1 200" in seg else f"[{lang}] {seg}"
    client = batch_client(transform=corrupt)
    t = ChatTranslator("m", client=client)
    out = t.translate_many(["Une dépense de 1 200 € est votée par le conseil.", "Le maire ouvre la séance du soir."], "en")
    assert out[1][1] is True
    text, ok, failed = out[0]
    assert ok is False and failed == ["numbers_preserved"]
    assert len(client.calls) == 2                                    # batch, then the single retry


def test_translate_many_is_idempotent_through_the_cache(tmp_path):
    client = batch_client()
    t = ChatTranslator("m", client=client, cache_path=tmp_path / "c.json")
    texts = ["Premier point de l’ordre du jour.", "Second point de l’ordre du jour."]
    first = t.translate_many(texts, "nl")
    again = ChatTranslator("m", client=batch_client(), cache_path=tmp_path / "c.json").translate_many(texts, "nl")
    assert first == again and len(client.calls) == 1


def test_usage_callback_fires_only_for_paid_calls_so_a_cap_can_be_enforced():
    seen = []
    client = batch_client()
    t = ChatTranslator("m", client=client, on_usage=seen.append)
    t.translate("Bonjour le conseil.", "en")
    t.translate("Bonjour le conseil.", "en")
    assert len(seen) == 1 and t.usage["calls"] == 1 and t.usage["cached"] == 1
