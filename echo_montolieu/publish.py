"""Maintainer-gated publication of redacted minutes.

Flow: sync (private extraction) -> redact (private, withheld) -> approve -> publish.
Output goes to public/redacted/. The faithful, unredacted record is published
separately by record.py to public/minutes/.

Safeguards, all enforced here and not assumed from earlier steps:
  * Approval is bound to the SHA-256 of the exact redacted file reviewed. If the
    file changes afterwards, the approval is stale and nothing is published.
  * Every OCR page marked needs_review needs an explicit decision: accepted by
    the reviewer, or withheld.
  * Before writing, the output is re-scanned for registered names and for
    unredacted names in private-transaction fields. Any hit blocks publication.
  * The public file is built field by field from a fixed list. Unknown fields
    (for example text_sparse or anything added later) are never copied.
  * Nothing here needs the pseudonym key; the registry is only read for names.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .privacy import (PublicFigures, _fold, _patterns, find_private_names)

# The faithful, unredacted record lives in public/minutes (see record.py). This
# gated, pseudonymised output is the safer base for aggregation services.
REDACTED_SUBDIR = "redacted"
PUBLIC_PAGE_FIELDS = ("page", "page_url", "method", "status", "note", "text")
WITHHELD_NOTE = "Withheld by the maintainer. See the original page at page_url."


class PublishError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _redacted_path(private_dir, stem):
    return Path(private_dir) / "redacted" / f"{stem}.json"


def approve(private_dir, stem, reviewer, withhold_pages=(), accept_pages=(), note=""):
    """Record a maintainer's approval of one redacted document."""
    if not (reviewer or "").strip():
        raise PublishError("a reviewer name is required")
    path = _redacted_path(private_dir, stem)
    if not path.exists():
        raise PublishError(f"no redacted file for '{stem}' (run redact first)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    withhold, accept = set(withhold_pages), set(accept_pages)
    if withhold & accept:
        raise PublishError(f"pages both withheld and accepted: {sorted(withhold & accept)}")
    pages = {p["page"] for p in doc["pages"]}
    unknown = (withhold | accept) - pages
    if unknown:
        raise PublishError(f"pages not in document: {sorted(unknown)}")
    undecided = [p["page"] for p in doc["pages"]
                 if p["status"] == "needs_review" and p["page"] not in withhold | accept]
    if undecided:
        raise PublishError(
            f"pages {undecided} need review: pass --accept-pages or --withhold-pages for each")
    approvals = _load(Path(private_dir) / "approvals.json", {})
    approvals[doc["privacy"]["document_id"]] = {
        "stem": stem,
        "redacted_sha256": _sha256_file(path),
        "approved_by": reviewer.strip(),
        "approved_at": _now(),
        "withheld_pages": sorted(withhold),
        "accepted_review_pages": sorted(accept),
        "note": note,
    }
    _write_private(Path(private_dir) / "approvals.json", approvals)
    return approvals[doc["privacy"]["document_id"]]


def _registry_pages(registry, doc_id):
    """page -> names the registry says were in a private-transaction field there."""
    out = {}
    for person in registry.values():
        for a in person["appearances"]:
            if a["document"] == doc_id:
                out.setdefault(a["page"], set()).update(person["names_seen"])
    return out


def check_no_leaks(public_doc, registry, figures, doc_id, doc_date):
    """Raise PublishError if the public document may expose a private person."""
    private_pages = _registry_pages(registry, doc_id)
    all_names = {n for person in registry.values() for n in person["names_seen"]}
    problems = []
    for page in public_doc["pages"]:
        text = page.get("text")
        if text is None:
            continue
        folded = _fold(text)
        for name in all_names:
            exempt = (figures.allows(name, doc_date)
                      and name not in private_pages.get(page["page"], set()))
            if not exempt and any(p.search(folded) for p in _patterns(name)):
                problems.append(f"page {page['page']}: a registered name is present")
        if find_private_names(text):
            problems.append(f"page {page['page']}: unredacted name in a labelled field")
    if problems:
        raise PublishError("blocked, possible exposure: " + "; ".join(sorted(set(problems))))


def build_public_document(doc, approval, include_text=True):
    withheld = set(approval["withheld_pages"])
    accepted = set(approval["accepted_review_pages"])
    pages = []
    for p in doc["pages"]:
        if p["page"] in withheld:
            pages.append({"page": p["page"], "page_url": p["page_url"],
                          "status": "withheld", "note": WITHHELD_NOTE})
            continue
        out = {k: p[k] for k in PUBLIC_PAGE_FIELDS if k in p}
        if not include_text:
            out.pop("text", None)
        if p["page"] in accepted:
            out["maintainer_accepted"] = True
        if "ocr" in p:
            out["ocr"] = {k: p["ocr"][k] for k in ("mean_conf", "words") if k in p["ocr"]}
        pages.append(out)
    return {
        "document_id": doc["privacy"]["document_id"],
        "source_url": doc["source_url"],
        "source_sha256": doc["sha256"],
        "retrieved_at": doc["retrieved_at"],
        "meeting_date": doc.get("meeting_date"),
        "extractor": doc.get("extractor"),
        "privacy": {
            "scope": doc["privacy"]["scope"],
            "detection": doc["privacy"]["detection"],
            "reviewed_by": approval["approved_by"],
            "reviewed_at": approval["approved_at"],
        },
        "labels": {
            "machine_generated": True,
            "verify_at_source": True,
            "text_included": include_text,
        },
        "pages": pages,
    }


def publish(private_dir, public_dir, figures=None, include_text=True):
    """Publish every approved, unchanged document. Returns a report."""
    figures = figures or PublicFigures([])
    private, public = Path(private_dir), Path(public_dir) / REDACTED_SUBDIR
    approvals = _load(private / "approvals.json", {})
    registry = _load(private / "people.json", {})
    report = {"published": [], "stale": [], "blocked": []}
    for doc_id, approval in approvals.items():
        path = _redacted_path(private, approval["stem"])
        if not path.exists() or _sha256_file(path) != approval["redacted_sha256"]:
            report["stale"].append(approval["stem"])
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        public_doc = build_public_document(doc, approval, include_text)
        doc_date = (doc.get("meeting_date") or {}).get("value")
        try:
            check_no_leaks(public_doc, registry, figures, doc_id, doc_date)
        except PublishError as exc:
            report["blocked"].append({"stem": approval["stem"], "reason": str(exc)})
            continue
        out_dir = public / "minutes"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{doc_id}.json").write_text(
            json.dumps(public_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["published"].append(approval["stem"])
    _write_public_index(public)
    return report


def _write_public_index(public):
    out_dir = public / "minutes"
    entries = []
    if out_dir.exists():
        for f in sorted(out_dir.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            entries.append({"document_id": d["document_id"], "source_url": d["source_url"],
                            "meeting_date": d["meeting_date"], "pages": len(d["pages"]),
                            "withheld_pages": sum(p["status"] == "withheld" for p in d["pages"]),
                            "file": f"minutes/{f.name}"})
    public.mkdir(parents=True, exist_ok=True)
    (public / "index.json").write_text(
        json.dumps({"count": len(entries), "documents": entries}, ensure_ascii=False, indent=2)
        + "\n", encoding="utf-8")


def unpublish(private_dir, public_dir, stem):
    """Remove a document's public file and its approval."""
    private, public = Path(private_dir), Path(public_dir) / REDACTED_SUBDIR
    approvals = _load(private / "approvals.json", {})
    doc_ids = [d for d, a in approvals.items() if a["stem"] == stem]
    if not doc_ids:
        raise PublishError(f"no approval recorded for '{stem}'")
    for d in doc_ids:
        (public / "minutes" / f"{d}.json").unlink(missing_ok=True)
        del approvals[d]
    _write_private(private / "approvals.json", approvals)
    _write_public_index(public)
    return doc_ids


def status(private_dir, public_dir):
    """Per-document state for the maintainer: redacted, approved, published, stale."""
    private, public = Path(private_dir), Path(public_dir) / REDACTED_SUBDIR
    approvals = _load(private / "approvals.json", {})
    by_stem = {a["stem"]: (d, a) for d, a in approvals.items()}
    rows = []
    for f in sorted((private / "redacted").glob("*.json")) if (private / "redacted").exists() else []:
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc_id = doc["privacy"]["document_id"]
        d_a = by_stem.get(f.stem)
        if not d_a:
            state = "awaiting_review"
        elif _sha256_file(f) != d_a[1]["redacted_sha256"]:
            state = "approval_stale"
        elif (public / "minutes" / f"{doc_id}.json").exists():
            state = "published"
        else:
            state = "approved_not_published"
        rows.append({"stem": f.stem, "document_id": doc_id, "state": state,
                     "needs_review_pages": [p["page"] for p in doc["pages"]
                                            if p["status"] == "needs_review"],
                     "redactions": doc["privacy"]["redactions"]})
    return rows
