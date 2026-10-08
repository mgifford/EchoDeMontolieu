"""Faithful public record of the council minutes: page text and links, unredacted.

This reproduces what the Mairie published. Nothing is redacted, rewritten or
corrected. What is added is provenance and honesty about extraction quality:
how each page's text was obtained, OCR confidence, and a link to the original
page. Protection of individuals is applied later, where data is aggregated
(search, MCP, derived datasets), not here.
"""
import json
from pathlib import Path

PAGE_FIELDS = ("page", "page_url", "method", "status", "note", "image_area_fraction",
               "text", "text_sparse", "ocr")
SPARSE_NOTE = ("text_sparse is an alternate OCR reading. It finds more figures in "
               "tables but does not keep rows and columns together.")


def build_record(extraction, index_entry=None, include_text=True):
    index_entry = index_entry or {}
    pages = []
    for p in extraction["pages"]:
        out = {k: p[k] for k in PAGE_FIELDS if k in p}
        if not include_text:
            out.pop("text", None)
            out.pop("text_sparse", None)
        pages.append(out)
    return {
        "document_id": extraction["sha256"][:12],
        "filename": index_entry.get("filename"),
        "source_url": extraction["source_url"],
        "source_sha256": extraction["sha256"],
        "source_bytes": extraction.get("size_bytes"),
        "source_http": index_entry.get("http"),
        "verify": {
            "algorithm": "SHA-256",
            "about": "source_sha256 is the hash of the PDF exactly as downloaded from "
                     "source_url on retrieved_at. The PDF itself is not copied here.",
            "local_file": "shasum -a 256 FILE.pdf",
            "against_site": "python -m echo_montolieu verify DOCUMENT_ID",
        },
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
        },
        "pages": pages,
    }


def publish_record(private_dir, public_dir, include_text=True):
    private, public = Path(private_dir), Path(public_dir)
    index_path = private / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    out_dir = public / "minutes"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"published": 0, "skipped_failed": [], "documents": []}
    for url, entry in index.items():
        if "error" in entry:
            report["skipped_failed"].append(url)
            continue
        extraction = json.loads((private / entry["extraction"]).read_text(encoding="utf-8"))
        rec = build_record(extraction, entry, include_text)
        (out_dir / f"{rec['document_id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["published"] += 1
        pages = rec["pages"]
        report["documents"].append({
            "document_id": rec["document_id"],
            "filename": rec["filename"],
            "source_url": rec["source_url"],
            "meeting_date": rec["meeting_date"],
            "draft_suspected": rec["draft_suspected"],
            "pages": len(pages),
            "ocr_pages": [p["page"] for p in pages if p["method"] == "tesseract"],
            "needs_review_pages": [p["page"] for p in pages if p["status"] == "needs_review"],
            "file": f"minutes/{rec['document_id']}.json",
        })
    # Newest meeting first; documents with no detected date last.
    report["documents"].sort(key=lambda d: d["filename"] or "")
    report["documents"].sort(
        key=lambda d: (d["meeting_date"] or {}).get("value") or "", reverse=True)
    (public / "index.json").write_text(
        json.dumps({"count": len(report["documents"]), "documents": report["documents"]},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
