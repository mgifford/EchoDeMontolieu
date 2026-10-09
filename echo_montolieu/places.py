"""Places discussed in council meetings, confirmed against the national address database.

Street and place names are picked out of the minutes by pattern, which captures a lot of
ordinary French ("cours d'année", "place d'une borne"). A candidate is therefore kept only if
the Base Adresse Nationale (BAN) finds a street or locality of that name inside Montolieu with a
close name match. Everything else is dropped, not guessed.

What is deliberately NOT mapped:
  * items about sales of property (a place, a parcel and a sale together can identify a
    private seller in a village this size);
  * items whose title names a private person (the title was scrubbed);
  * private property sales in any form (they never reach this code: their places are emptied).
A pin shows where a street or place is, not the exact spot a decision concerned.
"""
import base64
import collections
import hashlib
import html
import json
import re
import time
from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import disclosure
from .fetch import USER_AGENT, StopFetching
from .privacy import _fold
from .render import page_link

# Verified against the BAN on 2026-10-08 (municipality search for "Montolieu").
COMMUNE = {"name": "Montolieu", "citycode": "11253", "postcode": "11170", "lat": 43.311995, "lon": 2.220246}
BAN_URL = "https://api-adresse.data.gouv.fr/search/"
MIN_SCORE = 0.5
SALE_TITLE = re.compile(r"\b(?:vente|cession|vendre|ceder)\b")
PARTICLES = {"de", "du", "des", "la", "le", "les", "l", "d", "en", "au", "aux", "et"}
TYPE_WORDS = {"rue", "chemin", "place", "impasse", "avenue", "route", "ruelle", "quai", "boulevard", "passage",
              "cours", "allee", "esplanade", "cote", "traverse", "carrefour", "faubourg", "ancien", "lieu", "dit",
              "rural", "communal", "departementale"}

# Marker shape per main theme, so meaning never rests on colour alone.
SHAPE_OF = {"finances": "circle", "subventions": "circle",
            "voirie et travaux": "square", "urbanisme": "square", "environnement et risques": "square",
            "patrimoine, culture, tourisme": "triangle", "associations et vie locale": "triangle",
            "école et enfance": "triangle"}
SHAPES = {"circle": ("Circle", "finances and subsidies", "#004B87"),
          "square": ("Square", "roads, works, planning and environment", "#8A3B00"),
          "triangle": ("Triangle", "heritage, culture, associations and schools", "#1F6B3A"),
          "diamond": ("Diamond", "other subjects", "#6A1B9A")}
LEAFLET_CSS_SRI = "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H"
LEAFLET_JS_SRI = "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
OSM_TOWN = (f"https://www.openstreetmap.org/?mlat={COMMUNE['lat']}&mlon={COMMUNE['lon']}"
            f"#map=16/{COMMUNE['lat']}/{COMMUNE['lon']}")


def _stem(token):
    return token[:-1] if len(token) > 4 and token[-1] in "sx" else token


def _tokens(text):
    return [_stem(t) for t in re.findall(r"[a-z]{3,}", _fold(text)) if t not in PARTICLES]


def verify(label, props):
    """Does this BAN result really name the place the minutes mention?"""
    wanted = [t for t in _tokens(label) if t not in TYPE_WORDS]
    if not wanted:
        return False
    have = set(_tokens(props.get("name", "")))
    return (props.get("citycode") == COMMUNE["citycode"] and props.get("type") in ("street", "locality")
            and props.get("score", 0) >= MIN_SCORE and all(t in have for t in wanted))


# ---- geocoding ----------------------------------------------------------------------------------


