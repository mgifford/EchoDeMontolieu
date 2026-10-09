import json
import sqlite3

import pytest

from echo_montolieu import parcel_map, private_db
from echo_montolieu.fetch import StopFetching

STACKED = ("Désignation du bien vendu :\nRéf. Cadastrale :\nSection\nN°\nLieu-dit\nSuperficie totale\n"
           "AB\n99\n6 Rue de l’indépendance\n40 m²\nC\n0154\nLes Vignes\n10 a\nUsage : Habitation\nPrix de vente : 83 000 euros\n")


def _refs(text, ocr=False):
    return {(s, n, f) for s, n, f, _ in private_db.parcel_references(text, ocr)}


def test_parcels_are_read_from_inline_stacked_table_and_bare_forms():
    assert ("C", "0551", "inline") in _refs("VENTE D’UN IMMEUBLE CADASTREE C 551 M. le maire")
    assert ("AB", "0204", "inline") in _refs("la parcelle cadastrée section AB n°204 d'un")
    assert {("AB", "0099", "table"), ("C", "0154", "table")} <= _refs(STACKED)
    assert ("AB", "0423", "bare") in _refs("Réf. Cadastrale\nVendeur(s) : Mme X\nAB0423 | AB0422")
    assert private_db.parcel_references("Le conseil approuve le budget AB0423", False) == []   # no cadastre on the page


def test_ocr_letter_errors_are_corrected_only_on_ocr_pages():
    text = "Réf. Cadastrale :\n| Section | N° | Lieudt |\n| ÆB | 490 | 17 Rue |"
    assert ("AB", "0490", "table") in _refs(text, ocr=True)
    assert not _refs(text, ocr=False)


def test_private_database_refuses_to_be_written_outside_a_private_folder(tmp_path):
    with pytest.raises(ValueError):
        private_db.build_private(tmp_path, tmp_path / "echo.db")
    with pytest.raises(ValueError):
        parcel_map.ParcelLookup(tmp_path / "cache.json")


def _public(tmp_path):
    public = tmp_path / "public"
    (public / "minutes").mkdir(parents=True)
    rec = {"document_id": "d1", "version": 1, "source_url": "https://example.org/x.pdf", "source_sha256": "ab",
           "meeting_date": {"value": "2025-03-06"}, "pages": [
               {"page": 1, "method": "text_layer", "status": "machine_extracted", "page_url": "https://example.org/x.pdf#page=1",
                "text": "M. DUPONT Jean propose la vente.\n" + STACKED}]}
    (public / "minutes" / "d1.json").write_text(json.dumps(rec))
    (public / "index.json").write_text(json.dumps({"documents": [{"document_id": "d1", "file": "minutes/d1.json"}]}))
    return public


def test_build_and_search_keep_the_faithful_text_and_the_parcels(tmp_path):
    out = tmp_path / "private" / "echo-private.db"
    counts = private_db.build_private(_public(tmp_path), out)
    assert counts["parcels"] == 2 and counts["pages"] == 1
    hits = private_db.search_private(out, "dupont")
    assert hits and hits[0]["meeting_date"] == "2025-03-06" and hits[0]["page"] == 1
    db = sqlite3.connect(out)
    assert db.execute("select value from build_info where key='layer'").fetchone()[0].startswith("PRIVATE")


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self._payload, self.headers = status, payload or {}, {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self.responses.pop(0)


def _feature(idu):
    return {"geometry": {"type": "Polygon", "coordinates": [[[2.2, 43.3], [2.21, 43.3], [2.21, 43.31], [2.2, 43.3]]]},
            "properties": {"idu": idu, "section": "AB", "numero": "0099"}}


def test_lookup_is_polite_cached_and_pads_one_letter_sections(tmp_path):
    waits = []
    session = FakeSession(FakeResponse(200, {"features": [_feature("11253000AB0099")]}), FakeResponse(200, {"features": []}))
    lookup = parcel_map.ParcelLookup(tmp_path / "private" / "c.json", session=session, sleep=waits.append, clock=lambda: 0.0, min_delay=2.0)
    assert lookup.lookup("AB", "0099")[0]["props"]["idu"] == "11253000AB0099"
    assert lookup.lookup("C", "0154") == []
    assert lookup.lookup("AB", "0099") and len(session.calls) == 2           # second call served from the cache
    assert session.calls[1]["section"] == "0C" and session.calls[0]["code_insee"] == "11253"
    assert waits == [2.0]
    assert parcel_map.ParcelLookup(tmp_path / "private" / "c.json", session=FakeSession()).cached("C", "0154") == []


def test_lookup_stops_on_429(tmp_path):
    lookup = parcel_map.ParcelLookup(tmp_path / "private" / "c.json", session=FakeSession(FakeResponse(429)))
    with pytest.raises(StopFetching):
        lookup.lookup("AB", "0099")
    assert lookup.cached("AB", "0099") is None


def test_map_page_lists_every_parcel_in_a_table_and_marks_it_private(tmp_path):
    db = tmp_path / "private" / "echo-private.db"
    private_db.build_private(_public(tmp_path), db)
    session = FakeSession(FakeResponse(200, {"features": [_feature("a")]}), FakeResponse(200, {"features": []}))
    lookup = parcel_map.ParcelLookup(tmp_path / "private" / "c.json", session=session, sleep=lambda s: None)
    out = tmp_path / "private" / "parcels.html"
    counts = parcel_map.build_parcel_map(db, lookup, out)
    page = out.read_text()
    assert counts["parcels"] == 2 and counts["mapped"] == 1 and counts["not_found"] == 1
    assert "Private." in page and 'name="robots" content="noindex,nofollow"' in page
    assert "AB 0099" in page and "C 0154" in page and "not found at the IGN" in page and "on the map" in page
    assert "#page=1" in page
