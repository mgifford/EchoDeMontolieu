import hashlib
import json

import pytest

from echo_montolieu import wayback
from echo_montolieu.fetch import Fetched, StopFetching
from echo_montolieu.record import build_record
from echo_montolieu.verify import verify_online


def cap(name, mimetype="application/pdf", ts="20041225055345", folder="docs"):
    return {"timestamp": ts, "original": f"http://www.montolieu.fr/{folder}/{name}", "mimetype": mimetype, "length": "1"}


def test_date_hint_reads_the_three_filename_styles_and_gives_up_on_nonsense():
    assert wayback.date_hint("CRCM02032004.pdf") == "2004-03-02"
    assert wayback.date_hint("CRCM140504.pdf") == "2004-05-14"
    assert wayback.date_hint("CRCM%2020060505.pdf") == "2006-05-05"
    assert wayback.date_hint("CRCM99999999.pdf") is None
    assert wayback.date_hint("Bulletinmunicipal.pdf") is None


def test_choose_minutes_keeps_only_minutes_prefers_pdf_and_dedupes():
    rows = [cap("CRCM170804.doc", "application/msword"), cap("CRCM170804.pdf"),
            cap("CRCM%2020060505.pdf"), cap("Bulletinmunicipal.pdf"),
            cap("duplipermis.pdf", folder="demarches"), cap("CRCM250105.doc", "application/msword")]
    items = wayback.choose_minutes(rows)
    assert [i["name"] for i in items] == ["CRCM170804.pdf", "CRCM20060505.pdf", "CRCM250105.doc"]
    first = items[0]
    assert first["wayback_url"] == "https://web.archive.org/web/20041225055345/http://www.montolieu.fr/docs/CRCM170804.pdf"
    assert "id_/" in first["raw_url"]            # the unwrapped original, not the Wayback viewer page
    assert first["date_hint"] == "2004-08-17"


class FakeFetcher:
    def __init__(self, tmp, bodies, stop_on=None):
        self.tmp, self.bodies, self.stop_on, self.calls = tmp, bodies, stop_on, []

    def get(self, url, revalidate=True):
        self.calls.append(url)
        if url == self.stop_on:
            raise StopFetching("429")
        body = self.bodies[url]
        p = self.tmp / hashlib.sha256(url.encode()).hexdigest()[:8]
        p.write_bytes(body)
        return Fetched(url, p, "fetched", "2026-10-08T00:00:00+00:00", hashlib.sha256(body).hexdigest())


def fake_extract(path, source_url, retrieved_at, tessdata_dir=None):
    return {"source_url": source_url, "retrieved_at": retrieved_at, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size, "page_count": 1, "meeting_date": None, "pages": [], "extractor": {}}


def items_for(*names):
    return wayback.choose_minutes([cap(n) for n in names])


def test_sync_wayback_mirrors_the_original_and_records_both_copies(tmp_path):
    items = items_for("CRCM02032004.pdf")
    body = b"%PDF-1.4 minutes"
    f = FakeFetcher(tmp_path, {items[0]["raw_url"]: body})
    report = wayback.sync_wayback(f, tmp_path / "private", tmp_path / "archive", items, extract=fake_extract)
    assert report["new"] == [items[0]["wayback_url"]] and report["exit_code"] == 0
    assert (tmp_path / "archive/originals/CRCM02032004.pdf").read_bytes() == body
    entry = json.loads((tmp_path / "private/index.json").read_text())[items[0]["wayback_url"]]
    o = entry["origin"]
    assert o["kind"] == "wayback" and o["official_copy"] == items[0]["wayback_url"]
    assert o["mirror_path"] == "archive/originals/CRCM02032004.pdf" and o["mirror_url"].endswith("/CRCM02032004.pdf")
    assert o["date_hint_from_filename"] == "2004-03-02"
    assert entry["pdf_sha256"] == hashlib.sha256(body).hexdigest()
    # a second run neither fetches nor re-mirrors
    f2 = FakeFetcher(tmp_path, {})
    again = wayback.sync_wayback(f2, tmp_path / "private", tmp_path / "archive", items, extract=fake_extract)
    assert f2.calls == [] and again["skipped"] == [items[0]["wayback_url"]]


def test_sync_wayback_rejects_a_non_pdf_and_keeps_nothing_of_it(tmp_path):
    items = items_for("CRCM02032004.pdf")
    f = FakeFetcher(tmp_path, {items[0]["raw_url"]: b"<html>Wayback error page</html>"})
    report = wayback.sync_wayback(f, tmp_path / "private", tmp_path / "archive", items, extract=fake_extract)
    assert report["failed"] and report["exit_code"] == 1
    assert not (tmp_path / "archive/originals/CRCM02032004.pdf").exists()


