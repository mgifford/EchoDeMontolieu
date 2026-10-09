"""2003-2008 decisions pages in English and Dutch, and the What's new paragraph, with a stand-in model."""
import json
from types import SimpleNamespace

from echo_montolieu import archive_digest as ad
from echo_montolieu import archive_translate as at
from echo_montolieu import whats_new
from echo_montolieu.generate import generate
from echo_montolieu.render import render_all
from echo_montolieu.site import build
from echo_montolieu.translate import ChatModel, ChatTranslator, parse_batch

LINES = ("Etaient présents : DRIEUX. OLIVIER. DELPERIER. ETORE. RICARD.\nSecrétariat de séance : OLIVIER.\n")
BODY = ("Madame ETORE intervient au sujet du procès verbal. Le Conseil accepte à l’unanimité la subvention de 1100,32 Euros. "
        "Le budget est voté. Monsieur PECH Frédéric souhaite le terrain. Le conseil décide à l’unanimité le choix de l’entreprise de maçonnerie.\n")
FILLER = {"page": 2, "method": "text_layer", "status": "machine_extracted", "page_url": "https://web.archive.org/x.pdf#page=2", "text": "le conseil municipal décide de la voirie et du budget de la commune " * 5}


class Model:
    """Translates by tagging; writes a French paragraph for the paragraph prompt; can corrupt a number."""

    def __init__(self, corrupt=False, drop_token=False):
        self.calls, self.corrupt, self.drop_token = [], corrupt, drop_token
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature, max_tokens):
        system, user = messages[0]["content"], messages[-1]["content"]
        self.calls.append(user)
        if "En bref" in system:
            text = ("D’après les procès-verbaux, le conseil du 22 juillet 2026 a voté la décision modificative du budget. "
                    "Une subvention a été régularisée. Ces informations viennent des procès-verbaux et peuvent être en retard sur l’actualité. "
                    "Le conseil de juin a traité plusieurs points de routine.")
        else:
            lang = "nl" if "Dutch" in system else "en"

            def tr(seg):
                out = f"{lang.upper()}: " + seg.replace("l’unanimité", "unanimity")
                out = out.replace("1100,32", "1100,99") if self.corrupt else out
                return out.replace("⟦W⟧", "") if self.drop_token else out
            if user.startswith("[[1]]"):
                segs = parse_batch(user, user.count("[[1]]") and user.count("[["))
                text = "\n".join(f"[[{i}]]\n{tr(s)}" for i, s in enumerate(segs, start=1))
            else:
                text = tr(user)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


def archived_public(tmp_path):
    public = tmp_path / "public"
    (public / "minutes").mkdir(parents=True)
    rec = {"document_id": "d1", "version": 1, "origin": {"mirror_path": "archive/originals/x.pdf", "mirror_url": "https://example.org/x.pdf", "date_hint_from_filename": "2005-01-25"}, "source_url": "https://web.archive.org/x.pdf", "source_sha256": "ab" * 32,
           "retrieved_at": "2026-10-08T00:00:00+00:00", "meeting_date": {"value": "2005-01-25"}, "filename": "x.pdf", "versions": [], "labels": {},
           "pages": [{"page": 1, "method": "text_layer", "status": "machine_extracted", "page_url": "https://web.archive.org/x.pdf#page=1",
                      "text": LINES + BODY}, FILLER, FILLER, FILLER]}
    (public / "minutes" / "d1.json").write_text(json.dumps(rec))
    (public / "index.json").write_text(json.dumps({"documents": [{"document_id": "d1", "file": "minutes/d1.json", "filename": "x.pdf",
                                                                  "meeting_date": {"value": "2005-01-25"}}]}))
    return public


def translator(client):
    return ChatTranslator("tr-model", client=client)


def test_archive_decisions_are_translated_with_the_french_shown_and_names_still_withheld(tmp_path):
    public, client = archived_public(tmp_path), Model()
    report = at.translate_archive_facts(public, translator(client), ["en", "nl"])
    assert report["written"] == 2 and not report["needs_review"]
    page = (public / "meetings" / "2005-01-25" / "facts.en.md").read_text()
    assert "translation_model: tr-model" in page and "facts_source_sha256:" in page and "Machine translation:" in page and "French original:" in page
    assert "EN: " in page and "[name withheld]" in page
    for secret in ("ETORE", "PECH", "Frédéric"):
        assert secret not in page and not any(secret in c for c in client.calls)       # nothing unscrubbed was ever sent
    assert "Machinevertaling:" in (public / "meetings" / "2005-01-25" / "facts.nl.md").read_text()


