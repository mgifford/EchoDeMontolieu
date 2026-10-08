"""Faithful public record of the council minutes: page text and links, unredacted.

This reproduces what the Mairie published. Nothing is redacted, rewritten or
corrected. What is added is provenance and honesty about extraction quality:
how each page's text was obtained, OCR confidence, and a link to the original
page. Protection of individuals is applied later, where data is aggregated
(search, MCP, derived datasets), not here.

Versions: when the Mairie replaces a PDF, every version stays in the record.
  minutes/<id>.json                  the current version, with a list of all versions
  minutes/<id>/v<N>.json             each superseded version, complete
  minutes/<id>/diff-v<N>-v<M>.json   what changed between consecutive versions
<id> comes from the document's URL, so it does not change when the file does.
"""
import json
from pathlib import Path

from . import disclosure
from .diff import diff_versions
from .versions import document_id, ensure_versions

PAGE_FIELDS = ("page", "page_url", "method", "status", "note", "image_area_fraction",
               "text", "text_sparse", "ocr")
SPARSE_NOTE = ("text_sparse is an alternate OCR reading. It finds more figures in "
               "tables but does not keep rows and columns together.")


def build_record(extraction, index_entry=None, include_text=True, doc_id=None,
                 version=1, superseded_at=None):
    index_entry = index_entry or {}
    pages = []
    for p in extraction["pages"]:
        out = {k: p[k] for k in PAGE_FIELDS if k in p}
        if not include_text:
            out.pop("text", None)
            out.pop("text_sparse", None)
        pages.append(out)
    return {
        "document_id": doc_id or document_id(extraction["source_url"]),
        "version": version,
        "is_current": superseded_at is None,
        "superseded_at": superseded_at,
        "filename": index_entry.get("filename"),
        "source_url": extraction["source_url"],
        "source_sha256": extraction["sha256"],
        "source_bytes": extraction.get("size_bytes"),
        "source_http": index_entry.get("http"),
        "origin": index_entry.get("origin"),
        "verify": ({
            "algorithm": "SHA-256",
            "about": "This minutes file is no longer on the Mairie's site. source_url is the Internet "
                     "Archive capture (the official copy); origin.mirror_url is our copy of the same "
                     "file. source_sha256 is the hash of the file as downloaded from that capture.",
            "local_file": "shasum -a 256 FILE.pdf",
            "against_site": "not applicable: an archived capture does not change; compare a file with source_sha256",
        } if index_entry.get("origin") else {
            "algorithm": "SHA-256",
            "about": "source_sha256 is the hash of the PDF exactly as downloaded from "
                     "source_url on retrieved_at. The PDF itself is not copied here.",
            "local_file": "shasum -a 256 FILE.pdf",
            "against_site": "python -m echo_montolieu verify DOCUMENT_ID",
        }),
        "retrieved_at": extraction["retrieved_at"],
        "meeting_date": extraction.get("meeting_date"),
        "draft_suspected": index_entry.get("draft_suspected"),
        "page_count": extraction["page_count"],
        "extractor": extraction.get("extractor"),
        "labels": {
            "machine_generated": True,
            "faithful_transcription": True,
            "redacted": False,
            "verify_at_source": True,
            "text_included": include_text,
            "text_sparse_note": SPARSE_NOTE,
            **disclosure.labels("extraction"),
        },
        "pages": pages,
    }


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish_record(private_dir, public_dir, include_text=True):
    private, public = Path(private_dir), Path(public_dir)
    index_path = private / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    out_dir = public / "minutes"
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = set()
    report = {"published": 0, "versions_published": 0, "skipped_failed": [], "documents": []}

    def emit(path, data):
        _write(path, data)
        produced.add(path.resolve())

    for url, entry in index.items():
        if "error" in entry:
            report["skipped_failed"].append(url)
            continue
        ensure_versions(entry)
        doc_id = document_id(url)
        versions = entry["versions"]
        extractions = {v["version"]: json.loads(
            (private / v["extraction"]).read_text(encoding="utf-8")) for v in versions}

        summary = []
        for v in versions:
            k = v["version"]
            summary.append({
                "version": k,
                "is_current": v["superseded_at"] is None,
                "source_sha256": v["sha256"],
                "source_bytes": v.get("size_bytes"),
                "retrieved_at": v["retrieved_at"],
                "last_modified": (v.get("http") or {}).get("last_modified"),
                "superseded_at": v["superseded_at"],
                "record": (f"minutes/{doc_id}.json" if v["superseded_at"] is None
                           else f"minutes/{doc_id}/v{k}.json"),
                "diff_from_previous": (f"minutes/{doc_id}/diff-v{k - 1}-v{k}.json"
                                       if k > 1 else None),
            })
            meta = {**entry, "http": v.get("http")}
            rec = build_record(extractions[k], meta, include_text, doc_id, k, v["superseded_at"])
            if v["superseded_at"] is None:
                current_rec = rec
            else:
                emit(out_dir / doc_id / f"v{k}.json", rec)
                report["versions_published"] += 1
            if k > 1:
                d = diff_versions(extractions[k - 1], extractions[k], k - 1, k)
                if not include_text:
                    d.pop("document_diff")
                    for p in d["pages"]:
                        p.pop("diff", None)
                emit(out_dir / doc_id / f"diff-v{k - 1}-v{k}.json", d)
        current_rec["versions"] = summary
        emit(out_dir / f"{doc_id}.json", current_rec)
        report["published"] += 1

        pages = current_rec["pages"]
        report["documents"].append({
            "document_id": doc_id,
            "filename": current_rec["filename"],
            "source_url": current_rec["source_url"],
            "meeting_date": current_rec["meeting_date"],
            "draft_suspected": current_rec["draft_suspected"],
            "version": current_rec["version"],
            "versions": len(versions),
            "pages": len(pages),
            "ocr_pages": [p["page"] for p in pages if p["method"] == "tesseract"],
            "needs_review_pages": [p["page"] for p in pages if p["status"] == "needs_review"],
            "file": f"minutes/{doc_id}.json",
        })

    # The folder is generated: remove anything this run did not produce (old ids, old files).
    for f in sorted(out_dir.rglob("*"), reverse=True):
        if f.is_file() and f.resolve() not in produced:
            f.unlink()
        elif f.is_dir() and not any(f.iterdir()):
            f.rmdir()

    # Newest meeting first; documents with no detected date last.
    report["documents"].sort(key=lambda d: d["filename"] or "")
    report["documents"].sort(
        key=lambda d: (d["meeting_date"] or {}).get("value") or "", reverse=True)
    _write(public / "index.json",
           {"count": len(report["documents"]), **disclosure.labels("extraction"),
            "documents": report["documents"]})
    return report
