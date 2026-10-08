import json
import re
from types import SimpleNamespace

import pytest

from echo_montolieu.generate import Budget, estimate_generation, generate
from echo_montolieu.translate import BudgetExceeded, ChatModel, ChatTranslator, parse_batch
from tests.test_meeting_render import record
from tests.test_summarise import GOOD


class Smart:
    """A stand-in model: writes a French summary for summary prompts, 'translates' for the rest."""

    def __init__(self, corrupt_numbers=False):
        self.calls, self.corrupt = [], corrupt_numbers
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature, max_tokens):
        system, user = messages[0]["content"], messages[-1]["content"]
        self.calls.append((system, user))
        if "résumés" in system:
            text = GOOD
        else:
            lang = "nl" if "Dutch" in system else "en"

            def tr(seg):
                seg = f"[{lang}] {seg}"
                return seg.replace("12 500,00", "12 800,00") if self.corrupt else seg
            if user.startswith("[[1]]"):
                segs = parse_batch(user, user.count("[[") // 1)
                text = "\n".join(f"[[{i}]]\n{tr(s)}" for i, s in enumerate(segs, start=1))
            else:
                text = tr(user)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                               usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500))


def make_public(tmp_path):
    public = tmp_path / "public"
    (public / "minutes").mkdir(parents=True)
    rec = record()
    (public / "minutes" / "aaaaaaaaaaaa.json").write_text(json.dumps(rec))
    (public / "index.json").write_text(json.dumps({"count": 1, "documents": [
        {"document_id": "aaaaaaaaaaaa", "filename": "a.pdf", "meeting_date": rec["meeting_date"],
         "file": "minutes/aaaaaaaaaaaa.json"}]}))
    return public


def run(tmp_path, client=None, **kw):
    public = make_public(tmp_path) if not (tmp_path / "public").exists() else tmp_path / "public"
    client = client or Smart()
    summ, trans = ChatModel("sum-model", client=client), ChatTranslator("tr-model", client=client)
    report = generate(public, summ, trans, ["en", "nl"], **kw)
    return public / "meetings" / "2025-03-05", client, report


def test_writes_the_french_summary_and_both_translations_of_summary_and_minutes(tmp_path):
    folder, client, report = run(tmp_path)
    for name in ("summary.md", "summary.en.md", "summary.nl.md", "minutes.en.md", "minutes.nl.md"):
        assert (folder / name).exists(), name
    assert report["summaries"] == 1 and report["translations"] == 4 and not report["needs_review"]
    fr = (folder / "summary.md").read_text(encoding="utf-8")
    assert "language: fr" in fr and "summary_model: sum-model" in fr and "## Résumé" in fr


def test_translated_summary_keeps_structure_citations_and_says_what_it_is(tmp_path):
    folder, _, _ = run(tmp_path)
    en = (folder / "summary.en.md").read_text(encoding="utf-8")
    assert "language: en" in en and "translated_from: fr" in en and "translation_model: tr-model" in en
    assert "Machine translation" in en and "written by an AI model" in en
    assert "## [en] Résumé" in en and "[p.1]" in en and "[p.2]" in en          # structure and page cites survive
    assert "À relire" not in en and "écrit automatiquement" not in en          # the French notice is replaced
    nl = (folder / "summary.nl.md").read_text(encoding="utf-8")
    assert "Automatische vertaling" in nl and "language: nl" in nl


def test_translated_minutes_translate_prose_but_leave_the_french_original_untouched(tmp_path):
    folder, _, _ = run(tmp_path)
    en = (folder / "minutes.en.md").read_text(encoding="utf-8")
    assert "language: en" in en and "machine_translated: true" in en and "translation_model: tr-model" in en
    assert "## [en] Décision modificative budgétaire" in en and "Machine translation" in en
    assert "https://example.test/a.pdf#page=1" in en                           # page links survive
    assert "Mme DUBOIS Claire" in en                                            # names restored after masking
    assert "[en]" not in (folder / "summary.md").read_text(encoding="utf-8")   # French untouched