def test_a_second_run_is_free_and_render_keeps_the_translation(tmp_path):
    public, client = archived_public(tmp_path), Model()
    at.translate_archive_facts(public, translator(client), ["en"])
    n = len(client.calls)
    assert at.translate_archive_facts(public, translator(client), ["en"])["skipped"] == 1 and len(client.calls) == n
    render_all(public)                                          # re-rendering must not overwrite a current translation
    assert "Machine translation:" in (public / "meetings" / "2005-01-25" / "facts.en.md").read_text()
    assert "Franse tekst:" in (public / "meetings" / "2005-01-25" / "facts.nl.md").read_text()      # no translation yet: plain labels


def test_a_translation_that_changes_a_number_or_loses_the_name_token_keeps_the_french(tmp_path):
    for client in (Model(corrupt=True), Model(drop_token=True)):
        public = archived_public(tmp_path / f"p{id(client)}")
        report = at.translate_archive_facts(public, translator(client), ["en"])
        assert report["needs_review"]
        page = (public / "meetings" / "2005-01-25" / "facts.en.md").read_text()
        assert "French text:" in page and "1100,99" not in page


def test_whats_new_paragraph_is_model_written_checked_translated_and_cached(tmp_path):
    public, client = archived_public(tmp_path), Model()
    data = {"recent_meetings": [{"date": "2026-07-22", "decisions": [{"title": "Décision modificative budgétaire", "vote": "unanimous"}]}],
            "pending": [], "dates_mentioned": []}
    summ = ChatModel("sum-model", client=client)
    r = whats_new.write_intro(public, data, summ, translator(client), ["en", "nl"])
    assert r["status"] == "ok" and not r["needs_review"]
    out = json.loads((public / "whats-new" / "intro.json").read_text())
    assert out["labels"]["human_reviewed"] is False and out["labels"]["produced_by"] == "AI model (sum-model)"
    assert set(out["texts"]) == {"fr", "en", "nl"} and out["texts"]["en"]["model"] == "tr-model"
    n = len(client.calls)
    assert whats_new.write_intro(public, data, summ, translator(client), ["en", "nl"])["status"] == "unchanged" and len(client.calls) == n


def test_a_paragraph_that_fails_its_checks_is_not_published():
    source = "Séance du 2026-07-22 : Budget (unanimous)."
    assert not all(whats_new.check_intro("Voici un paragraphe.\n\n- puce 1200000 euros", source).values())
    assert all(whats_new.check_intro("D’après les procès-verbaux, le conseil a voté le budget à l’unanimité. " * 4, source).values())


def test_the_site_shows_the_paragraph_with_its_disclosure_and_falls_back_to_french(tmp_path):
    public = archived_public(tmp_path)
    (public / "whats-new").mkdir()
    (public / "whats-new" / "whats-new.json").write_text(json.dumps({
        "latest": "2026-07-22", "recent_meetings": [], "feed_meetings": [], "coming_back": [], "pending": [], "dates_mentioned": [],
        "possibly_dropped": [], "watch": []}))
    (public / "whats-new" / "intro.json").write_text(json.dumps({"texts": {
        "fr": {"text": "Le conseil a voté le budget.", "model": "sum-model"},
        "en": {"text": "The council voted the budget.", "model": "tr-model"}}}))
    data = tmp_path / "data"; data.mkdir()
    out = build(tmp_path / "_site", public, data)
    en = (out / "en/whats-new/index.html").read_text()
    assert "In short" in en and "The council voted the budget." in en and "tr-model" in en and "AI translation" in en
    nl = (out / "nl/whats-new/index.html").read_text()
    assert "In het kort" in nl and 'lang="fr"' in nl and "Le conseil a voté le budget." in nl and "sum-model" in nl


def test_generate_runs_both_extras_and_never_sends_the_full_archived_minutes(tmp_path):
    public, client = archived_public(tmp_path), Model()
    (public / "meetings").mkdir(exist_ok=True)
    report = generate(public, ChatModel("sum-model", client=client), translator(client), ["en"])
    assert report["archive_facts"]["written"] == 1
    assert all("ETORE" not in c and "PECH" not in c for c in client.calls)
