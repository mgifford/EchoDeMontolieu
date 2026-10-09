import hashlib
import base64
import json
import re

import pytest
import requests

from echo_montolieu import places as pl
from echo_montolieu.fetch import StopFetching
from tests.test_threads import item, meeting


def feat(name, type_="street", citycode="11253", score=0.94, coords=(2.2136, 43.3102)):
    return {"props": {"label": f"{name} 11170 Montolieu", "name": name, "type": type_, "citycode": citycode, "score": score},
            "coords": list(coords)}


def with_places(n, date, title, places, text="Texte de l’élément sur le sujet en question pour la commune.", **kw):
    it = item(n, date, title, text, **kw)
    it["places"] = [{"kind": k, "label": label, "number": None} for k, label in places]
    return it


# ---- verification --------------------------------------------------------------------------------


def test_a_result_must_be_in_montolieu_a_street_or_locality_and_share_the_name():
    ok = {"name": "Rue des Remparts", "type": "street", "citycode": "11253", "score": 0.95}
    assert pl.verify("rue des remparts", ok)
    assert not pl.verify("rue des remparts", {**ok, "citycode": "11262"})        # Narbonne has one too
    assert not pl.verify("rue des remparts", {**ok, "type": "municipality"})
    assert not pl.verify("rue des remparts", {**ok, "score": 0.3})
    assert not pl.verify("rue des tilleuls", ok)                                 # a different name
    assert not pl.verify("rue de", ok)                                           # nothing but a type word


def test_plurals_accents_and_case_do_not_defeat_a_match():
    assert pl.verify("chemin des Brétous", {"name": "Chemin des Bretous", "type": "street", "citycode": "11253", "score": 0.9})
    assert pl.verify("Cazelles", {"name": "Cazelle", "type": "locality", "citycode": "11253", "score": 0.9})
    assert pl.verify("rue DES OLIVIERS", {"name": "Rue des Oliviers", "type": "street", "citycode": "11253", "score": 0.9})


# ---- the geocoder ----------------------------------------------------------------------------------


class Resp:
    def __init__(self, status=200, features=None):
        self.status_code, self._f, self.headers = status, features or [], {}

    def json(self):
        return {"features": [{"properties": f["props"], "geometry": {"coordinates": f["coords"]}} for f in self._f]}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, resp=None):
        self.calls, self.headers, self.resp = [], {}, resp or Resp(features=[feat("Rue des Remparts")])

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def geocoder(tmp_path, session=None):
    c = Clock()
    return pl.BanGeocoder(tmp_path / "cache.json", session or Session(), sleep=c.sleep, clock=c.now), c


def test_lookups_are_cached_restricted_to_montolieu_and_sent_with_a_descriptive_user_agent(tmp_path):
    g, _ = geocoder(tmp_path)
    first = g.lookup("rue des remparts")
    assert first[0]["props"]["name"] == "Rue des Remparts"
    assert g.session.calls[0][1] == {"q": "rue des remparts", "citycode": "11253", "limit": 3}
    assert "EchoDeMontolieu" in g.session.headers["User-Agent"]
    g.lookup("rue des remparts")
    assert len(g.session.calls) == 1                                  # second lookup: cache
    reopened = pl.BanGeocoder(tmp_path / "cache.json", Session())
    assert reopened.cached("rue des remparts")[0]["coords"] == [2.2136, 43.3102]


def test_requests_are_spaced_and_an_empty_answer_is_cached_so_it_is_not_asked_again(tmp_path):
    g, clock = geocoder(tmp_path, Session(Resp(features=[])))
    g.lookup("route de nulle part")
    g.lookup("place de rien")
    assert sum(clock.slept) >= 1.0 - 1e-6 and g.cached("route de nulle part") == []
    g.lookup("route de nulle part")
    assert len(g.session.calls) == 2


def test_a_rate_limit_or_network_error_stops_cleanly(tmp_path):
    g, _ = geocoder(tmp_path, Session(Resp(status=429)))
    with pytest.raises(StopFetching, match="429"):
        g.lookup("x")
    g2, _ = geocoder(tmp_path / "b", Session(requests.ConnectionError("down")))
    with pytest.raises(StopFetching, match="network error"):
        g2.lookup("x")
    assert g.cached("x") is None                                       # a failure is never cached as "no place"


# ---- what is mapped, and what is not -----------------------------------------------------------------


def sample():
    return [
        meeting("2024-01-10", [with_places(1, "2024-01-10", "Travaux de voirie", [("street", "rue des remparts")], topics=("voirie et travaux",)),
                               with_places(2, "2024-01-10", "Vente d’un immeuble", [("street", "rue des oliviers")]),
                               with_places(3, "2024-01-10", "Demande de [name withheld]", [("street", "impasse de la gare")]),
                               with_places(4, "2024-01-10", "Idée", [("street", "cours d’année")])]),
        meeting("2024-03-10", [with_places(1, "2024-03-10", "Réfection de la rue", [("street", "rue des remparts")], topics=("voirie et travaux",)),
                               with_places(2, "2024-03-10", "Fête", [("lieu-dit", "Borderouge")], topics=("finances",))]),
    ]