def test_sync_wayback_stops_at_once_on_a_server_error(tmp_path):
    items = items_for("CRCM02032004.pdf", "CRCM041204.pdf")
    f = FakeFetcher(tmp_path, {i["raw_url"]: b"%PDF-1" for i in items}, stop_on=items[0]["raw_url"])
    report = wayback.sync_wayback(f, tmp_path / "private", tmp_path / "archive", items, extract=fake_extract)
    assert report["stopped"] and report["exit_code"] == 2 and len(f.calls) == 1


def test_word_only_meetings_are_reported_not_fetched(tmp_path):
    items = wayback.choose_minutes([cap("CRCM250105.doc", "application/msword")])
    f = FakeFetcher(tmp_path, {})
    report = wayback.sync_wayback(f, tmp_path / "private", tmp_path / "archive", items, extract=fake_extract)
    assert report["word_only"] == [items[0]["wayback_url"]] and f.calls == []


def test_record_names_the_official_copy_and_the_mirror_and_refuses_online_verify():
    origin = {"kind": "wayback", "mirror_path": "archive/originals/X.pdf", "mirror_url": "https://example/X.pdf"}
    ex = {"source_url": "https://web.archive.org/web/1/http://a/X.pdf", "sha256": "ab", "retrieved_at": "t",
          "page_count": 0, "pages": []}
    rec = build_record(ex, {"filename": "X.pdf", "origin": origin})
    assert rec["origin"] == origin and "Internet Archive" in rec["verify"]["about"]
    with pytest.raises(ValueError, match="archived capture"):
        verify_online({**rec, "is_current": True}, fetcher=None)


def _archived_and_current_public(tmp_path):
    """A public folder with one current record and one archived record, built by the real writers."""
    from echo_montolieu.record import publish_record
    private, public = tmp_path / "private", tmp_path / "public"
    (private / "extractions").mkdir(parents=True)
    index = {}
    for url, date, origin in (("https://www.montolieu.fr/a.pdf", "2024-04-04", None),
                              ("https://web.archive.org/web/1/http://x/b.pdf", "2004-03-02", {"kind": "wayback", "mirror_path": "archive/originals/b.pdf", "mirror_url": "https://e/b.pdf", "date_hint_from_filename": "2004-03-02"})):
        stem = "a" if origin is None else "b"
        ex = {"source_url": url, "retrieved_at": "2026-10-08T00:00:00+00:00", "sha256": stem * 64, "size_bytes": 1, "page_count": 1,
              "meeting_date": {"value": date, "source": "x", "status": "tentative"}, "extractor": {},
              "pages": [{"page": 1, "page_url": url + "#page=1", "method": "text_layer", "status": "ok",
                         "text": "Le conseil municipal se réunit. Monsieur DUPONT Jean a acheté le terrain."}]}
        (private / "extractions" / f"{stem}.json").write_text(json.dumps(ex))
        index[url] = {"filename": f"{stem}.pdf", "draft_suspected": False, "pdf_sha256": stem * 64, "retrieved_at": ex["retrieved_at"],
                      "extraction": f"extractions/{stem}.json", **({"origin": origin} if origin else {})}
    (private / "index.json").write_text(json.dumps(index))
    publish_record(private, public)
    return public


def test_archived_minutes_get_faithful_text_only_and_stay_out_of_derived_pages(tmp_path):
    from echo_montolieu import threads
    from echo_montolieu.render import render_all
    public = _archived_and_current_public(tmp_path)
    _, meetings = render_all(public)
    assert [m["date"] for m in meetings] == ["2024-04-04"]
    old = public / "meetings" / "2004-03-02"
    assert (old / "minutes.md").exists() and not (old / "facts.md").exists() and not (old / "todo.md").exists()
    assert "Internet Archive" in (old / "minutes.md").read_text(encoding="utf-8")
    assert "2004-03-02" in (public / "meetings" / "index.md").read_text(encoding="utf-8")
    assert [m["meeting"]["date"] for m in threads.load_meetings(public)] == ["2024-04-04"]


def test_archived_minutes_are_never_sent_to_a_model(tmp_path):
    from echo_montolieu.generate import estimate_generation
    public = _archived_and_current_public(tmp_path)
    est = estimate_generation(public, ["en"], None, None)
    assert est["meetings"] == 1