def test_private_people_and_sale_details_never_reach_the_model(tmp_path):
    folder, client, _ = run(tmp_path)
    sent = "\n".join(user for _, user in client.calls)
    assert "DURAND" not in sent and "90 000" not in sent and "Écoles" not in sent   # the sale notice
    assert "MOREL" not in sent                                                       # a private person


def test_summary_calls_may_name_officials_but_translation_calls_mask_every_name(tmp_path):
    folder, client, _ = run(tmp_path)
    summary_calls = [user for system, user in client.calls if "résumés" in system]
    translation_calls = [user for system, user in client.calls if "Translate" in system]
    assert summary_calls and translation_calls
    assert any("Mme DUBOIS Claire" in c for c in summary_calls)                     # the owner's policy
    assert not any("DUBOIS" in c or "LEFEBVRE" in c for c in translation_calls)     # masked before sending
    en = (folder / "minutes.en.md").read_text(encoding="utf-8")
    assert "vendeur(s) : DURAND Jean" in en and "[en] Vente" not in en              # sale text stays French


def test_a_second_run_makes_no_calls_and_skips_everything_unchanged(tmp_path):
    folder, client, first = run(tmp_path)
    n = len(client.calls)
    _, client2, second = run(tmp_path, client=client)
    assert len(client2.calls) == n
    assert second["summaries"] == 0 and second["translations"] == 0 and second["skipped"] == 5


def test_force_rewrites_but_the_cache_means_it_is_still_free(tmp_path):
    folder, client, _ = run(tmp_path)
    n = len(client.calls)
    summ = ChatModel("sum-model", client=client)
    trans = ChatTranslator("tr-model", client=client)
    # fresh model objects have empty in-memory caches, so a real second pass would call again;
    # with the same objects (as in one process) the cache absorbs it:
    report = generate(tmp_path / "public", summ, trans, ["en"], force=True)
    assert report["summaries"] == 1 and report["translations"] == 2
    assert len(client.calls) > n                                                     # new model objects: calls happen


def test_a_translation_that_changed_a_number_keeps_the_french_and_is_reported(tmp_path):
    folder, _, report = run(tmp_path, client=Smart(corrupt_numbers=True))
    en = (folder / "minutes.en.md").read_text(encoding="utf-8")
    assert "12 500,00 €" in en and "12 800,00" not in en                             # the wrong figure never appears
    assert "not translated: an automatic check failed" in en
    assert "segments_kept_in_french:" in en and any("minutes.en.md" in x for x in report["needs_review"])


def test_the_spending_cap_stops_the_run_and_reports_it(tmp_path):
    public = make_public(tmp_path)
    client, budget = Smart(), Budget(0.0000001)
    price = ("p", 1.0, 2.0)
    summ = ChatModel("sum-model", client=client, on_usage=budget.hook(price))
    trans = ChatTranslator("tr-model", client=client, on_usage=budget.hook(price))
    report = generate(public, summ, trans, ["en", "nl"])
    assert report["stopped"] and "cap" in report["stopped"]
    assert not (public / "meetings" / "2025-03-05" / "minutes.nl.md").exists()


def test_index_links_the_summary_and_language_versions(tmp_path):
    folder, _, _ = run(tmp_path)
    index = (folder.parent / "index.md").read_text(encoding="utf-8")
    for link in ("2025-03-05/summary.md", "2025-03-05/summary.en.md", "2025-03-05/minutes.nl.md"):
        assert link in index


def test_estimate_is_computed_without_calls_and_scales_with_languages(tmp_path):
    public = make_public(tmp_path)
    one = estimate_generation(public, ["en"], ("p", 0.1, 0.2), ("p", 0.1, 0.2))
    two = estimate_generation(public, ["en", "nl"], ("p", 0.1, 0.2), ("p", 0.1, 0.2))
    assert one["meetings"] == 1 and one["summary"]["usd"] > 0
    assert two["translation"]["tokens_in"] > one["translation"]["tokens_in"]
    assert estimate_generation(public, ["en"], None, None)["summary"]["usd"] is None
