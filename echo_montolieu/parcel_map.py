"""A local-only map of the parcels named in the sale notices, from the IGN cadastre API.

Reads the private database, asks the IGN APICarto service for the outline of each distinct parcel
(one polite request per new parcel, remembered in a cache under private/), and writes one HTML page
under private/. The page is for the maintainer to open from disk. It is never published.
"""
import html
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .fetch import USER_AGENT, StopFetching
from .places import COMMUNE, LEAFLET_CSS_SRI, LEAFLET_JS_SRI
from .private_db import require_private_path

IGN_URL = "https://apicarto.ign.fr/api/cadastre/parcelle"


def ign_section(section):
    """The cadastre writes a one-letter section with a leading zero ('C' is '0C')."""
    return section.rjust(2, "0")


class ParcelLookup:
    """One request per new parcel, at least `min_delay` seconds apart, every answer cached (empty answers too).
    A 429, a server error or a network error stops the run."""

    def __init__(self, cache_path, session=None, sleep=time.sleep, clock=time.monotonic, min_delay=2.0):
        self.path = require_private_path(cache_path)
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Connection"] = "close"
        self._sleep, self._clock, self._last, self.min_delay = sleep, clock, None, min_delay
        self.requests_made = 0

    @staticmethod
    def key(section, number):
        return f"{ign_section(section)}{number}"

    def cached(self, section, number):
        return self.cache.get(self.key(section, number), {}).get("features")

    def lookup(self, section, number):
        k = self.key(section, number)
        if k in self.cache:
            return self.cache[k]["features"]
        if self._last is not None:
            wait = self.min_delay - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            resp = self.session.get(IGN_URL, params={"code_insee": COMMUNE["citycode"], "section": ign_section(section),
                                                     "numero": number}, timeout=30)
        except requests.RequestException as exc:
            raise StopFetching(f"network error for IGN parcel {k}: {exc!r}") from exc
        finally:
            self._last = self._clock()
        self.requests_made += 1
        if resp.status_code == 429 or resp.status_code >= 500:
            raise StopFetching(f"{resp.status_code} from the IGN API (Retry-After: {resp.headers.get('Retry-After')})")
        if resp.status_code >= 400:
            features = []            # unknown parcel or refused parameters: remember, do not retry
        else:
            features = [{"geometry": f.get("geometry"), "props": {x: (f.get("properties") or {}).get(x)
                         for x in ("idu", "section", "numero", "contenance", "nom_com")}}
                        for f in resp.json().get("features", [])]
        self.cache[k] = {"features": features, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        return features


def distinct_parcels(db_path):
    """[{section, number, mentions: [{date, page, form, ocr, context}]}], most-mentioned first."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        out = {}
        for r in db.execute("""SELECT p.section, p.number, p.page, p.form, p.ocr, p.context, m.date, g.page_url
                               FROM parcels p JOIN meetings m ON m.id = p.meeting_id
                               JOIN pages g ON g.meeting_id = p.meeting_id AND g.page = p.page
                               ORDER BY m.date"""):
            d = out.setdefault((r["section"], r["number"]), {"section": r["section"], "number": r["number"], "mentions": []})
            d["mentions"].append({k: r[k] for k in ("date", "page", "form", "ocr", "context", "page_url")})
        return sorted(out.values(), key=lambda d: (-len(d["mentions"]), d["section"], d["number"]))
    finally:
        db.close()


def build_parcel_map(db_path, lookup, out_path, fetch=True):
    """Look up every parcel (when `fetch`), write the map page. Returns counts."""
    out = require_private_path(out_path)
    parcels = distinct_parcels(db_path)
    features, unknown, pending = [], [], 0
    for p in parcels:
        found = lookup.cached(p["section"], p["number"])
        if found is None and fetch:
            found = lookup.lookup(p["section"], p["number"])
        if found is None:
            pending += 1
            p["status"] = "not looked up yet"
        elif not found:
            unknown.append(p)
            p["status"] = "not found at the IGN"
        else:
            p["found"] = True
            p["status"] = "on the map"
            for f in found:
                features.append({"type": "Feature", "geometry": f["geometry"],
                                 "properties": {"label": f"{p['section']} {p['number']}", "mentions": len(p["mentions"])}})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(parcels, features), encoding="utf-8")
    return {"parcels": len(parcels), "mapped": len([p for p in parcels if p.get("found")]), "not_found": len(unknown),
            "not_looked_up": pending, "requests": lookup.requests_made}


def render_html(parcels, features):
    e = html.escape
    rows = []
    for p in parcels:
        rows.append(f"<tr><th scope=\"row\">{e(p['section'])} {e(p['number'])}</th><td>{len(p['mentions'])}</td>"
                    f"<td>{e(p.get('status', ''))}</td><td><ul>" + "".join(
            f"<li>{e(m['date'] or 'undated')}, <a href=\"{e(m['page_url'] or '#')}\">page {m['page']}</a> ({e(m['form'])}"
            f"{', OCR: check the page' if m['ocr'] else ''}): <q lang=\"fr\">{e(m['context'])}</q></li>" for m in p["mentions"])
            + f"</ul></td></tr>")
    geo = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'unsafe-inline' https://unpkg.com; img-src https://tile.openstreetmap.org https://unpkg.com data:; connect-src 'none'">
<meta name="robots" content="noindex,nofollow">
<title>Private: parcels named in sale notices</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="{LEAFLET_CSS_SRI}" crossorigin="">
<style>body{{font:1rem/1.6 system-ui,sans-serif;margin:0 auto;max-width:60rem;padding:1rem}}#map{{height:28rem;border:2px solid #004B87}}
.private{{border:3px solid #8a1c1c;background:#fbeaea;padding:.5rem 1rem}}th,td{{border:1px solid #6b6b6b;padding:.4rem;text-align:left;vertical-align:top}}
table{{border-collapse:collapse;width:100%}}a:focus-visible{{outline:3px solid #005A9C;outline-offset:2px}}</style></head>
<body><main>
<h1>Parcels named in the sale notices</h1>
<p class="private" role="note"><strong>Private.</strong> For the maintainer only. Do not publish, share or commit this page. Parcel references were read from the minutes by rules; pages read by OCR can be wrong, so check each against the original page.</p>
<div id="map" role="img" aria-label="Map of the parcels listed in the table below"></div>
<p class="note">Outlines from the IGN cadastre API (APICarto). The map loads its code from unpkg.com and tiles from OpenStreetMap.</p>
<h2>The same parcels as a table</h2>
<div style="overflow-x:auto"><table><thead><tr><th scope="col">Parcel</th><th scope="col">Mentions</th><th scope="col">Status</th><th scope="col">Where</th></tr></thead><tbody>
{''.join(rows)}</tbody></table></div>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="{LEAFLET_JS_SRI}" crossorigin=""></script>
<script>
var map = L.map('map').setView([{COMMUNE['lat']}, {COMMUNE['lon']}], 15);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'}}).addTo(map);
var layer = L.geoJSON({geo}, {{onEachFeature: function (f, l) {{ l.bindPopup(f.properties.label + ' (' + f.properties.mentions + ' mention(s))'); }}}}).addTo(map);
if (layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {{maxZoom: 17}});
</script></body></html>
"""
