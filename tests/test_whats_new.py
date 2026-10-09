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
