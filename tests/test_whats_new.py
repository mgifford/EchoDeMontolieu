import json
from echo_montolieu import whats_new as wn


def test_dates_are_read_from_french_text_and_the_past_is_skipped():
    assert wn.mentioned_dates("Les élections auront lieu le 27 septembre 2026.", "2026-06-05") == ["2026-09-27"]
    assert wn.mentioned_dates("Réunion le 1er juillet.", "2026-06-05") == ["2026-07-01"]
    assert wn.mentioned_dates("La commission réunie le 9 avril a analysé.", "2026-04-13") == []      # earlier this year: the past
    assert wn.mentioned_dates("Le 31 février est impossible.", "2026-01-05") == []
    assert wn.mentioned_dates("Vote en 2020 le 3 mars 2020.", "2026-06-05") == []


def _item(i, title, topics=(), sensitive=False, followups=(), text=""):
    return {"id": i, "title": title, "pages": [1, 1], "topics": list(topics), "vote_result": "unanimous", "sensitive": sensitive,
            "followups": list(followups), "text": text}


def test_digest_lists_recent_decisions_but_never_private_sales():
    m = lambda d, items: {"folder": d, "meeting": {"date": d, "source_url": "https://example.org/" + d, "items": items}}
    meetings = [m("2026-05-01", [_item("a", "Budget", ["finances"])]),
                m("2026-06-01", [_item("b", "Vente d'une maison", sensitive=True), _item("c", "PLU", ["urbanisme"],
                    followups=[{"type": "deferred", "sentence": "Le vote est reporté."}], text="Consultation jusqu'au 30 septembre.")])]
    result = {"threads": [{"title": "PLU", "meetings": ["2026-05-01", "2026-06-01"], "n_meetings": 2, "status": "returned", "possibly_dropped": False,
                           "pending": [], "later_meetings": 0}], "standing": {}, "meeting_dates": []}
    d = wn.build(meetings, result)
    assert d["latest"] == "2026-06-01" and [r["date"] for r in d["recent_meetings"]] == ["2026-06-01", "2026-05-01"]
    latest = d["recent_meetings"][0]
    assert [x["title"] for x in latest["decisions"]] == ["PLU"] and latest["sale_notices"] == 1
    assert d["pending"][0]["sentence"] == "Le vote est reporté." and d["dates_mentioned"][0]["mentioned"] == "2026-09-30"
    assert d["coming_back"][0]["title"] == "PLU" and {w["topic"] for w in d["watch"]} == {"finances", "urbanisme"}
    assert wn.build([], {"threads": []})["latest"] is None


def test_clip_cuts_at_a_word_and_keeps_the_stretch_around_a_date():
    text = "Une phrase assez longue pour dépasser la limite fixée, " * 6 + "jusqu'au 15 septembre."
    short = wn.clip(text, 80)
    assert len(short) <= 81 and short.endswith("…") and not short[:-1].endswith(" ") and text.startswith(short[:-1])
    window = wn.clip(text, 80, around=len(text))
    assert window.startswith("…") and window.endswith("septembre.")
    assert wn.clip("Courte.", 80) == "Courte."


def test_table_rows_and_headings_are_not_taken_for_sentences_but_short_dated_sentences_are():
    grades = "Grade au 1/1/2026 Nombre Durée horaire Nouveaux grades Nombre Durée horaire Filière technique Adjoint technique principal 1 2 3 35h 35 h 2 à 35 h 1 à 29/35"
    assert not wn.looks_like_prose(grades)
    assert not wn.looks_like_prose("Code Libellé Budget total Réalisé total BR2 Fonctionnement.")
    assert wn.looks_like_prose("Consultation jusqu'au 30 septembre.")
    assert wn.looks_like_prose("Les élections sénatoriales 2026 auront lieu le dimanche 27 septembre 2026.")


class FakeTranslator:
    model = "fake/model"

    def __init__(self, fail=()):
        self.calls, self.fail = [], fail

    def translate_many(self, texts, lang, names=()):
        self.calls.append((lang, list(texts)))
        return [(f"[{lang}] {t}", t not in self.fail, [] if t not in self.fail else ["numbers_preserved"]) for t in texts]


def _digest():
    m = lambda d, items: {"folder": d, "meeting": {"date": d, "source_url": "https://example.org/" + d, "items": items}}
    meetings = [m("2026-06-01", [_item("c", "PLU", ["urbanisme"], followups=[{"type": "deferred", "sentence": "Le vote est reporté."}],
                                       text="Consultation jusqu'au 30 septembre.")])]
    return wn.build(meetings, {"threads": [], "standing": {}, "meeting_dates": []})


def test_translations_are_written_once_failed_segments_are_left_out_and_nothing_is_resent(tmp_path):
    data = _digest()
    t = FakeTranslator(fail=("Le vote est reporté.",))
    report = wn.write_translations(tmp_path, data, t, ["en", "nl"])
    saved = json.loads((tmp_path / "whats-new/translations.json").read_text(encoding="utf-8"))
    en = saved["texts"]["en"]
    assert en[wn.string_key("PLU")] == "[en] PLU" and wn.string_key("Le vote est reporté.") not in en
    assert report["failed"] == 2 and report["needs_review"] and saved["labels"]["human_reviewed"] is False
    again = FakeTranslator(fail=("Le vote est reporté.",))
    wn.write_translations(tmp_path, data, again, ["en"])
    assert again.calls == [("en", ["Le vote est reporté."])]            # only the one that failed is tried again
