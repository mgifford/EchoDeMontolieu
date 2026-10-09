import csv
import io
import json

from echo_montolieu import export
from echo_montolieu.site import build


def item(title, sensitive=False, vote="unanimous", pages=(2, 3), topics=("finances",), amounts=()):
    return {"title": title, "sensitive": sensitive, "vote_result": vote, "pages": list(pages), "topics": list(topics),
            "amounts": [{"kind": "eur", "value": v} for v in amounts]}


def meeting(date, items, folder=None):
    return {"folder": folder or date, "meeting": {"date": date, "document_id": "aaaaaaaaaaaa", "version": 1, "page_count": 5, "pages_needing_review": [4],
                                               "source_url": "https://example.org/x.pdf", "source_sha256": "ab" * 32, "items": items}}


def public(tmp_path):
    p = tmp_path / "public"
    (p / "meetings" / "2026-07-22").mkdir(parents=True)
    (p / "meetings" / "2026-07-22" / "summary.md").write_text(
        '---\nproduced_by: "AI model (m)"\n---\n# Résumé\n\n> **Information sur l’IA.** ...\n\n## Résumé\nLe conseil a voté le budget.\n')
    (p / "places").mkdir()
    (p / "places" / "places.json").write_text(json.dumps({"places": [{"label": "Rue des Remparts", "kind": "street", "lat": 43.31, "lon": 2.21,
        "items": [{"date": "2026-07-22", "folder": "2026-07-22", "page": 3, "url": "https://example.org/x.pdf"},
                  {"date": "2026-01-08", "folder": "2026-01-08", "page": 1, "url": "https://example.org/y.pdf"}]}]}))
    return p


def test_files_hold_decisions_but_never_private_sales_and_every_row_links_to_the_original(tmp_path):
    files, info = export.build(public(tmp_path), [meeting("2026-07-22", [item("Budget", amounts=(300.0,)), item("Vente rue Secrète 12", sensitive=True)])])
    blob = "".join(files.values())
    assert "Secrète" not in blob and info["decisions"] == 1 and info["meetings"] == 1
    doc = json.loads(files["council.json"])
    m = doc["meetings"][0]
    assert m["private_sale_notices"] == 1 and m["decisions"][0]["original_page_url"] == "https://example.org/x.pdf#page=2"
    assert m["summaries"]["fr"]["written_by"] == "AI model (m)" and m["summaries"]["fr"]["human_reviewed"] is False
    assert doc["labels"]["human_reviewed"] is False and "No reuse licence" in doc["notice"]
    rows = list(csv.DictReader(io.StringIO(files["decisions.csv"])))
    assert rows[0]["title"] == "Budget" and rows[0]["euro_amounts"] == "300.00" and rows[0]["original_page_url"].endswith("#page=2")
    assert list(csv.DictReader(io.StringIO(files["meetings.csv"])))[0]["private_sale_notices"] == "1"
    place = list(csv.DictReader(io.StringIO(files["places.csv"])))[0]
    assert place["meetings"] == "2" and place["first_meeting"] == "2026-01-08" and "openstreetmap.org" in place["openstreetmap_url"]


def test_a_cell_a_spreadsheet_would_run_as_a_formula_is_defused():
    text = export.to_csv(["a"], [{"a": "=HYPERLINK(\"http://x\")"}, {"a": "+1"}, {"a": "-2"}, {"a": "@x"}, {"a": "fine"}, {"a": None}])
    cells = [r[0] for r in csv.reader(io.StringIO(text))][1:]
    assert cells == ["'=HYPERLINK(\"http://x\")", "'+1", "'-2", "'@x", "fine", ""]


def test_archived_meetings_appear_with_their_scrubbed_vote_sentences_only(tmp_path):
    digest = {"decisions": [{"page": 2, "page_url": "https://web.archive.org/x#page=2", "kind": "unanimous", "for": None, "against": None,
                             "abstentions": None, "text": "Le Conseil vote [name withheld] à l’unanimité."}], "sale_notices": 1}
    rec = {"document_id": "bbbbbbbbbbbb", "source_url": "https://web.archive.org/x"}
    files, info = export.build(public(tmp_path), [], [("2005-01-25", "2005-01-25", rec, digest)])
    row = list(csv.DictReader(io.StringIO(files["decisions.csv"])))[0]
    assert row["source"] == "archive" and row["text_fr"].startswith("Le Conseil vote [name withheld]") and info["meetings"] == 1


def test_site_publishes_the_files_and_a_data_page_in_each_language(tmp_path):
    pub = public(tmp_path)
    export.write(pub, [meeting("2026-07-22", [item("Budget")])])
    (pub / "index.json").write_text(json.dumps({"documents": []}))
    data = tmp_path / "data"; data.mkdir()
    out = build(tmp_path / "_site", pub, data)
    for name in ("council.json", "meetings.csv", "decisions.csv", "places.csv"):
        assert (out / "data" / name).exists()
    for lang, title, date in (("en", "Open data", "22 July 2026"), ("fr", "Données ouvertes", "22 juillet 2026"), ("nl", "Open data", "22 juli 2026")):
        page = (out / lang / "data" / "index.html").read_text()
        assert title in page and date in page and 'href="../../data/decisions.csv"' in page and "https://example.org" not in page
        assert "1 " in page and "[{" not in page
        assert 'href="data/index.html"' in (out / lang / "index.html").read_text()
