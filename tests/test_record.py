import json

from echo_montolieu.record import publish_record

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
        "http": {"etag": '"abc"', "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        "public_release": "withheld"}}
    if with_failure:
        index["https://example.test/bad.pdf"] = {"filename": "bad.pdf", "error": "boom"}
    (private / "index.json").write_text(json.dumps(index))
    return private


def load(public, doc="abababababab"):
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
    assert d["file"] == "minutes/abababababab.json"


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