LOOKUP = {"rue des remparts": [feat("Rue des Remparts")], "rue des oliviers": [feat("Rue des Oliviers")],
          "impasse de la gare": [feat("Impasse de la Gare")], "cours d’année": [feat("Chemin du Cours")],
          "Borderouge": [feat("Borderouge", "locality", coords=(2.2153, 43.3357))]}


def test_only_verified_places_from_eligible_items_reach_the_map():
    places, info = pl.build_places(sample(), LOOKUP.get)
    assert [p["label"] for p in places] == ["Rue des Remparts", "Borderouge"]
    assert info["held_back_items"] == 2                                # the sale and the private person
    assert info["unconfirmed"] == ["cours d’année"]                    # ordinary French, not a place
    remparts = places[0]
    assert remparts["meetings"] == 2 and [o["date"] for o in remparts["items"]] == ["2024-01-10", "2024-03-10"]
    assert remparts["shape"] == "square" and places[1]["shape"] == "circle"


def test_places_named_differently_but_resolving_to_one_street_are_merged():
    m = [meeting("2024-01-10", [with_places(1, "2024-01-10", "A", [("lieu-dit", "Cazelle")]),
                                with_places(2, "2024-01-10", "B", [("lieu-dit", "Cazelles")])])]
    lookup = {"Cazelle": [feat("Cazelle", "locality")], "Cazelles": [feat("Cazelle", "locality")]}
    places, _ = pl.build_places(m, lookup.get)
    assert len(places) == 1 and places[0]["mentioned_as"] == ["Cazelle", "Cazelles"]


def test_a_name_not_yet_looked_up_is_unconfirmed_not_guessed():
    places, info = pl.build_places(sample(), lambda q: None)
    assert places == [] and len(info["unconfirmed"]) == 3


def test_private_sale_items_never_contribute_places_even_if_something_slips_through():
    m = [meeting("2024-01-10", [with_places(1, "2024-01-10", "Droits de préemption", [("street", "rue des remparts")], sensitive=True)])]
    places, info = pl.build_places(m, LOOKUP.get)
    assert places == [] and info["held_back_items"] == 1


# ---- the pages -----------------------------------------------------------------------------------------


def built(tmp_path):
    return pl.write_places(tmp_path, sample(), LOOKUP.get), tmp_path / "places"


def test_files_are_written_and_json_has_no_sale_or_private_details(tmp_path):
    info, folder = built(tmp_path)
    assert info == {"places": 2, "candidates": 3, "unconfirmed": 1, "held_back_items": 2}
    blob = (folder / "places.json").read_text(encoding="utf-8") + (folder / "index.md").read_text(encoding="utf-8") \
        + (folder / "map.html").read_text(encoding="utf-8")
    assert "oliviers" not in blob.lower() and "gare" not in blob.lower() and "withheld" not in blob


def test_markdown_list_links_osm_and_says_what_was_left_out(tmp_path):
    _, folder = built(tmp_path)
    md = (folder / "index.md").read_text(encoding="utf-8")
    assert "openstreetmap.org/?mlat=43.311995" in md and "2 places confirmed, from 3 candidate names" in md
    assert "Not shown on purpose: 2 items about property sales or naming a private person" in md
    assert "| [Rue des Remparts](" in md and "#page=1" in md


