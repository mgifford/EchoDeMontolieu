import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import create_app
from echo_montolieu import db
from echo_montolieu.meeting import SALE_TITLE_NEUTRAL


def _public(tmp_path, with_summary=True):
    pub = tmp_path / "public"
    (pub / "minutes").mkdir(parents=True)
    text = ("ORDRE DU JOUR\n- Piscine municipale\n- Vente d'un immeuble cadastré C0551\n\n"
            "PISCINE MUNICIPALE\nLe conseil fixe les tarifs de la piscine à 3 euros. Monsieur DUPONT Jean a demandé une subvention.\n"
            "Vote du conseil à l'unanimité\n\n"
            "VENTE D'UN IMMEUBLE CADASTREE C 551\nM. le maire propose la vente de l'immeuble cadastrée C0551 situé au 1 rue des Oliviers. "
            "Prix de vente : 100 000 euros.\nVote du conseil à l'unanimité\n")
    docs = []
    for i, (date, origin) in enumerate([("2026-06-05", None), ("2004-03-02", {"kind": "wayback"})]):
        rec = {"document_id": f"{i:012x}", "source_url": f"https://e.test/{i}.pdf", "source_sha256": "a" * 64, "page_count": 1, "version": 1,
               "origin": origin, "meeting_date": {"value": date, "status": "tentative"},
               "pages": [{"page": 1, "page_url": f"https://e.test/{i}.pdf#page=1", "method": "text_layer", "status": "machine_extracted",
                          "text": text if i == 0 else "Archive archivée secrète"}]}
        (pub / "minutes" / f"{rec['document_id']}.json").write_text(json.dumps(rec))
        docs.append({"file": f"minutes/{rec['document_id']}.json"})
    (pub / "index.json").write_text(json.dumps({"documents": docs}))
    folder = pub / "meetings" / "2026-06-05"
    folder.mkdir(parents=True)
    (folder / "minutes.md").write_text(f"---\ndocument_id: {0:012x}\n---\n# x\n")
    if with_summary:
        (folder / "summary.en.md").write_text('---\nproduced_by: "AI model (m)"\nhuman_reviewed: false\n---\n# Summary\n\n> **AI disclosure.** x\n\n'
                                              "The council set the swimming pool prices.\n")
        (folder / "summary.md").write_text("---\nproduced_by: \"software\"\n---\n# S\n\nNot written by a model, so not stored.\n")
    return pub


def test_build_counts_meetings_skips_archived_and_stores_summaries_only_when_a_model_wrote_them(tmp_path):
    counts = db.build_public(_public(tmp_path), tmp_path / "echo.db")
    assert counts["meetings"] == 1 and counts["skipped_archived"] == 1 and counts["summaries"] == 1
    con = sqlite3.connect(tmp_path / "echo.db")
    assert con.execute("SELECT lang, produced_by, human_reviewed FROM summaries").fetchall() == [("en", "AI model (m)", 0)]
    assert dict(con.execute("SELECT key, value FROM build_info"))["layer"].startswith("derived")


def test_sale_items_are_in_the_database_by_neutral_title_only_and_cannot_be_found(tmp_path):
    db.build_public(_public(tmp_path), tmp_path / "echo.db")
    con = sqlite3.connect(tmp_path / "echo.db")
    sale = con.execute("SELECT title, body, amounts, sensitive FROM items WHERE sensitive = 1").fetchall()
    assert sale and all(t == SALE_TITLE_NEUTRAL and b == "" and a == "[]" for t, b, a, _ in sale)
    everything = " ".join(str(c) for t in ("items", "search", "meetings", "summaries") for row in con.execute(f"SELECT * FROM {t}") for c in row).lower()
    for secret in ("c0551", "551", "oliviers", "100 000", "secrète", "archivée"):
        assert secret not in everything, secret
    for q in ("oliviers", "551", "cadastré", "vente immeuble"):
        assert all("oliviers" not in (r["snippet"] or "").lower() for r in db.search_public(tmp_path / "echo.db", q))


def test_names_are_scrubbed_before_they_reach_the_index(tmp_path):
    db.build_public(_public(tmp_path), tmp_path / "echo.db")
    assert db.search_public(tmp_path / "echo.db", "DUPONT") == [] and db.search_public(tmp_path / "echo.db", "Jean Dupont") == []
    assert db.search_public(tmp_path / "echo.db", "piscine")


def test_search_finds_items_and_marks_ai_written_summaries_and_filters_by_language(tmp_path):
    db.build_public(_public(tmp_path), tmp_path / "echo.db")
    hits = db.search_public(tmp_path / "echo.db", "swimming pool")
    assert hits and hits[0]["kind"] == "summary" and hits[0]["ai_written"] is True and hits[0]["lang"] == "en"
    assert "written by an AI model" in hits[0]["title"]
    fr = db.search_public(tmp_path / "echo.db", "piscine", lang="fr")
    assert fr and all(h["lang"] == "fr" and h["ai_written"] is False for h in fr) and fr[0]["original"].startswith("https://e.test/0.pdf#page=")
    assert db.search_public(tmp_path / "echo.db", "piscine", lang="nl") == []


@pytest.mark.parametrize("q", ['" OR 1=1 --', "NEAR(a b) AND *", "piscine) UNION SELECT", "'; DROP TABLE items;--", "", "   ", "***"])
def test_hostile_or_empty_queries_never_raise_or_act_as_operators(tmp_path, q):
    db.build_public(_public(tmp_path), tmp_path / "echo.db")
    assert isinstance(db.search_public(tmp_path / "echo.db", q), list)
    assert sqlite3.connect(tmp_path / "echo.db").execute("SELECT count(*) FROM items").fetchone()[0] > 0


def test_results_are_capped_and_the_database_is_opened_read_only(tmp_path):
    db.build_public(_public(tmp_path), tmp_path / "echo.db")
    assert len(db.search_public(tmp_path / "echo.db", "conseil", limit=10_000)) <= db.MAX_RESULTS
    with pytest.raises(sqlite3.OperationalError):
        con = sqlite3.connect(f"file:{tmp_path / 'echo.db'}?mode=ro", uri=True)
        con.execute("DELETE FROM items")


def test_api_search_is_rate_limited_validated_and_unavailable_without_a_database(tmp_path, monkeypatch):
    pub = _public(tmp_path)
    monkeypatch.setenv("ECHO_DB", str(tmp_path / "echo.db"))
    client = TestClient(create_app(public_dir=pub, data_dir=tmp_path))
    assert client.get("/api/search?q=piscine").status_code == 503
    db.build_public(pub, tmp_path / "echo.db")
    body = client.get("/api/search?q=piscine").json()
    assert body["results"] and "ai_disclosure" in body and "derived" in body["layer"]
    assert client.get("/api/search?q=piscine&lang=de").status_code == 422
    assert client.get("/api/search?q=" + "a" * 300).status_code == 422
