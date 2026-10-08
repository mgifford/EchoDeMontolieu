import hashlib
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
A, B, C = BASE + "A-site.pdf", BASE + "B-site.pdf", BASE + "Projet-C-site.pdf"


class FakeFetcher:
    """Serves INDEX_HTML and per-URL PDF bytes that tests can change between runs."""

    def __init__(self, tmp_path, content=None, stop_on=None):
        self.tmp, self.calls, self.stop_on = tmp_path, [], stop_on
        self.content = content if content is not None else {}
        self.cached, self.head_says, self.heads = {}, {}, []

    def cached_sha256(self, url):
        return self.cached.get(url)

    def changed_on_server(self, url):
        self.heads.append(url)
        return self.head_says.get(url)  # None = cannot tell

    def get(self, url, revalidate=True):
        self.calls.append((url, revalidate))
        if url == self.stop_on:
            raise StopFetching("429 from " + url)
        p = self.tmp / (url.rsplit("/", 1)[-1] or "index")
        if url.endswith("/comptes-rendus-cm/"):
            p.write_text(INDEX_HTML)
            data = INDEX_HTML.encode()
        else:
            data = self.content.setdefault(url, b"%PDF v1")
            p.write_bytes(data)
        return Fetched(url, p, "fetched", "2026-10-08T00:00:00+00:00",
                       hashlib.sha256(data).hexdigest(), None, "Mon",
                       archived_to=self.tmp / "archive" / "old.pdf" if b"v2" in data else None)


def fake_extract(path, url, retrieved_at, tessdata_dir=None):
    if "B-site" in url and path.read_bytes() == b"%PDF v1":
        raise RuntimeError("boom")
    data = path.read_bytes()
    return {"source_url": url, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
            "retrieved_at": retrieved_at, "page_count": 2, "meeting_date": None,
            "pages": [{"page": 1, "method": "text_layer", "status": "machine_extracted",
                       "text": data.decode()},
                      {"page": 2, "method": "tesseract", "status": "needs_review", "text": "ocr"}]}


def run(tmp_path, fetcher=None, **kw):
    f = fetcher or FakeFetcher(tmp_path)
    r = sync(f, tmp_path / "private", extract=fake_extract, **kw)
    return f, r


def index(tmp_path):
    return json.loads((tmp_path / "private" / "index.json").read_text())


def test_new_pdfs_are_extracted_withheld_and_private(tmp_path):
    run(tmp_path)
    ok = index(tmp_path)[A]
    assert ok["public_release"] == "withheld"
    assert ok["needs_review_pages"] == [2] and ok["ocr_pages"] == [2]
    assert ok["draft_suspected"] is False and index(tmp_path)[C]["draft_suspected"]
    assert (tmp_path / "private" / "extractions" / "A-site.json").exists()
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700
    assert ok["current_version"] == 1 and len(ok["versions"]) == 1
    assert ok["versions"][0]["sha256"] == ok["pdf_sha256"]


def test_failure_is_recorded_nonzero_and_does_not_stop_others(tmp_path):
    _, r = run(tmp_path)
    assert "boom" in index(tmp_path)[B]["error"]
    assert r["exit_code"] == 1 and len(r["failed"]) == 1 and len(r["new"]) == 2


def test_failed_pdf_is_retried_but_finished_ones_are_not_refetched(tmp_path):
    run(tmp_path)
    f2, r2 = run(tmp_path, FakeFetcher(tmp_path, content={B: b"%PDF v1 fixed"}),
                 check_changes=False)
    assert [u for u, _ in f2.calls if u.endswith(".pdf")] == [B]
    assert A in r2["skipped"] and "error" not in index(tmp_path)[B]


def test_new_pdfs_are_fetched_without_revalidation(tmp_path):
    f, _ = run(tmp_path)
    assert all(rev is False for u, rev in f.calls if u.endswith(".pdf"))


def test_dry_run_downloads_no_pdfs_and_reports_planned_checks(tmp_path):
    run(tmp_path)
    f, r = run(tmp_path, dry_run=True)
    assert not [u for u, _ in f.calls if u.endswith(".pdf")]
    assert r["would_check_for_changes"] == 2 and len(r["would_fetch"]) == 1