class BanGeocoder:
    """Looks places up in the BAN, one request at a time, and remembers every answer.

    The cache stores the top results (not a verdict), so the verification rules can change
    without asking the BAN again. A missing or failed lookup is cached as an empty list.
    """

    def __init__(self, cache_path, session=None, sleep=time.sleep, clock=time.monotonic, min_delay=1.0):
        self.path = Path(cache_path)
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Connection"] = "close"
        self._sleep, self._clock, self._last, self.min_delay = sleep, clock, None, min_delay
        self.requests_made = 0

    def cached(self, query):
        return self.cache.get(query, {}).get("features")

    def prune(self, keep):
        """Forget lookups for names that are no longer candidates (for example, after a sale notice
        was reclassified), so the committed cache holds nothing it does not need."""
        keep = set(keep)
        dropped = [q for q in self.cache if q not in keep]
        for q in dropped:
            del self.cache[q]
        if dropped:
            self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        return len(dropped)

    def lookup(self, query):
        if query in self.cache:
            return self.cache[query]["features"]
        if self._last is not None:
            wait = self.min_delay - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            resp = self.session.get(BAN_URL, params={"q": query, "citycode": COMMUNE["citycode"], "limit": 3}, timeout=30)
        except requests.RequestException as exc:
            raise StopFetching(f"network error for BAN query {query!r}: {exc!r}") from exc
        finally:
            self._last = self._clock()
        self.requests_made += 1
        if resp.status_code == 429 or resp.status_code >= 500:
            raise StopFetching(f"{resp.status_code} from the BAN (Retry-After: {resp.headers.get('Retry-After')})")
        resp.raise_for_status()
        features = [{"props": {k: f["properties"].get(k) for k in ("label", "name", "type", "citycode", "score")},
                     "coords": f["geometry"]["coordinates"]} for f in resp.json().get("features", [])]
        self.cache[query] = {"features": features, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        return features


# ---- from the minutes to places -------------------------------------------------------------------


# Street words that are also ordinary French ("place centrale", "cours de natation", "passage devant"): only a
# capitalised name or a well-known landmark makes them a plausible place. The rest are rarely anything else.
_AMBIGUOUS_TYPES = {"chemin", "route", "place", "cours", "passage", "traverse", "carrefour", "lieu", "ancien"}
_LANDMARKS = {"eglise", "mail", "halle", "mairie", "ecole", "source", "fontaine", "lavoir", "pont", "foyer", "cimetiere", "moulin"}


_PREP = r"(?:de la|de l[’']|du|des|de|d[’']|l[’']|la|le|les)"
_MODIFIER = r"(?:rural|rurale|communal|communale|départementale|departementale|ancien|ancienne)"
_STREET_LABEL = re.compile(rf"^(?P<type>\S+)(?:\s+{_MODIFIER})?(?:\s+{_PREP}\s*|\s+)(?P<name>\S.*)$", re.I)


def plausible(label, kind):
    """Could this unconfirmed candidate be a real place name? Used only to decide whether to offer a search link."""
    label = label.strip()
    if kind == "lieu-dit":
        return label[:1].isupper() and not label.isupper()
    m = _STREET_LABEL.match(label)
    if not m or label.endswith("-"):
        return False
    has_prep = bool(re.match(rf"^\S+(?:\s+{_MODIFIER})?\s+{_PREP}\s*\S", label, re.I))
    words = [w for w in re.findall(r"[\wÀ-ÿ]+", m.group("name")) if _fold(w) not in PARTICLES]
    if not words:
        return False
    first = words[0]
    named = first[0].isupper() and not first.isupper() and _fold(first) not in TYPE_WORDS
    landmark = _fold(first) in _LANDMARKS
    if _fold(m.group("type")) in _AMBIGUOUS_TYPES:         # "place", "cours", "chemin" are also ordinary words
        return named or landmark
    return named or (has_prep and len(words) <= 3)          # "rue des remparts" yes; "rue en traversant l'actuel espace" no


def eligible(item):
    """Items whose places may be mapped. Everything else is counted but never shown."""
    return not (item["sensitive"] or "withheld" in item["title"].lower() or SALE_TITLE.search(item["title_key"]))


def collect_candidates(meetings):
    """({query: {"kind", "occurrences"}}, number of items kept off the map)."""
    found, held_back = {}, 0
    for m in meetings:
        for it in m["meeting"]["items"]:
            if not it["places"]:
                continue
            if not eligible(it):
                held_back += 1
                continue
            for p in it["places"]:
                entry = found.setdefault(p["label"], {"kind": p["kind"], "occurrences": []})
                entry["occurrences"].append({"date": m["meeting"]["date"] or "undated", "folder": m["folder"],
                                             "title": it["title"], "page": it["pages"][0],
                                             "url": m["meeting"]["source_url"], "topics": it["topics"]})
    return found, held_back


def build_places(meetings, lookup):
    """Verified places. `lookup(query)` returns BAN features or None when it was not looked up."""
    found, held_back = collect_candidates(meetings)
    groups, unconfirmed, by_clean = {}, [], {}
    for label, info in found.items():
        features = lookup(label)
        match = next((f for f in (features or []) if verify(label, f["props"])), None)
        if not match:
            unconfirmed.append(label)
            clean = search_label(label)
            if plausible(clean, info["kind"]):
                entry = by_clean.setdefault(_fold(clean), {"label": clean, "kind": info["kind"], "search": osm_search(clean), "items": []})
                entry["items"] += [{k: o[k] for k in ("date", "folder", "page", "url")} for o in info["occurrences"]]
            continue
        lon, lat = match["coords"]
        key = (match["props"]["name"], round(lon, 4), round(lat, 4))
        g = groups.setdefault(key, {"label": match["props"]["name"], "kind": info["kind"], "lat": lat, "lon": lon,
                                    "ban_label": match["props"]["label"], "ban_score": round(match["props"]["score"], 3),
                                    "mentioned_as": [], "items": []})
        g["mentioned_as"].append(label)
        g["items"] += info["occurrences"]
    places = []
    for g in groups.values():
        seen, items = set(), []
        for o in sorted(g["items"], key=lambda o: (o["date"], o["page"])):
            if (o["date"], o["title"]) not in seen:
                seen.add((o["date"], o["title"]))
                items.append(o)
        themes = collections.Counter(t for o in items for t in o["topics"])
        main = themes.most_common(1)[0][0] if themes else None
        places.append({**{k: g[k] for k in ("label", "kind", "lat", "lon", "ban_label", "ban_score")},
                       "mentioned_as": sorted(set(g["mentioned_as"])), "items": items,
                       "themes": dict(themes), "main_theme": main, "shape": SHAPE_OF.get(main, "diamond"),
                       "meetings": len({o["date"] for o in items})})
    places.sort(key=lambda p: (-p["meetings"], p["label"]))
    return places, {"candidates": len(found), "unconfirmed": sorted(unconfirmed), "held_back_items": held_back,
                    "unconfirmed_mentions": sorted(by_clean.values(), key=lambda m: m["label"].lower())}


# ---- output -----------------------------------------------------------------------------------------


def search_label(label):
    """The place name only: cut a candidate at the first lowercase word that follows its capitalised name
    ("place des Tilleuls sont" -> "place des Tilleuls") and at a dash or bracket."""
    label = re.split(r"\s[-–(]\s|\s*[(\[]", label.strip())[0].replace("’", "'")
    out, named = [], False
    for w in label.split():
        bare = re.sub(r"^[a-zA-Zà-ÿ]'", "", w)
        if named and w[:1].islower() and _fold(w) not in PARTICLES and not w.lower().endswith("'"):
            break
        out.append(w)
        named = named or (bare[:1].isupper() and not bare.isupper() and len(out) > 1)
    return " ".join(out)


def osm_search(label):
    """OpenStreetMap's own search for a name in Montolieu. A link the reader may follow; nothing is sent from here."""
    return "https://www.openstreetmap.org/search?query=" + quote(f"{label}, {COMMUNE['name']}")


def _osm(p):
    return f"https://www.openstreetmap.org/?mlat={p['lat']:.6f}&mlon={p['lon']:.6f}#map=18/{p['lat']:.6f}/{p['lon']:.6f}"


def render_places_md(places, info):
    out = ["# Places discussed", "", disclosure.markdown("rules"), "",
           "> Machine-generated. Street and place names were picked out of the minutes by pattern and kept only "
           "if the national address database (BAN) confirms a street or locality of that name in Montolieu. A pin "
           "shows where a street or place is, not the exact spot a decision concerned.", "",
           f"- [Map of Montolieu on OpenStreetMap]({OSM_TOWN})",
           "- [Interactive map of the places below](map.html) (the table on that page lists the same places)",
           f"- {len(places)} places confirmed, from {info['candidates']} candidate names. "
           f"{len(info['unconfirmed'])} candidates were not confirmed and are not on the map"
           f"{'; the plausible ones are listed at the end with search links' if info.get('unconfirmed_mentions') else ''}.",
           f"- Not shown on purpose: {info['held_back_items']} {'item' if info['held_back_items'] == 1 else 'items'} "
           "about property sales or naming a private person.", "",
           "| Place | Type | Main theme | Meetings | Where it came up |", "|---|---|---|---|---|"]
    for p in places:
        where = "; ".join(f"{o['date']}: {o['title'][:50]} ({page_link(o['url'], o['page'])})" for o in p["items"][:4])
        more = f" (+{len(p['items']) - 4} more)" if len(p["items"]) > 4 else ""
        out.append(f"| [{p['label']}]({_osm(p)}) | {p['kind']} | {p['main_theme'] or '-'} | {p['meetings']} | {where}{more} |")
    mentions = info.get("unconfirmed_mentions") or []
    if mentions:
        out += ["", "## Names not yet confirmed", "",
                "Picked out of the minutes by pattern but not matched to a street or place in Montolieu. The links search "
                "OpenStreetMap; the result may be empty or wrong.", ""]
        out += [f"- {m['label']} ({m['kind']}): [search OpenStreetMap]({m['search']}); "
                + ", ".join(f"{o['date']} {page_link(o['url'], o['page'])}" for o in m["items"][:4]) for m in mentions]
    return "\n".join(out) + "\n"


def _sha256_b64(text):
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()


MAP_STYLE = """
:root{color-scheme:light}
body{margin:0;font:1rem/1.6 system-ui,-apple-system,sans-serif;background:#FBF9F5;color:#1A1A1A}
header{background:#004B87;color:#fff;padding:1rem 1.5rem}
header h1{margin:0;font-size:1.5rem}
main{max-width:70rem;margin:0 auto;padding:1rem 1.5rem;overflow-wrap:anywhere}
a{color:#004B87}
a:focus-visible,button:focus-visible,.leaflet-container:focus-visible{outline:3px solid #005A9C;outline-offset:2px}
.skip{position:absolute;left:-999px}
.skip:focus{left:1rem;top:1rem;background:#fff;padding:.5rem 1rem;z-index:2000}
#map{height:60vh;min-height:24rem;border:1px solid #1A1A1A;margin:1rem 0}
.leaflet-marker-icon:focus-visible{outline:3px solid #1A1A1A;box-shadow:0 0 0 6px #fff}
.legend{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:.5rem 1.5rem}
.legend li{display:flex;align-items:center;gap:.5rem}
table{border-collapse:collapse;width:100%;font-size:.95rem}
caption{text-align:left;font-weight:bold;padding:.5rem 0}
th,td{border:1px solid #6b6b6b;padding:.4rem .6rem;text-align:left;vertical-align:top}
th{background:#EBF3FA}
.note{font-size:.95rem}
.ai{border-left:6px solid #6b6b6b;background:#F1EFEA;padding:.25rem 1rem}
"""


def _svg(shape, fill, size=28):
    c = size / 2
    body = {"circle": f'<circle cx="{c}" cy="{c}" r="{c - 3}"/>',
            "square": f'<rect x="3" y="3" width="{size - 6}" height="{size - 6}"/>',
            "triangle": f'<polygon points="{c},3 {size - 3},{size - 3} 3,{size - 3}"/>',
            "diamond": f'<polygon points="{c},3 {size - 3},{c} {c},{size - 3} 3,{c}"/>'}[shape]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'aria-hidden="true" focusable="false"><g fill="{fill}" stroke="#ffffff" stroke-width="2">{body}</g></svg>')


