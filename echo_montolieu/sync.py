"""Fetch new minutes PDFs politely, extract them, and store the results privately.

Output goes only to the private directory. Nothing here publishes anything:
extractions are unredacted and can contain private individuals' names, so
every index entry is marked "withheld" until a redaction step exists.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .extract import extract_pdf
from .fetch import StopFetching
from .minutes import INDEX_URL, parse_minutes_index


def _load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _summarise(result):
    pages = result["pages"]
    return {
        "page_count": result["page_count"],
        "meeting_date": result["meeting_date"],
        "ocr_pages": [p["page"] for p in pages if p["method"] == "tesseract"],
        "needs_review_pages": [p["page"] for p in pages if p["status"] == "needs_review"],
    }


def sync(fetcher, private_dir, tessdata_dir=None, limit=None, dry_run=False,
         extract=extract_pdf):
    """Returns a report dict. report["exit_code"] is 0, 1 (failures) or 2 (stopped)."""
    private = Path(private_dir)
    extractions = private / "extractions"
    extractions.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    index_path = private / "index.json"
    index = _load(index_path, {})

    report = {"new": [], "skipped": [], "failed": [], "stopped": None, "exit_code": 0}

    try:
        page = fetcher.get(INDEX_URL)
        items = parse_minutes_index(page.path.read_text(encoding="utf-8"))
        todo = [i for i in items if i["url"] not in index or "error" in index[i["url"]]]
        report["skipped"] = [i["url"] for i in items if i not in todo]
        if limit is not None:
            todo = todo[:limit]
        if dry_run:
            report["would_fetch"] = [i["url"] for i in todo]
            return report

        for item in todo:
            url = item["url"]
            try:
                fetched = fetcher.get(url, revalidate=False)
                result = extract(fetched.path, url, fetched.retrieved_at,
                                 tessdata_dir=tessdata_dir)
                out = extractions / (Path(item["filename"]).stem + ".json")
                out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                index[url] = {
                    "filename": item["filename"],
                    "extraction": str(out.relative_to(private)),
                    "pdf_sha256": result["sha256"],
                    "http": {"etag": fetched.etag, "last_modified": fetched.last_modified},
                    "retrieved_at": fetched.retrieved_at,
                    "draft_suspected": item["draft_suspected"],
                    "public_release": "withheld",  # no redaction step yet
                    **_summarise(result),
                }
                report["new"].append(url)
            except StopFetching:
                raise
            except Exception as exc:  # recorded and surfaced, never silent
                index[url] = {"filename": item["filename"], "error": repr(exc),
                              "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                report["failed"].append({"url": url, "error": repr(exc)})
                report["exit_code"] = 1
            finally:
                index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    except StopFetching as exc:
        report["stopped"] = str(exc)
        report["exit_code"] = 2
    return report