def test_map_page_has_the_list_the_skip_link_the_legend_and_a_noscript_fallback(tmp_path):
    _, folder = built(tmp_path)
    page = (folder / "map.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in page and "<title>" in page and page.count("<h1>") == 1
    assert 'class="skip" href="#list"' in page and 'id="list"' in page
    assert "<table><caption>" in page and 'scope="row"' in page and 'scope="col"' in page
    assert "<noscript>" in page and "needs JavaScript" in page
    for shape in ("Circle", "Square", "Triangle", "Diamond"):
        assert f"{shape}:" in page                                              # the legend names every shape
    assert 'role="region" aria-label="Map of places discussed' in page
    assert 'aria-hidden="true"' in page                                         # decorative legend svgs


def test_third_party_files_are_pinned_with_integrity_and_the_csp_matches_the_inline_code(tmp_path):
    _, folder = built(tmp_path)
    page = (folder / "map.html").read_text(encoding="utf-8")
    assert f'integrity="{pl.LEAFLET_JS_SRI}"' in page and f'integrity="{pl.LEAFLET_CSS_SRI}"' in page
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page).group(1)
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    h = lambda t: "sha256-" + base64.b64encode(hashlib.sha256(t.encode()).digest()).decode()
    assert h(script) in csp and h(style) in csp and "default-src 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_data_is_embedded_safely_and_the_script_builds_popups_without_innerhtml_of_data(tmp_path):
    _, folder = built(tmp_path)
    page = (folder / "map.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'id="places-data">(.*?)</script>', page, re.S).group(1))
    assert [p["label"] for p in data["places"]] == ["Rue des Remparts", "Borderouge"]
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    assert "innerHTML" not in script and "textContent" in script
    hostile = [meeting("2024-01-10", [with_places(1, "2024-01-10", "</script><script>alert(1)</script>", [("street", "rue des remparts")])])]
    pl.write_places(tmp_path / "x", hostile, LOOKUP.get)
    out = (tmp_path / "x" / "places" / "map.html").read_text(encoding="utf-8")
    assert "<script>alert(1)" not in out and out.count("</script>") == 3 and "<" not in re.search(r'id="places-data">(.*?)</script>', out, re.S).group(1)
    assert "&lt;/script&gt;" in out                                              # escaped in the table


def test_the_map_opens_at_village_scale_so_44px_targets_never_overlap_and_focus_pans_into_view(tmp_path):
    _, folder = built(tmp_path)
    page = (folder / "map.html").read_text(encoding="utf-8")
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    assert "setView([data.center.lat, data.center.lon], 16)" in script and "fitBounds" not in script
    assert "panInside" in script and "addEventListener('focus'" in script
    assert "The map opens on the village; places up to about" in page and "zoom out" in page


def test_the_closest_real_places_stay_at_least_44px_apart_at_the_opening_zoom():
    import itertools, json, math
    from pathlib import Path
    data = json.loads(Path("public/places/places.json").read_text(encoding="utf-8"))
    def px(a, b, z=16):
        mpp = 156543.03392 * math.cos(math.radians(a["lat"])) / 2 ** z
        return math.hypot((a["lon"] - b["lon"]) * 111320 * math.cos(math.radians(a["lat"])), (a["lat"] - b["lat"]) * 110574) / mpp
    assert min(px(a, b) for a, b in itertools.combinations(data["places"], 2)) >= 44


def test_prune_drops_lookups_for_names_that_are_no_longer_candidates(tmp_path):
    g, _ = geocoder(tmp_path)
    g.lookup("rue des remparts")
    g.lookup("rue bellevue")
    assert g.prune(["rue des remparts"]) == 1
    reopened = pl.BanGeocoder(tmp_path / "cache.json", Session())
    assert reopened.cached("rue des remparts") and reopened.cached("rue bellevue") is None
    assert g.prune(["rue des remparts"]) == 0


def test_search_links_are_offered_only_for_plausible_names_and_are_cut_at_the_name():
    from echo_montolieu import places as pl
    assert pl.plausible("place du Foirail", "street") and pl.plausible("rue des remparts", "street") and pl.plausible("Boulzons", "lieu-dit")
    for junk in ("place centrale", "cours de natation", "chemin de", "rue en traversant l’actuel espace", "place de STECAL", "passage devant"):
        assert not pl.plausible(junk, "street"), junk
    assert pl.search_label("place des Tilleuls sont") == "place des Tilleuls"
    assert pl.search_label("côte d'Escudié - début de") == "côte d'Escudié"
    assert pl.osm_search("place du Foirail") == "https://www.openstreetmap.org/search?query=place%20du%20Foirail%2C%20Montolieu"


def test_archived_minutes_give_place_candidates_without_sale_passages_or_names(tmp_path):
    import json
    from echo_montolieu import archive_digest as ad
    public = tmp_path / "public"; (public / "minutes").mkdir(parents=True)
    text = ("Etaient présents : DRIEUX. OLIVIER. DELPERIER.\nSecrétariat de séance : OLIVIER.\n"
            "Les travaux de la place du Foirail sont décidés. Le budget est voté. Droit de préemption sur la maison de Mme DUPUIS située rue des Rames. "
            "Le conseil s’oppose. Le chemin de Peyremale est refait.")
    rec = {"document_id": "d1", "origin": "wayback", "source_url": "https://web.archive.org/x.pdf", "meeting_date": {"value": "2005-01-25"},
           "pages": [{"page": 1, "text": text}]}
    (public / "minutes" / "d1.json").write_text(json.dumps(rec))
    (public / "index.json").write_text(json.dumps({"documents": [{"document_id": "d1", "file": "minutes/d1.json", "meeting_date": {"value": "2005-01-25"}, "filename": "x.pdf"}]}))
    from echo_montolieu.places import search_label
    labels = {search_label(p["label"]) for m in ad.place_meetings(public) for it in m["meeting"]["items"] for p in it["places"]}
    assert "place du Foirail" in labels and "chemin de Peyremale" in labels and "rue des Rames" not in labels
