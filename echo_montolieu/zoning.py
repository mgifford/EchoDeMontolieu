"""Planning and heritage zoning for Montolieu, taken only from the national planning portal.

The Géoportail de l'urbanisme (GPU) is the official register of local planning documents. Its
open API (IGN APICarto, module "gpu") is asked a few questions about the commune, politely, and the
answers are kept in a dated snapshot with the address of each source. Nothing here interprets the
law: a prescription's code is passed on as the portal gives it, and the page says it is not legal advice.

The snapshot is fetched here, on the maintainer's machine, and published as plain files. The website,
the API and the MCP server read the snapshot; none of them makes a live request for a visitor, so a
visitor's question about a place is never sent to a third party.

The endpoints and field names follow the APICarto documentation as the author knew it. They have not
been checked against the live service from the build environment; `fetch_snapshot` records which
endpoints answered and which did not, so a mismatch shows up in the page instead of as a gap.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import disclosure
from .fetch import USER_AGENT, StopFetching
from .places import COMMUNE

API = "https://apicarto.ign.fr/api/gpu/"
PORTAL = "https://www.geoportail-urbanisme.gouv.fr/"
# Words that make a prescription or zone relevant to heritage. Used to select, never to interpret.
HERITAGE = re.compile(r"patrimoin|prot[eé]g|historique|monument|ABF|architect|paysag|cath|remarquable|site class|[eé]difice", re.I)
ENDPOINTS = ("municipality", "document", "zone-urba", "prescription-surf", "prescription-lin", "prescription-pct", "info-surf")


class GpuClient:
    """One request per new question, at least `min_delay` seconds apart; every answer cached, failures
    of a single endpoint (4xx) remembered as such; 429, server errors and network errors stop the run."""

    def __init__(self, cache_path, session=None, sleep=time.sleep, clock=time.monotonic, min_delay=2.0):
        self.path = Path(cache_path)
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Connection"] = "close"
        self._sleep, self._clock, self._last, self.min_delay = sleep, clock, None, min_delay
        self.requests_made = 0

    def get(self, endpoint, params):
        key = endpoint + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if key in self.cache:
            return self.cache[key]
        if self._last is not None:
            wait = self.min_delay - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            resp = self.session.get(API + endpoint, params=params, timeout=60)
        except requests.RequestException as exc:
            raise StopFetching(f"network error for GPU {endpoint}: {exc!r}") from exc
        finally:
            self._last = self._clock()
        self.requests_made += 1
        if resp.status_code == 429 or resp.status_code >= 500:
            raise StopFetching(f"{resp.status_code} from the GPU API (Retry-After: {resp.headers.get('Retry-After')})")
        entry = {"url": resp.url if hasattr(resp, "url") and isinstance(resp.url, str) else API + endpoint, "status": resp.status_code,
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "features": [{"properties": f.get("properties") or {}} for f in resp.json().get("features", [])]
                 if resp.status_code < 400 else []}
        self.cache[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        return entry


def _first(props, *names):
    for n in names:
        if props.get(n) not in (None, ""):
            return props[n]
    return None


def fetch_snapshot(client):
    """Ask the portal about the commune: its documents, zones and heritage-related prescriptions."""
    point = json.dumps({"type": "Point", "coordinates": [COMMUNE["lon"], COMMUNE["lat"]]})
    status, docs, zones, prescriptions = {}, [], {}, []
    muni = client.get("municipality", {"insee": COMMUNE["citycode"]})
    status["municipality"] = muni["status"]
    municipality = (muni["features"][0]["properties"] if muni["features"] else {})
    doc = client.get("document", {"geom": point})
    status["document"] = doc["status"]
    partitions = []
    for f in doc["features"]:
        p = f["properties"]
        docs.append({"type": _first(p, "typedoc", "type"), "name": _first(p, "name", "nom"), "status": _first(p, "status", "etat"),
                     "partition": p.get("partition"), "id": _first(p, "id", "gpu_doc_id"),
                     "approved": _first(p, "datappro", "date_approbation"), "updated": _first(p, "gpu_timestamp", "updated_at"),
                     "url": PORTAL + "document/" + str(_first(p, "gpu_doc_id", "id") or "")})
        if p.get("partition"):
            partitions.append(p["partition"])
    for partition in dict.fromkeys(partitions):
        z = client.get("zone-urba", {"partition": partition})
        status["zone-urba"] = z["status"]
        for f in z["features"]:
            p = f["properties"]
            label = _first(p, "libelle", "libelong") or ""
            kind = _first(p, "typezone") or ""
            row = zones.setdefault((kind, label), {"type": kind, "label": label, "name": _first(p, "libelong", "libelle"), "count": 0})
            row["count"] += 1
        for endpoint in ("prescription-surf", "prescription-lin", "prescription-pct", "info-surf"):
            r = client.get(endpoint, {"partition": partition})
            status[endpoint] = r["status"]
            for f in r["features"]:
                p = f["properties"]
                text = " ".join(str(v) for v in (_first(p, "libelle"), _first(p, "txt"), _first(p, "nomfic")) if v)
                if HERITAGE.search(text):
                    prescriptions.append({"kind": endpoint, "label": _first(p, "libelle"), "text": _first(p, "txt"),
                                          "code": _first(p, "typepsc", "typeinf"), "subcode": _first(p, "stypepsc", "stypeinf"),
                                          "file": _first(p, "nomfic"), "link": _first(p, "urlfic"), "partition": partition})
    return {"source": "Géoportail de l'urbanisme (IGN APICarto, module gpu)", "portal": PORTAL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commune": COMMUNE["name"],
            "insee": COMMUNE["citycode"], "municipality": {k: municipality.get(k) for k in municipality if k in (
                "name", "is_rnu", "is_rnu_and_pos", "insee", "code_insee", "status", "document")},
            "documents": docs, "zones": sorted(zones.values(), key=lambda z: (z["type"], z["label"])),
            "heritage_prescriptions": prescriptions, "endpoint_status": status,
            "requests_made": client.requests_made}


def render_md(s):
    lines = ["# Planning and heritage zoning", "", disclosure.markdown("rules"), "",
             f"> **Not legal advice.** Taken from the national planning portal ([{s['source']}]({s['portal']})) on "
             f"{s['retrieved_at'][:10]}. Planning documents change; the portal and the Mairie's planning service are authoritative. "
             "The commune's local urban plan (PLU) is under revision, so check what is in force before relying on anything here.", ""]
    muni = s.get("municipality") or {}
    if muni:
        lines += ["## Status of the commune on the portal", ""] + [f"- {k}: {v}" for k, v in muni.items() if v is not None] + [""]
    lines += ["## Planning documents", ""]
    lines += [f"- {d['type'] or 'document'} “{d['name'] or d['id']}”, status {d['status'] or 'unknown'}"
              f"{', approved ' + str(d['approved']) if d['approved'] else ''} ([portal]({d['url']}))" for d in s["documents"]] or [
        "The portal returned no planning document for the centre of the commune."]
    lines += ["", "## Zones", ""]
    lines += ["| Type | Label | Parts |", "|---|---|---|"] + [f"| {z['type']} | {z['label']} | {z['count']} |" for z in s["zones"]] \
        if s["zones"] else ["No zones were returned."]
    lines += ["", "## Heritage-related prescriptions", "",
              "Selected by words such as heritage, protected, historic, architect, landscape in the portal's own labels. "
              "The code is the portal's; it is not interpreted here.", ""]
    lines += [f"- {p['label'] or 'prescription'} (code {p['code']}/{p['subcode']}; {p['kind']})"
              f"{': ' + p['text'] if p['text'] else ''}{' ([file](' + p['link'] + '))' if p['link'] else ''}" for p in s["heritage_prescriptions"]] \
        or ["None were returned. That may mean there are none, or that the portal does not hold them for this commune."]
    bad = {k: v for k, v in s["endpoint_status"].items() if v >= 400}
    if bad:
        lines += ["", "## Gaps", "", "These questions to the portal were refused or unknown, so the page is incomplete: "
                  + ", ".join(f"{k} (HTTP {v})" for k, v in bad.items()) + "."]
    return "\n".join(lines) + "\n"


def write_zoning(public_dir, client):
    target = Path(public_dir) / "zoning"
    target.mkdir(parents=True, exist_ok=True)
    snapshot = fetch_snapshot(client)
    (target / "zoning.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    (target / "index.md").write_text(disclosure.with_front_matter(render_md(snapshot), "Planning and heritage zoning"), encoding="utf-8")
    return snapshot