def test_limit_caps_new_pdfs(tmp_path):
    _, r = run(tmp_path, limit=1)
    assert len(r["new"]) + len(r["failed"]) == 1


def test_stop_on_429_keeps_progress_and_exits_2(tmp_path):
    f = FakeFetcher(tmp_path, stop_on=B)
    _, r = run(tmp_path, f)
    assert r["exit_code"] == 2 and "429" in r["stopped"]
    assert A in index(tmp_path) and C not in index(tmp_path)


# ---- versions ---------------------------------------------------------------------


def good(tmp_path):
    run(tmp_path, FakeFetcher(tmp_path, content={B: b"%PDF v1 ok"}))


def test_unchanged_pdfs_are_checked_with_revalidation_and_stay_version_1(tmp_path):
    good(tmp_path)
    f, r = run(tmp_path, FakeFetcher(tmp_path, content={B: b"%PDF v1 ok"}))
    pdf_calls = [(u, rev) for u, rev in f.calls if u.endswith(".pdf")]
    assert len(pdf_calls) == 3 and all(rev is True for _, rev in pdf_calls)
    assert len(r["unchanged"]) == 3 and r["changed"] == [] and r["exit_code"] == 0
    assert all(e["current_version"] == 1 for e in index(tmp_path).values())


def test_changed_pdf_becomes_version_2_and_keeps_version_1(tmp_path):
    good(tmp_path)
    old_text = json.loads((tmp_path / "private" / "extractions" / "A-site.json").read_text())
    f = FakeFetcher(tmp_path, content={A: b"%PDF v2 edited", B: b"%PDF v1 ok"})
    _, r = run(tmp_path, f)
    assert [c["url"] for c in r["changed"]] == [A]
    assert r["changed"][0]["from_version"] == 1 and r["changed"][0]["to_version"] == 2
    assert r["changed"][0]["previous_pdf_archived_to"].endswith("old.pdf")
    e = index(tmp_path)[A]
    assert e["current_version"] == 2 and [v["version"] for v in e["versions"]] == [1, 2]
    v1, v2 = e["versions"]
    assert v1["superseded_at"] and v2["superseded_at"] is None
    assert v1["sha256"] != v2["sha256"] == e["pdf_sha256"]
    kept = json.loads((tmp_path / "private" / v1["extraction"]).read_text())
    assert kept == old_text                                  # version 1 preserved exactly
    cur = json.loads((tmp_path / "private" / v2["extraction"]).read_text())
    assert cur["pages"][0]["text"] == "%PDF v2 edited"       # current is the new one
    assert v1["extraction"].startswith("versions/A-site/v1")


def test_several_changes_keep_every_version(tmp_path):
    good(tmp_path)
    for n in (2, 3, 4):
        run(tmp_path, FakeFetcher(tmp_path, content={A: f"%PDF v{n} text".encode(),
                                                     B: b"%PDF v1 ok"}))
    e = index(tmp_path)[A]
    assert e["current_version"] == 4 and [v["version"] for v in e["versions"]] == [1, 2, 3, 4]
    for k in (1, 2, 3):
        assert (tmp_path / "private" / "versions" / "A-site" / f"v{k}.json").exists()
    assert sum(v["superseded_at"] is None for v in e["versions"]) == 1   # only the latest is current


def test_failed_update_keeps_the_working_version_and_retries_next_run(tmp_path):
    good(tmp_path)
    new = {A: b"%PDF v2 edited", B: b"%PDF v1 ok"}

    def exploding(path, url, retrieved_at, tessdata_dir=None):
        if url == A:
            raise RuntimeError("ocr crashed")
        return fake_extract(path, url, retrieved_at, tessdata_dir)

    r = sync(FakeFetcher(tmp_path, content=new), tmp_path / "private", extract=exploding)
    assert r["exit_code"] == 1 and index(tmp_path)[A]["current_version"] == 1
    assert "ocr crashed" in index(tmp_path)[A]["last_update_error"]["error"]
    _, r2 = run(tmp_path, FakeFetcher(tmp_path, content=new))   # next run, extraction works
    assert r2["changed"] and index(tmp_path)[A]["current_version"] == 2
    assert "last_update_error" not in index(tmp_path)[A]


