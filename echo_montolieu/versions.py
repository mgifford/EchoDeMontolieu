"""Version bookkeeping shared by sync and the public record."""
import hashlib


def document_id(url):
    """Stable id for a document: derived from its URL, so it survives new versions."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def ensure_versions(entry):
    """Index entries written before versioning existed become version 1."""
    if "versions" not in entry and "error" not in entry:
        entry["versions"] = [{
            "version": 1, "sha256": entry["pdf_sha256"], "size_bytes": None,
            "retrieved_at": entry["retrieved_at"], "http": entry.get("http"),
            "extraction": entry["extraction"], "superseded_at": None}]
        entry["current_version"] = 1
