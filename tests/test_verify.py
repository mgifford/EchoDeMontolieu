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
    def __init__(self, sha, status, cached=None, head=None):
        self.sha, self.status, self.urls = sha, status, []
        self._cached, self._head = cached, head

    def cached_sha256(self, url):
        return self._cached

    def changed_on_server(self, url):
        return self._head

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


def test_load_record_can_return_an_older_version_and_refuses_unknown_ones(tmp_path):
    import pytest
    (tmp_path / "minutes" / "d").mkdir(parents=True)
    cur = {**REC, "document_id": "d", "version": 2, "is_current": True}
    (tmp_path / "minutes" / "d.json").write_text(json.dumps(cur))
    (tmp_path / "minutes" / "d" / "v1.json").write_text(
        json.dumps({**REC, "document_id": "d", "version": 1, "is_current": False,
                    "source_sha256": "0" * 64}))
    assert load_record(tmp_path, "d")["version"] == 2
    assert load_record(tmp_path, "d", 2)["version"] == 2
    assert load_record(tmp_path, "d", 1)["source_sha256"] == "0" * 64
    with pytest.raises(FileNotFoundError):
        load_record(tmp_path, "d", 7)


def test_online_verification_of_a_superseded_version_is_refused():
    import pytest
    with pytest.raises(ValueError, match="only holds the current version"):
        verify_online({**REC, "is_current": False}, FakeFetcher(SHA, "not_modified"))


def test_verify_online_trusts_unchanged_headers_without_downloading():
    f = FakeFetcher("0" * 64, "fetched", cached=SHA, head=False)
    r = verify_online(REC, f)
    assert r["match"] is True and r["http_status"] == "headers_unchanged" and f.urls == []


def test_verify_online_downloads_when_headers_changed_or_unknown():
    for head in (True, None):
        f = FakeFetcher("0" * 64, "changed", cached=SHA, head=head)
        r = verify_online(REC, f)
        assert r["match"] is False and f.urls == [REC["source_url"]]
    f = FakeFetcher(SHA, "fetched", cached=None, head=False)       # nothing cached to compare with
    assert verify_online(REC, f)["http_status"] == "fetched"
