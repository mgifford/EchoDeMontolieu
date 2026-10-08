import hashlib
import json

from echo_montolieu.fetch import Fetched
from echo_montolieu.verify import load_record, sha256_file, verify_local, verify_online

PDF = b"%PDF-1.4 fake bytes"
SHA = hashlib.sha256(PDF).hexdigest()
REC = {"document_id": SHA[:12], "source_url": "https://example.test/a.pdf", "source_sha256": SHA}


def test_sha256_file_matches_hashlib(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(PDF)
    assert sha256_file(f) == SHA


def test_verify_local_match_and_mismatch(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(PDF)
    assert verify_local(REC, f)["match"] is True
    f.write_bytes(PDF + b" changed")
    r = verify_local(REC, f)
    assert r["match"] is False and r["expected_sha256"] == SHA and r["actual_sha256"] != SHA


class FakeFetcher:
    def __init__(self, sha, status):
        self.sha, self.status, self.urls = sha, status, []

    def get(self, url, revalidate=True):
        self.urls.append(url)
        return Fetched(url, None, self.status, "t", self.sha)


def test_verify_online_unchanged_file_is_a_match_via_304():
    f = FakeFetcher(SHA, "not_modified")
    r = verify_online(REC, f)
    assert r["match"] and r["http_status"] == "not_modified" and f.urls == [REC["source_url"]]


def test_verify_online_detects_a_replaced_pdf():
    r = verify_online(REC, FakeFetcher("0" * 64, "fetched"))
    assert r["match"] is False and r["http_status"] == "fetched"


def test_load_record_reads_published_file(tmp_path):
    (tmp_path / "minutes").mkdir()
    (tmp_path / "minutes" / f"{REC['document_id']}.json").write_text(json.dumps(REC))
    assert load_record(tmp_path, REC["document_id"])["source_sha256"] == SHA
