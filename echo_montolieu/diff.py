"""What changed between two versions of the same minutes PDF.

Each version's text is compared exactly as extracted. Two views are produced:
  * per page, matched by page number, with a status for each page;
  * the whole document as one unified diff with page markers, which still reads
    correctly when a page was inserted or removed and later page numbers shifted.

A changed file with identical text is reported as such (text_changed = False):
the PDF was probably re-saved or its metadata changed.
"""
import difflib

CONTEXT_LINES = 2


def _norm_ws(text):
    return " ".join(text.split())


def _unified(old, new, from_label, to_label):
    return list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                     fromfile=from_label, tofile=to_label,
                                     n=CONTEXT_LINES, lineterm=""))


def _page_texts(extraction):
    return {p["page"]: p.get("text") or "" for p in extraction["pages"]}


def diff_versions(old, new, from_version, to_version):
    """old and new are extraction dicts (as written by extract_pdf)."""
    old_pages, new_pages = _page_texts(old), _page_texts(new)
    pages, counts = [], {"unchanged": 0, "whitespace_only": 0, "changed": 0,
                         "added": 0, "removed": 0}
    for n in sorted(set(old_pages) | set(new_pages)):
        a, b = old_pages.get(n), new_pages.get(n)
        if a is None:
            status = "added"
        elif b is None:
            status = "removed"
        elif a == b:
            status = "unchanged"
        elif _norm_ws(a) == _norm_ws(b):
            status = "whitespace_only"
        else:
            status = "changed"
        counts[status] += 1
        entry = {"page": n, "status": status}
        if status in ("changed", "whitespace_only", "added", "removed"):
            entry["similarity"] = round(difflib.SequenceMatcher(
                None, a or "", b or "").ratio(), 3)
            entry["diff"] = _unified(a or "", b or "", f"v{from_version} page {n}",
                                     f"v{to_version} page {n}")
        pages.append(entry)

    def whole(pages_by_no):
        return "\n".join(f"=== page {n} ===\n{t}" for n, t in sorted(pages_by_no.items()))

    text_changed = any(p["status"] in ("changed", "added", "removed") for p in pages)
    return {
        "from_version": from_version,
        "to_version": to_version,
        "from_sha256": old["sha256"],
        "to_sha256": new["sha256"],
        "from_retrieved_at": old["retrieved_at"],
        "to_retrieved_at": new["retrieved_at"],
        "summary": {
            "file_changed": old["sha256"] != new["sha256"],
            "text_changed": text_changed,
            "pages_before": len(old_pages),
            "pages_after": len(new_pages),
            "pages": counts,
            "meeting_date_before": (old.get("meeting_date") or {}).get("value"),
            "meeting_date_after": (new.get("meeting_date") or {}).get("value"),
        },
        "pages": pages,
        "document_diff": _unified(whole(old_pages), whole(new_pages),
                                  f"v{from_version}", f"v{to_version}"),
        "labels": {
            "machine_generated": True,
            "note": "Differences are between machine-extracted texts. OCR pages may differ "
                    "because of recognition, not because the original changed; check the PDFs.",
        },
    }
