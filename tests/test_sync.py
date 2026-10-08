import json
import stat

import pytest

from echo_montolieu.fetch import Fetched, StopFetching
from echo_montolieu.sync import sync

INDEX_HTML = """
<a href="/wp-content/uploads/2024/12/A-site.pdf">A</a>
<a href="/wp-content/uploads/2024/12/B-site.pdf">B</a>
<a href="/wp-content/uploads/2024/12/Projet-C-site.pdf">C</a>
"""
BASE = "https://www.montolieu.fr/wp-content/uploads/2024/12/"


class FakeFetcher:
    def __init__(self, tmp_path, stop_on=None):
        self.tmp, self.calls, self.stop_on = tmp_path, [], stop_on

    def get(self, url, revalidate=True):
        self.calls.append((url, revalidate))
        if url == self.stop_on:
            raise StopFetching("429 from " + url)
        p = self.tmp / (url.rsplit("/", 1)[-1] or "index")
        p.write_text(INDEX_HTML if url.endswith("/comptes-rendus-cm/") else "%PDF")
        return Fetched(url, p, "fetched", "2026-10-08T00:00:00+00:00", "0" * 64)


def fake_extract(path, url, retrieved_at, tessdata_dir=None):
    if "B-site" in url:
        raise RuntimeError("boom")
    return {"source_url": url, "sha256": "f" * 64, "page_count": 2,
            "meeting_date": None,
            "pages": [{"page": 1, "method": "text_layer", "status": "machine_extracted"},
                      {"page": 2, "method": "tesseract", "status": "needs_review"}]}


def run(tmp_path, **kw):
    f = kw.pop("fetcher", None) or FakeFetcher(tmp_path)
    r = sync(f, tmp_path / "private", extract=fake_extract, **kw)
    return f, r


def test_new_pdfs_are_extracted_withheld_and_private(tmp_path):
    _, r = run(tmp_path)
    idx = json.loads((tmp_path / "private" / "index.json").read_text())
    ok = idx[BASE + "A-site.pdf"]
    assert ok["public_release"] == "withheld"
    assert ok["needs_review_pages"] == [2] and ok["ocr_pages"] == [2]
    assert ok["draft_suspected"] is False and idx[BASE + "Projet-C-site.pdf"]["draft_suspected"]
    assert (tmp_path / "private" / "extractions" / "A-site.json").exists()
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700


def test_failure_is_recorded_nonzero_and_does_not_stop_others(tmp_path):
    _, r = run(tmp_path)
    idx = json.loads((tmp_path / "private" / "index.json").read_text())
    assert "error" in idx[BASE + "B-site.pdf"] and "boom" in idx[BASE + "B-site.pdf"]["error"]
    assert r["exit_code"] == 1 and len(r["failed"]) == 1 and len(r["new"]) == 2


def test_second_run_skips_done_and_retries_failed_without_refetching_done(tmp_path):
    run(tmp_path)
    f2, r2 = run(tmp_path, fetcher=FakeFetcher(tmp_path))
    fetched_pdfs = [u for u, _ in f2.calls if u.endswith(".pdf")]
    assert fetched_pdfs == [BASE + "B-site.pdf"]  # only the failed one is retried
    assert BASE + "A-site.pdf" in r2["skipped"]


def test_pdfs_are_fetched_without_revalidation(tmp_path):
    f, _ = run(tmp_path)
    assert all(rev is False for u, rev in f.calls if u.endswith(".pdf"))


def test_dry_run_downloads_no_pdfs(tmp_path):
    f, r = run(tmp_path, dry_run=True)
    assert not [u for u, _ in f.calls if u.endswith(".pdf")]
    assert len(r["would_fetch"]) == 3


def test_limit_caps_new_pdfs(tmp_path):
    _, r = run(tmp_path, limit=1)
    assert len(r["new"]) + len(r["failed"]) == 1


def test_stop_on_429_keeps_progress_and_exits_2(tmp_path):
    f = FakeFetcher(tmp_path, stop_on=BASE + "B-site.pdf")
    _, r = run(tmp_path, fetcher=f)
    idx = json.loads((tmp_path / "private" / "index.json").read_text())
    assert r["exit_code"] == 2 and "429" in r["stopped"]
    assert BASE + "A-site.pdf" in idx            # progress before the stop is saved
    assert BASE + "Projet-C-site.pdf" not in idx  # nothing fetched after the stop
