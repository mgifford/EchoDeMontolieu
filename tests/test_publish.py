import json

import pytest

from echo_montolieu import publish as pub
from echo_montolieu.privacy import Pseudonymiser, PublicFigures, redact_extraction

KEY = "k" * 40
# All names are fictional.
SALE = "Vendeur(s) : DURANT Paul, DURANT Léa\nPrix : 90 000 EUR\nAcquéreur : SAFER"


def extraction(sha="ab" * 32):
    return {
        "source_url": "https://example.test/a.pdf", "sha256": sha,
        "retrieved_at": "2026-10-08T00:00:00+00:00", "page_count": 3,
        "extractor": {"pymupdf": "x"}, "meeting_date": {"value": "2024-09-18",
                                                       "status": "tentative", "source": "s"},
        "pages": [
            {"page": 1, "page_url": "https://example.test/a.pdf#page=1", "method": "text_layer",
             "status": "machine_extracted", "note": None, "text": "Séance du conseil.",
             "image_area_fraction": 0.0},
            {"page": 2, "page_url": "https://example.test/a.pdf#page=2", "method": "tesseract",
             "status": "needs_review", "note": "OCR", "text": SALE,
             "text_sparse": "DURANT Paul 90 000", "ocr": {"mean_conf": 70.0, "min_conf": 3,
                                                          "low_word_fraction": 0.2, "words": 20}},
            {"page": 3, "page_url": "https://example.test/a.pdf#page=3", "method": "tesseract",
             "status": "needs_review", "note": "OCR", "text": "Tableau illisible",
             "ocr": {"mean_conf": 40.0, "words": 3}},
        ],
    }


@pytest.fixture
def env(tmp_path):
    private, public = tmp_path / "private", tmp_path / "public"
    p = Pseudonymiser(KEY, private)
    red = redact_extraction(extraction(), p)
    (private / "redacted").mkdir(parents=True, exist_ok=True)
    (private / "redacted" / "doc.json").write_text(json.dumps(red), encoding="utf-8")
    return private, public


def approve(private, **kw):
    args = dict(reviewer="maintainer", accept_pages=[2], withhold_pages=[3])
    args.update(kw)
    return pub.approve(private, "doc", **args)


def test_nothing_is_published_without_approval(env):
    private, public = env
    assert pub.publish(private, public)["published"] == []
    assert not (public / "redacted" / "minutes").exists() or not list((public / "redacted" / "minutes").glob("*.json"))
    assert pub.status(private, public)[0]["state"] == "awaiting_review"


def test_approve_requires_reviewer_and_a_decision_for_every_review_page(env):
    private, _ = env
    with pytest.raises(pub.PublishError, match="reviewer"):
        approve(private, reviewer=" ")
    with pytest.raises(pub.PublishError, match=r"\[2, 3\]|\[3\]|need review"):
        pub.approve(private, "doc", "m")  # no decisions at all
    with pytest.raises(pub.PublishError, match="both"):
        approve(private, accept_pages=[2], withhold_pages=[2, 3])
    with pytest.raises(pub.PublishError, match="not in document"):
        approve(private, withhold_pages=[3, 99])
    with pytest.raises(pub.PublishError, match="no redacted file"):
        pub.approve(private, "missing", "m")


def test_published_file_has_no_names_withholds_pages_and_labels_review(env):
    private, public = env
    approve(private, note="checked page 2 against the PDF")
    report = pub.publish(private, public)
    assert report["published"] == ["doc"] and not report["blocked"]
    out = json.loads(next((public / "redacted" / "minutes").glob("*.json")).read_text(encoding="utf-8"))
    blob = json.dumps(out, ensure_ascii=False)
    for secret in ("DURANT", "Léa", "text_sparse", "low_word_fraction", "checked page 2"):
        assert secret not in blob
    p1, p2, p3 = out["pages"]
    assert p1["status"] == "machine_extracted" and "text" in p1
    assert p2["status"] == "needs_review" and p2["maintainer_accepted"] is True
    assert "SAFER" in p2["text"]
    assert p3["status"] == "withheld" and "text" not in p3 and p3["page_url"].endswith("#page=3")
    assert out["privacy"]["reviewed_by"] == "maintainer"
    assert out["labels"]["machine_generated"] is True
    idx = json.loads((public / "redacted" / "index.json").read_text(encoding="utf-8"))
    assert idx["count"] == 1 and idx["documents"][0]["withheld_pages"] == 1