MAP_SCRIPT = """
(function () {
  var data = JSON.parse(document.getElementById('places-data').textContent);
  if (!window.L || !data.places.length) { return; }
  var map = L.map('map', {keyboard: true}).setView([data.center.lat, data.center.lon], 16);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
  data.places.forEach(function (p) {
    var icon = L.divIcon({className: '', html: data.shapes[p.shape], iconSize: [44, 44], iconAnchor: [22, 22]});
    var text = p.label + ', ' + p.meetings + (p.meetings === 1 ? ' meeting' : ' meetings');
    var marker = L.marker([p.lat, p.lon], {icon: icon, title: text, keyboard: true}).addTo(map);
    var box = document.createElement('div');
    var h = document.createElement('strong'); h.textContent = p.label; box.appendChild(h);
    var ul = document.createElement('ul');
    p.items.slice(0, 5).forEach(function (o) {
      var li = document.createElement('li'); var a = document.createElement('a');
      a.href = o.url + '#page=' + o.page; a.textContent = o.date + ': ' + o.title;
      li.appendChild(a); ul.appendChild(li);
    });
    box.appendChild(ul); marker.bindPopup(box);
    var el = marker.getElement();
    if (el) {
      el.setAttribute('role', 'button'); el.setAttribute('aria-label', text + '. Press Enter for details.');
      // Tab visits every marker, including those outside the opening view: bring the focused one into view.
      el.addEventListener('focus', function () { map.panInside(marker.getLatLng(), {padding: [60, 60]}); });
    }
  });
})();
"""


