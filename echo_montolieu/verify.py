"""Check that a record's text came from the same PDF that is (or was) on the site.

SHA-256 is used, not MD5: MD5 is broken for collision resistance, and nothing
is gained from the shorter digest here.
"""
import hashlib
import json
from pathlib import Path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_record(public_dir, document_id):
    path = Path(public_dir) / "minutes" / f"{document_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no published record {document_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_local(record, pdf_path):
    """Offline: does this PDF file match the one the record's text came from?"""
    actual = sha256_file(pdf_path)
    return {"document_id": record["document_id"], "check": "local file",
            "match": actual == record["source_sha256"],
            "expected_sha256": record["source_sha256"], "actual_sha256": actual}


def verify_online(record, fetcher):
    """Polite check of the file on the site now (conditional request, so an unchanged
    file costs a 304). A mismatch means the Mairie replaced the PDF after we read it."""
    fetched = fetcher.get(record["source_url"])
    return {"document_id": record["document_id"], "check": "site now",
            "http_status": fetched.status,
            "match": fetched.sha256 == record["source_sha256"],
            "expected_sha256": record["source_sha256"], "actual_sha256": fetched.sha256}
