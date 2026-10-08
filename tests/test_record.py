import json

from echo_montolieu.record import publish_record
from echo_montolieu.versions import document_id

URL = "https://example.test/a.pdf"
DOC = document_id(URL)

# Fictional names. The point of these tests: the record is faithful, so names stay.
TEXT_1 = "Etaient présents : Hélène MARTEL, Paul DURANT.\nL’an deux mille vingt-quatre  "
TEXT_2 = "Vendeur(s) : DURANT Paul\nPrix de vente : 90 000,00 EUR\nM² : 1861M?"


def make_private(tmp_path, with_failure=False):
    private = tmp_path / "private"
    (private / "extractions").mkdir(parents=True)
    ext = {
        "source_url": "https://example.test/a.pdf", "sha256": "ab" * 32,
        "retrieved_at": "2026-10-08T00:00:00+00:00", "page_count": 2, "size_bytes": 12345,
        "extractor": {"pymupdf": "x"},
        "meeting_date": {"value": "2024-09-18", "status": "tentative", "source": "s"},
        "pages": [
            {"page": 1, "page_url": "https://example.test/a.pdf#page=1",
             "method": "text_layer", "status": "machine_extracted", "note": None,
             "image_area_fraction": 0.0, "text": TEXT_1},
            {"page": 2, "page_url": "https://example.test/a.pdf#page=2",
             "method": "tesseract", "status": "needs_review", "note": "OCR",
             "image_area_fraction": 0.6, "text": TEXT_2, "text_sparse": "90 000 1861",
             "ocr": {"mean_conf": 58.7, "min_conf": 0, "low_word_fraction": 0.46, "words": 142}},
        ]}
    (private / "extractions" / "a.json").write_text(json.dumps(ext, ensure_ascii=False))
    index = {"https://example.test/a.pdf": {
        "filename": "a.pdf", "extraction": "extractions/a.json", "draft_suspected": False,
        "pdf_sha256": "ab" * 32, "retrieved_at": "2026-10-08T00:00:00+00:00",
        "http": {"etag": '"abc"', "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        "public_release": "withheld"}}
    if with_failure:
        index["https://example.test/bad.pdf"] = {"filename": "bad.pdf", "error": "boom"}
    (private / "index.json").write_text(json.dumps(index))
    return private


def load(public, doc=DOC):
    return json.loads((public / "minutes" / f"{doc}.json").read_text(encoding="utf-8"))


def test_text_is_reproduced_exactly_names_and_ocr_errors_included(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    publish_record(private, public)
    pages = load(public)["pages"]
    assert pages[0]["text"] == TEXT_1          # incl. curly apostrophe, double space, names
    assert pages[1]["text"] == TEXT_2          # incl. the OCR error "1861M?", not corrected
    assert pages[1]["text_sparse"] == "90 000 1861"
    assert "MARTEL" in json.dumps(load(public), ensure_ascii=False)


def test_record_is_labelled_and_links_to_each_original_page(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    publish_record(private, public)
    rec = load(public)
    assert rec["labels"]["redacted"] is False and rec["labels"]["faithful_transcription"]
    assert rec["labels"]["verify_at_source"] is True
    assert rec["source_url"] == "https://example.test/a.pdf"
    assert rec["pages"][1]["page_url"].endswith("#page=2")
    assert rec["pages"][1]["status"] == "needs_review"
    assert rec["pages"][1]["ocr"]["mean_conf"] == 58.7   # uncertainty is published, not hidden
    assert rec["meeting_date"]["status"] == "tentative"


def test_only_known_fields_are_copied(tmp_path):
    private = make_private(tmp_path)
    f = private / "extractions" / "a.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["pages"][0]["internal_debug"] = "do not publish"
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    publish_record(private, tmp_path / "public")
    assert "internal_debug" not in json.dumps(load(tmp_path / "public"))


def test_no_text_option_keeps_links_and_status_only(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    publish_record(private, public, include_text=False)
    rec = load(public)
    assert all("text" not in p and "text_sparse" not in p for p in rec["pages"])
    assert rec["pages"][0]["page_url"] and rec["labels"]["text_included"] is False


def test_index_lists_documents_and_failures_are_reported_not_published(tmp_path):
    private, public = make_private(tmp_path, with_failure=True), tmp_path / "public"
    report = publish_record(private, public)
    assert report["published"] == 1 and report["skipped_failed"] == ["https://example.test/bad.pdf"]
    idx = json.loads((public / "index.json").read_text(encoding="utf-8"))
    d = idx["documents"][0]
    assert idx["count"] == 1 and d["ocr_pages"] == [2] and d["needs_review_pages"] == [2]
    assert d["file"] == f"minutes/{DOC}.json"


def test_private_files_are_never_written_to_public(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    (private / "people.json").write_text('{"M-1": {"names_seen": ["SECRET Name"]}}')
    (private / "pseudonym.key").write_text("k" * 40)
    publish_record(private, public)
    blob = "".join(p.read_text(encoding="utf-8") for p in public.rglob("*.json"))
    assert "SECRET" not in blob and "kkkkkkkk" not in blob and "public_release" not in blob


def test_record_carries_hash_size_validators_and_how_to_verify(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    publish_record(private, public)
    rec = load(public)
    assert rec["source_sha256"] == "ab" * 32 and rec["source_bytes"] == 12345
    assert rec["source_http"]["etag"] == '"abc"'
    assert rec["verify"]["algorithm"] == "SHA-256"
    assert "shasum -a 256" in rec["verify"]["local_file"]
    assert "not copied" in rec["verify"]["about"]


# ---- versions -----------------------------------------------------------------------


def add_version(private, text2, sha="cd"):
    """Make the indexed document a two-version one: v1 (the existing) superseded by v2."""
    ext1 = json.loads((private / "extractions" / "a.json").read_text(encoding="utf-8"))
    (private / "versions" / "a").mkdir(parents=True)
    (private / "versions" / "a" / "v1.json").write_text(json.dumps(ext1, ensure_ascii=False))
    ext2 = json.loads(json.dumps(ext1))
    ext2["sha256"] = sha * 32
    ext2["retrieved_at"] = "2026-11-01T00:00:00+00:00"
    ext2["pages"][0]["text"] = text2
    (private / "extractions" / "a.json").write_text(json.dumps(ext2, ensure_ascii=False))
    idx = json.loads((private / "index.json").read_text())
    e = idx[URL]
    e["versions"] = [
        {"version": 1, "sha256": "ab" * 32, "size_bytes": 111, "retrieved_at": "2026-10-08T00:00:00+00:00",
         "http": {"etag": None, "last_modified": "Mon"}, "extraction": "versions/a/v1.json",
         "superseded_at": "2026-11-01T00:00:00+00:00"},
        {"version": 2, "sha256": sha * 32, "size_bytes": 222, "retrieved_at": "2026-11-01T00:00:00+00:00",
         "http": {"etag": None, "last_modified": "Tue"}, "extraction": "extractions/a.json",
         "superseded_at": None}]
    e["current_version"] = 2
    (private / "index.json").write_text(json.dumps(idx))


def test_document_id_is_stable_across_versions(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    publish_record(private, public)
    first_id = json.loads((public / "index.json").read_text())["documents"][0]["document_id"]
    add_version(private, "Séance modifiée.")
    publish_record(private, public)
    assert json.loads((public / "index.json").read_text())["documents"][0]["document_id"] == first_id == DOC


def test_all_versions_diff_and_current_are_published(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    add_version(private, "Séance modifiée.")
    report = publish_record(private, public)
    assert report["versions_published"] == 1
    cur = load(public)
    assert cur["version"] == 2 and cur["is_current"] and cur["pages"][0]["text"] == "Séance modifiée."
    v1 = json.loads((public / "minutes" / DOC / "v1.json").read_text(encoding="utf-8"))
    assert v1["version"] == 1 and v1["is_current"] is False and v1["superseded_at"]
    assert v1["pages"][0]["text"] == TEXT_1                 # the first version, exactly
    assert v1["source_sha256"] == "ab" * 32 and cur["source_sha256"] == "cd" * 32
    d = json.loads((public / "minutes" / DOC / "diff-v1-v2.json").read_text(encoding="utf-8"))
    assert d["summary"]["text_changed"] and d["pages"][0]["status"] == "changed"
    assert any(l.startswith("+Séance modifiée") for l in d["pages"][0]["diff"])


def test_version_list_links_every_version_and_diff(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    add_version(private, "x")
    publish_record(private, public)
    vs = load(public)["versions"]
    assert [v["version"] for v in vs] == [1, 2] and [v["is_current"] for v in vs] == [False, True]
    assert vs[0]["record"] == f"minutes/{DOC}/v1.json" and vs[0]["diff_from_previous"] is None
    assert vs[1]["record"] == f"minutes/{DOC}.json"
    assert vs[1]["diff_from_previous"] == f"minutes/{DOC}/diff-v1-v2.json"
    assert vs[0]["source_sha256"] == "ab" * 32 and vs[0]["last_modified"] == "Mon"
    idx = json.loads((public / "index.json").read_text())["documents"][0]
    assert idx["version"] == 2 and idx["versions"] == 2


def test_single_version_document_has_a_one_item_version_list(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    publish_record(private, public)
    rec = load(public)
    assert [v["version"] for v in rec["versions"]] == [1] and rec["is_current"] is True
    assert not (public / "minutes" / DOC).exists()          # no old versions, no diffs


def test_stale_files_from_earlier_runs_are_removed(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    (public / "minutes").mkdir(parents=True)
    (public / "minutes" / "oldoldoldold.json").write_text("{}")
    publish_record(private, public)
    assert not (public / "minutes" / "oldoldoldold.json").exists() and load(public)


def test_no_text_option_removes_text_from_old_versions_and_diffs_too(tmp_path):
    private, public = make_private(tmp_path), tmp_path / "public"
    add_version(private, "Séance modifiée.")
    publish_record(private, public, include_text=False)
    blob = "".join(p.read_text(encoding="utf-8") for p in (public / "minutes").rglob("*.json"))
    assert "Séance modifiée" not in blob and "MARTEL" not in blob and "Prix de vente" not in blob
    d = json.loads((public / "minutes" / DOC / "diff-v1-v2.json").read_text(encoding="utf-8"))
    assert "document_diff" not in d and d["summary"]["text_changed"] is True
