"""Fetch minutes PDFs politely, extract them, keep every version, store privately.

Output goes only to the private directory. Nothing here publishes anything.

Versions: when a known PDF changes on the site, the previous extraction is kept as
versions/<stem>/v<N>.json, the replaced PDF is archived by hash (see PoliteFetcher),
and the new extraction becomes current. A change is detected by comparing the
file's SHA-256 with the current version's, not from the HTTP status, so a failed
extraction is retried on the next run even though the cache already holds the file.
"""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .extract import extract_pdf
from .fetch import StopFetching
from .minutes import INDEX_URL, parse_minutes_index
from .versions import ensure_versions


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _set_current(entry, result, fetched, extraction_rel):
    entry.update({
        "extraction": extraction_rel,
        "pdf_sha256": result["sha256"],
        "http": {"etag": fetched.etag, "last_modified": fetched.last_modified},
        "retrieved_at": fetched.retrieved_at,
        **_summarise(result),
    })


def _first_version(entry_base, result, fetched, extraction_rel):
    entry = {**entry_base, "public_release": "withheld"}  # no redaction step yet
    _set_current(entry, result, fetched, extraction_rel)
    entry["current_version"] = 1
    entry["versions"] = [{
        "version": 1, "sha256": result["sha256"], "size_bytes": result.get("size_bytes"),
        "retrieved_at": fetched.retrieved_at,
        "http": {"etag": fetched.etag, "last_modified": fetched.last_modified},
        "extraction": extraction_rel, "superseded_at": None}]
    return entry


def sync(fetcher, private_dir, tessdata_dir=None, limit=None, dry_run=False,
         extract=extract_pdf, check_changes=True):
    """Returns a report dict. report["exit_code"] is 0, 1 (failures) or 2 (stopped)."""
    private = Path(private_dir)
    extractions = private / "extractions"
    extractions.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    index_path = private / "index.json"
    index = _load(index_path, {})
    for entry in index.values():
        ensure_versions(entry)

    report = {"new": [], "changed": [], "unchanged": [], "skipped": [], "failed": [],
              "stopped": None, "exit_code": 0}

    def save():
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def fail(url, filename, exc, entry=None):
        info = {"error": repr(exc), "failed_at": _now()}
        if entry is None:
            index[url] = {"filename": filename, **info}
        else:
            entry["last_update_error"] = info  # keep the existing, working version
        report["failed"].append({"url": url, "error": repr(exc)})
        report["exit_code"] = 1

    try:
        page = fetcher.get(INDEX_URL)
        items = parse_minutes_index(page.path.read_text(encoding="utf-8"))
        todo = [i for i in items if i["url"] not in index or "error" in index[i["url"]]]
        known = [i for i in items if i not in todo]
        report["skipped"] = [i["url"] for i in known]
        if limit is not None:
            todo = todo[:limit]
        if dry_run:
            report["would_fetch"] = [i["url"] for i in todo]
            report["would_check_for_changes"] = len(known) if check_changes else 0
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
                index[url] = _first_version(
                    {"filename": item["filename"], "draft_suspected": item["draft_suspected"]},
                    result, fetched, str(out.relative_to(private)))
                report["new"].append(url)
            except StopFetching:
                raise
            except Exception as exc:  # recorded and surfaced, never silent
                fail(url, item["filename"], exc)
            finally:
                save()

        if check_changes:
            for item in known:
                url, entry = item["url"], index[item["url"]]
                if "error" in entry:
                    continue
                try:
                    current = entry["versions"][-1]
                    # A cached copy that already differs from the indexed version means an
                    # earlier update failed after download: process it without asking the
                    # server. Otherwise ask with HEAD and download only if the headers differ.
                    if (fetcher.cached_sha256(url) == current["sha256"]
                            and fetcher.changed_on_server(url) is False):
                        entry["checked_at"] = _now()
                        report["unchanged"].append(url)
                        continue
                    fetched = fetcher.get(url, revalidate=True)
                    if fetched.sha256 == current["sha256"]:
                        entry["checked_at"] = _now()
                        report["unchanged"].append(url)
                        continue
                    stem = Path(entry["filename"]).stem
                    result = extract(fetched.path, url, fetched.retrieved_at,
                                     tessdata_dir=tessdata_dir)
                    old_path = private / current["extraction"]
                    kept = private / "versions" / stem / f"v{current['version']}.json"
                    kept.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(old_path, kept)
                    current["extraction"] = str(kept.relative_to(private))
                    current["superseded_at"] = fetched.retrieved_at
                    new_version = current["version"] + 1
                    out = extractions / f"{stem}.json"
                    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
                    entry["versions"].append({
                        "version": new_version, "sha256": result["sha256"],
                        "size_bytes": result.get("size_bytes"),
                        "retrieved_at": fetched.retrieved_at,
                        "http": {"etag": fetched.etag, "last_modified": fetched.last_modified},
                        "extraction": str(out.relative_to(private)), "superseded_at": None})
                    entry["current_version"] = new_version
                    entry.pop("last_update_error", None)
                    _set_current(entry, result, fetched, str(out.relative_to(private)))
                    report["changed"].append({
                        "url": url, "from_version": new_version - 1, "to_version": new_version,
                        "previous_pdf_archived_to": (str(fetched.archived_to)
                                                     if fetched.archived_to else None)})
                except StopFetching:
                    raise
                except Exception as exc:
                    fail(url, entry["filename"], exc, entry)
                finally:
                    save()
    except StopFetching as exc:
        report["stopped"] = str(exc)
        report["exit_code"] = 2
    save()
    return report