def _farthest_km(places):
    import math
    cy = COMMUNE["lat"]
    return max((math.hypot((p["lon"] - COMMUNE["lon"]) * 111.32 * math.cos(math.radians(cy)),
                           (p["lat"] - cy) * 110.574) for p in places), default=0.0)


def render_map_html(places, info):
    far = f"{_farthest_km(places):.1f}".rstrip("0").rstrip(".")
    data = {"center": {"lat": COMMUNE["lat"], "lon": COMMUNE["lon"]},
            "shapes": {k: _svg(k, v[2], 44) for k, v in SHAPES.items()},
            "places": [{k: p[k] for k in ("label", "lat", "lon", "meetings", "shape", "items")}
                       | {"items": [{k: o[k] for k in ("date", "title", "page", "url")} for o in p["items"]]}
                       for p in places]}
    # Every "<" becomes \u003c: JSON still parses it, and nothing in the data can open or close a tag.
    data_json = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    csp = ("default-src 'none'; "
           f"script-src '{_sha256_b64(MAP_SCRIPT)}' https://unpkg.com; "
           f"style-src '{_sha256_b64(MAP_STYLE)}' https://unpkg.com; "
           "img-src https://tile.openstreetmap.org https://unpkg.com data:; "
           "base-uri 'none'; form-action 'none'")
    e = html.escape
    legend = "".join(f"<li>{_svg(k, v[2])}<span>{e(v[0])}: {e(v[1])}</span></li>" for k, v in SHAPES.items())
    rows = []
    for p in places:
        items = "".join(f'<li><a href="{e(o["url"])}#page={o["page"]}">{e(o["date"])}: {e(o["title"])}</a></li>' for o in p["items"][:6])
        theme = f'{e(SHAPES[p["shape"]][0])}, {e(p["main_theme"] or "other")}'
        rows.append(f'<tr><th scope="row"><a href="{e(_osm(p))}">{e(p["label"])}</a></th><td>{e(p["kind"])}</td>'
                    f'<td>{theme}</td><td>{p["meetings"]}</td><td><ul>{items}</ul></td></tr>')
    table = ("<table><caption>Places discussed in council meetings</caption><thead><tr><th scope=\"col\">Place (opens "
             "OpenStreetMap)</th><th scope=\"col\">Type</th><th scope=\"col\">Marker and main theme</th>"
             "<th scope=\"col\">Meetings</th><th scope=\"col\">Where it came up</th></tr></thead><tbody>"
             + "".join(rows) + "</tbody></table>") if places else "<p>No places have been confirmed yet.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>Places discussed in Montolieu council meetings</title>