def test_indexes_written_before_versioning_are_treated_as_version_1(tmp_path):
    good(tmp_path)
    idx = index(tmp_path)
    for e in idx.values():
        e.pop("versions", None)
        e.pop("current_version", None)
    (tmp_path / "private" / "index.json").write_text(json.dumps(idx))
    run(tmp_path, FakeFetcher(tmp_path, content={A: b"%PDF v2 edited", B: b"%PDF v1 ok"}))
    e = index(tmp_path)[A]
    assert [v["version"] for v in e["versions"]] == [1, 2]
    assert (tmp_path / "private" / "versions" / "A-site" / "v1.json").exists()


def test_check_changes_can_be_switched_off(tmp_path):
    good(tmp_path)
    f, r = run(tmp_path, FakeFetcher(tmp_path, content={A: b"%PDF v2 edited"}), check_changes=False)
    assert not [u for u, _ in f.calls if u.endswith(".pdf")] and r["changed"] == []


# ---- header-only change detection ------------------------------------------------------


def sha_of(b):
    return hashlib.sha256(b).hexdigest()


def head_fetcher(tmp_path, content, head_says, cached=None):
    f = FakeFetcher(tmp_path, content=content)
    f.head_says = head_says
    f.cached = cached if cached is not None else {
        u: sha_of(b) for u, b in content.items()}
    return f


def test_head_says_unchanged_so_no_pdf_is_downloaded(tmp_path):
    good(tmp_path)
    content = {A: b"%PDF v1", B: b"%PDF v1 ok", C: b"%PDF v1"}
    f = head_fetcher(tmp_path, content, {A: False, B: False, C: False})
    _, r = run(tmp_path, f)
    assert len(r["unchanged"]) == 3 and r["changed"] == [] and r["exit_code"] == 0
    assert sorted(f.heads) == sorted([A, B, C])
    assert not [u for u, _ in f.calls if u.endswith(".pdf")]      # nothing downloaded


def test_head_says_changed_so_the_pdf_is_downloaded_and_versioned(tmp_path):
    good(tmp_path)
    content = {A: b"%PDF v2 edited", B: b"%PDF v1 ok", C: b"%PDF v1"}
    f = head_fetcher(tmp_path, content, {A: True, B: False, C: False},
                     cached={A: sha_of(b"%PDF v1"), B: sha_of(b"%PDF v1 ok"), C: sha_of(b"%PDF v1")})
    _, r = run(tmp_path, f)
    assert [c["url"] for c in r["changed"]] == [A]
    assert [u for u, _ in f.calls if u.endswith(".pdf")] == [A]   # only the changed one
    assert index(tmp_path)[A]["current_version"] == 2


def test_head_cannot_tell_falls_back_to_downloading(tmp_path):
    good(tmp_path)
    content = {A: b"%PDF v2 edited", B: b"%PDF v1 ok", C: b"%PDF v1"}
    f = head_fetcher(tmp_path, content, {A: None, B: None, C: None})
    _, r = run(tmp_path, f)
    assert [c["url"] for c in r["changed"]] == [A]
    assert len([u for u, _ in f.calls if u.endswith(".pdf")]) == 3


def test_cached_copy_newer_than_the_index_is_processed_even_if_head_says_unchanged(tmp_path):
    """An earlier update downloaded the file then failed: the server now matches the cache,
    but the index still holds the old version. HEAD must not hide that."""
    good(tmp_path)
    content = {A: b"%PDF v2 edited", B: b"%PDF v1 ok", C: b"%PDF v1"}
    f = head_fetcher(tmp_path, content, {A: False, B: False, C: False},
                     cached={A: sha_of(b"%PDF v2 edited"), B: sha_of(b"%PDF v1 ok"),
                             C: sha_of(b"%PDF v1")})
    _, r = run(tmp_path, f)
    assert [c["url"] for c in r["changed"]] == [A]
    assert A not in f.heads                                       # skipped HEAD, went straight to it
