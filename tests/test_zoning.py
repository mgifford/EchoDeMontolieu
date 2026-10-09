import json

import pytest

from echo_montolieu import zoning
from echo_montolieu.fetch import StopFetching


class Resp:
    def __init__(self, status, features=None):
        self.status_code, self._f, self.headers, self.url = status, features or [], {}, "https://apicarto.ign.fr/api/gpu/x"

    def json(self):
        return {"features": self._f}


class Session:
    def __init__(self, answers):
        self.answers, self.calls, self.headers = answers, [], {}

    def get(self, url, params=None, timeout=None):
        endpoint = url.rsplit("/", 1)[1]
        self.calls.append((endpoint, params))
        a = self.answers.get(endpoint, Resp(404))
        if isinstance(a, Exception):
            raise a
        return a


def feat(**props):
    return {"geometry": None, "properties": props}


ANSWERS = {
    "municipality": Resp(200, [feat(name="Montolieu", is_rnu=False)]),
    "document": Resp(200, [feat(typedoc="PLU", name="PLU de Montolieu", status="document.production", partition="DU_11253", gpu_doc_id="abc")]),
    "zone-urba": Resp(200, [feat(libelle="UA", typezone="U"), feat(libelle="UA", typezone="U"), feat(libelle="N", typezone="N")]),
    "prescription-surf": Resp(200, [feat(libelle="Élément de patrimoine bâti à protéger", typepsc="07", stypepsc="00", txt="Lavoir"),
                                     feat(libelle="Emplacement réservé", typepsc="05")]),
    "info-surf": Resp(200, [feat(libelle="Périmètre des abords de monument historique", typeinf="01")]),
}


def test_snapshot_summarises_documents_zones_and_only_heritage_prescriptions(tmp_path):
    session = Session(ANSWERS)
    client = zoning.GpuClient(tmp_path / "c.json", session=session, sleep=lambda s: None)
    snap = zoning.fetch_snapshot(client)
    assert snap["documents"][0]["name"] == "PLU de Montolieu" and snap["documents"][0]["url"].startswith(zoning.PORTAL)
    assert {z["label"]: z["count"] for z in snap["zones"]} == {"UA": 2, "N": 1}
    labels = [p["label"] for p in snap["heritage_prescriptions"]]
    assert "Élément de patrimoine bâti à protéger" in labels and "Emplacement réservé" not in labels
    assert any("monument historique" in (p["label"] or "") for p in snap["heritage_prescriptions"])
    assert session.calls[0][1] == {"insee": "11253"}
    assert snap["endpoint_status"]["prescription-lin"] == 404          # unknown endpoints are reported, not hidden


def test_page_is_dated_cited_and_says_it_is_not_legal_advice(tmp_path):
    snap = zoning.write_zoning(tmp_path, zoning.GpuClient(tmp_path / "c.json", session=Session(ANSWERS), sleep=lambda s: None))
    page = (tmp_path / "zoning" / "index.md").read_text()
    assert "Not legal advice" in page and snap["retrieved_at"][:10] in page and zoning.PORTAL in page
    assert "## Gaps" in page and "prescription-lin (HTTP 404)" in page and "machine_generated: true" in page
    assert json.loads((tmp_path / "zoning" / "zoning.json").read_text())["insee"] == "11253"


def test_empty_answers_are_said_plainly():
    page = zoning.render_md({"source": "s", "portal": zoning.PORTAL, "retrieved_at": "2026-10-09T00:00:00+00:00", "municipality": {},
                             "documents": [], "zones": [], "heritage_prescriptions": [], "endpoint_status": {}})
    assert "no planning document" in page and "None were returned" in page


def test_client_is_polite_cached_and_stops_on_errors(tmp_path):
    waits = []
    session = Session({"zone-urba": Resp(200, [])})
    c = zoning.GpuClient(tmp_path / "c.json", session=session, sleep=waits.append, clock=lambda: 0.0, min_delay=2.0)
    c.get("zone-urba", {"partition": "A"}); c.get("zone-urba", {"partition": "B"}); c.get("zone-urba", {"partition": "A"})
    assert len(session.calls) == 2 and waits == [2.0]
    for bad in (Resp(429), Resp(503)):
        with pytest.raises(StopFetching):
            zoning.GpuClient(tmp_path / "d.json", session=Session({"document": bad})).get("document", {})
    import requests
    with pytest.raises(StopFetching):
        zoning.GpuClient(tmp_path / "e.json", session=Session({"document": requests.ConnectionError("x")})).get("document", {})


def test_landing_links_the_zoning_page_only_when_it_exists(tmp_path):
    from echo_montolieu.site import build
    public, data = tmp_path / "public", tmp_path / "data"
    public.mkdir(); data.mkdir()
    assert "zoning/index.html" not in (build(tmp_path / "a", public, data) / "en/index.html").read_text()
    (public / "zoning").mkdir()
    (public / "zoning" / "index.md").write_text("---\ntitle: z\n---\n# Planning and heritage zoning\n")
    out = build(tmp_path / "b", public, data)
    assert 'href="zoning/index.html"' in (out / "en/index.html").read_text() and (out / "en/zoning/index.html").exists()