def test_no_text_option_publishes_metadata_and_links_only(env):
    private, public = env
    approve(private)
    pub.publish(private, public, include_text=False)
    out = json.loads(next((public / "redacted" / "minutes").glob("*.json")).read_text(encoding="utf-8"))
    assert all("text" not in p for p in out["pages"]) and out["labels"]["text_included"] is False


def test_changing_the_reviewed_file_makes_approval_stale(env):
    private, public = env
    approve(private)
    f = private / "redacted" / "doc.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["pages"][0]["text"] += " modifié"
    f.write_text(json.dumps(d), encoding="utf-8")
    report = pub.publish(private, public)
    assert report["stale"] == ["doc"] and report["published"] == []
    assert pub.status(private, public)[0]["state"] == "approval_stale"


def test_leak_check_blocks_a_registered_name_left_in_the_text(env):
    private, public = env
    f = private / "redacted" / "doc.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["pages"][0]["text"] = "Courrier de Paul DURANT reçu."   # a name the redaction missed
    f.write_text(json.dumps(d), encoding="utf-8")
    approve(private)
    report = pub.publish(private, public)
    assert report["published"] == [] and "registered name" in report["blocked"][0]["reason"]
    assert not list((public / "redacted" / "minutes").glob("*.json")) if (public / "redacted" / "minutes").exists() else True


def test_leak_check_blocks_an_unredacted_labelled_field(env):
    private, public = env
    f = private / "redacted" / "doc.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["pages"][0]["text"] = "Vendeur(s) : MOREAU Jeanne"        # never registered
    f.write_text(json.dumps(d), encoding="utf-8")
    approve(private)
    assert "labelled field" in pub.publish(private, public)["blocked"][0]["reason"]


def test_allow_listed_official_may_appear_but_not_on_their_private_sale_page(env):
    private, public = env
    reg = json.loads((private / "people.json").read_text(encoding="utf-8"))
    figures = PublicFigures([{"name": "DURANT Paul", "category": "elected_official",
                              "basis": "https://example.test/attendance"}])
    f = private / "redacted" / "doc.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["pages"][0]["text"] = "Présents : Paul DURANT, maire."
    f.write_text(json.dumps(d), encoding="utf-8")
    approve(private)
    assert pub.publish(private, public, figures)["published"] == ["doc"]
    # Now put the same name on the page where the registry says it was a private sale.
    d["pages"][1]["text"] = "Séance. Paul DURANT a vendu."
    f.write_text(json.dumps(d), encoding="utf-8")
    approve(private)  # re-approve the changed file
    assert pub.publish(private, public, figures)["blocked"]
    assert reg  # registry was populated by the redaction step


def test_unpublish_removes_file_and_revokes_approval(env):
    private, public = env
    approve(private)
    pub.publish(private, public)
    assert pub.unpublish(private, public, "doc")
    assert not list((public / "redacted" / "minutes").glob("*.json"))
    assert json.loads((public / "redacted" / "index.json").read_text(encoding="utf-8"))["count"] == 0
    assert pub.publish(private, public)["published"] == []  # approval revoked
    with pytest.raises(pub.PublishError):
        pub.unpublish(private, public, "doc")


def test_status_reports_each_state(env):
    private, public = env
    assert pub.status(private, public)[0]["needs_review_pages"] == [2, 3]
    approve(private)
    assert pub.status(private, public)[0]["state"] == "approved_not_published"
    pub.publish(private, public)
    assert pub.status(private, public)[0]["state"] == "published"