<meta name="description" content="A map and a table of streets and places that came up in Montolieu council meetings.">
<style>{MAP_STYLE}</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="{LEAFLET_CSS_SRI}" crossorigin="">
</head>
<body>
<a class="skip" href="#list">Skip the map and go to the list of places</a>
<header><h1>Places discussed in council meetings</h1></header>
<main id="main">
<p>Streets and places that came up in the council minutes, confirmed against the national address database
(BAN). A marker shows where a street or place is, not the exact spot a decision concerned. Sales of property
and items naming a private person are not shown ({info['held_back_items']} {'item' if info['held_back_items'] == 1 else 'items'} kept off this page on purpose).
The map opens on the village; places up to about {far} km away appear when you zoom out, and every place is in the list below.
<a href="{e(OSM_TOWN)}">Map of Montolieu on OpenStreetMap</a>. <a href="../index.html">Back to the home page</a>.</p>
{disclosure.html("rules")}
<noscript><p>The interactive map needs JavaScript. The list below has the same places and works without it.</p></noscript>
<p class="note">The map loads its code from unpkg.com and its tiles from OpenStreetMap, which therefore see your
address when it loads. The list does not.</p>
<h2>Map</h2>
<ul class="legend" aria-label="Marker shapes">{legend}</ul>
<div id="map" role="region" aria-label="Map of places discussed. The same places are listed in the table below."></div>
<h2 id="list">List of places</h2>
{table}
<script type="application/json" id="places-data">{data_json}</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="{LEAFLET_JS_SRI}" crossorigin=""></script>
<script>{MAP_SCRIPT}</script>
</main>
</body>
</html>
"""


def write_places(public_dir, meetings, lookup):
    target = Path(public_dir) / "places"
    target.mkdir(parents=True, exist_ok=True)
    places, info = build_places(meetings, lookup)
    (target / "places.json").write_text(json.dumps({"commune": COMMUNE, **disclosure.labels("rules"), "places": places, **{k: v for k, v in info.items() if k != "unconfirmed"}},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    (target / "index.md").write_text(disclosure.with_front_matter(render_places_md(places, info), "Places discussed"), encoding="utf-8")
    (target / "map.html").write_text(render_map_html(places, info), encoding="utf-8")
    return {"places": len(places), "candidates": info["candidates"], "unconfirmed": len(info["unconfirmed"]),
            "held_back_items": info["held_back_items"]}
