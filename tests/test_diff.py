from echo_montolieu.diff import diff_versions


def ext(texts, sha, date="2024-04-04"):
    return {"sha256": sha * 64, "retrieved_at": "t", "meeting_date": {"value": date},
            "pages": [{"page": i, "text": t} for i, t in enumerate(texts, start=1)]}


def test_identical_text_but_different_file_is_reported_as_text_unchanged():
    d = diff_versions(ext(["a\nb"], "1"), ext(["a\nb"], "2"), 1, 2)
    assert d["summary"]["file_changed"] is True and d["summary"]["text_changed"] is False
    assert d["summary"]["pages"]["unchanged"] == 1
    assert d["document_diff"] == [] and "diff" not in d["pages"][0]


def test_changed_page_has_a_unified_diff_and_similarity():
    d = diff_versions(ext(["Budget 12 000 EUR\nfin"], "1"), ext(["Budget 15 000 EUR\nfin"], "2"), 1, 2)
    p = d["pages"][0]
    assert p["status"] == "changed" and 0 < p["similarity"] < 1
    assert "-Budget 12 000 EUR" in p["diff"] and "+Budget 15 000 EUR" in p["diff"]
    assert p["diff"][0] == "--- v1 page 1" and p["diff"][1] == "+++ v2 page 1"
    assert d["summary"]["text_changed"] is True and d["summary"]["pages"]["changed"] == 1


def test_whitespace_only_change_is_labelled_not_called_a_text_change():
    d = diff_versions(ext(["a  b\n c"], "1"), ext(["a b c"], "2"), 1, 2)
    assert d["pages"][0]["status"] == "whitespace_only" and d["summary"]["text_changed"] is False


def test_added_and_removed_pages():
    d = diff_versions(ext(["one", "two"], "1"), ext(["one", "two", "three"], "2"), 1, 2)
    assert [p["status"] for p in d["pages"]] == ["unchanged", "unchanged", "added"]
    assert d["summary"]["pages_before"] == 2 and d["summary"]["pages_after"] == 3
    d2 = diff_versions(ext(["one", "two"], "1"), ext(["one"], "2"), 1, 2)
    assert d2["pages"][1]["status"] == "removed"


def test_document_diff_survives_an_inserted_page_that_shifts_numbers():
    old = ext(["intro", "decision A", "closing"], "1")
    new = ext(["intro", "NEW PAGE", "decision A", "closing"], "2")
    d = diff_versions(old, new, 1, 2)
    added = [l for l in d["document_diff"] if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in d["document_diff"] if l.startswith("-") and not l.startswith("---")]
    assert "+NEW PAGE" in added
    assert not any("decision A" in l for l in removed)   # not reported as removed
    # The per-page view, matched by number, calls the shift three changes. That is why
    # the document-level diff exists: it shows the single insertion.
    assert [p["status"] for p in d["pages"]] == ["unchanged", "changed", "changed", "added"]


def test_meeting_date_change_is_surfaced():
    d = diff_versions(ext(["x"], "1", "2024-04-04"), ext(["x"], "2", "2024-04-05"), 1, 2)
    assert d["summary"]["meeting_date_before"] == "2024-04-04"
    assert d["summary"]["meeting_date_after"] == "2024-04-05"
