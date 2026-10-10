"""Recorded property sales (DVF) for Montolieu, read from files you download yourself. Private: output goes to the terminal only.

DVF, "Demandes de valeurs foncières", is the state's open record of every property sale: date, price, address, parcel,
surface. It lags the sale by several months. The geolocated yearly file for one commune is a CSV; the host's robots.txt
asks automated clients to stay out, so a person downloads it in a browser (see `HOW_TO`) and this module only reads it.

Nothing here is published. The sale notices in the council minutes (`private/echo-private.db`) can be matched to the recorded
sales by parcel, to compare what the council was told with what was registered.
"""
import csv
import re
import sqlite3
import unicodedata
from datetime import date, timedelta
from pathlib import Path

COMMUNE = "11253"
HOW_TO = ("Download the yearly file for Montolieu in a browser, for example "
          "https://files.data.gouv.fr/geo-dvf/latest/csv/2025/communes/11/11253.csv (change the year), and save each as "
          "private/dvf/dvf-YYYY.csv. The dataset page is https://www.data.gouv.fr/ (search 'Demandes de valeurs foncières géolocalisées').")


def _plain(text):
    return re.sub(r"[^a-z0-9 ]+", " ", unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()).strip()


def parcel_key(parcel_id):
    """('AB', '0099') from '11253000AB0099'; a one-letter section is padded with 0 in the cadastre ('0B') and returned as 'B'."""
    m = re.fullmatch(r"\d{5}(\d{3})([0-9A-Z]{2})(\d{4})", parcel_id or "")
    return (m.group(2).lstrip("0"), m.group(3)) if m else None


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load(folder):
    """Sales as dicts, newest first: one per mutation (one registered sale), with its addresses, parcels, price and surfaces."""
    sales = {}
    for path in sorted(Path(folder).glob("*.csv")):
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("code_commune") not in (None, "", COMMUNE) and not (row.get("code_commune") or "").startswith("11253"):
                    continue
                s = sales.setdefault(row["id_mutation"], {"id": row["id_mutation"], "date": row.get("date_mutation"), "nature": row.get("nature_mutation"),
                                                         "price": _num(row.get("valeur_fonciere")), "addresses": set(), "parcels": set(),
                                                         "types": set(), "built": 0.0, "land": 0.0, "rooms": 0})
                address = " ".join(x for x in (row.get("adresse_numero"), row.get("adresse_suffixe"), row.get("adresse_nom_voie")) if x)
                if address:
                    s["addresses"].add(address)
                key = parcel_key(row.get("id_parcelle"))
                if key:
                    s["parcels"].add(key)
                if row.get("type_local"):
                    s["types"].add(row["type_local"])
                    s["built"] += _num(row.get("surface_reelle_bati"))
                    s["rooms"] += int(_num(row.get("nombre_pieces_principales")))
                if row.get("type_local") == "" or not row.get("type_local"):
                    s["land"] += _num(row.get("surface_terrain"))
    return sorted(sales.values(), key=lambda s: s["date"] or "", reverse=True)


def search(sales, street=None, section=None, nature="Vente"):
    """Sales whose address contains `street` (accents and case ignored) and/or that touch cadastre `section`."""
    want = _plain(street) if street else None
    out = []
    for s in sales:
        if nature and s["nature"] != nature:
            continue
        if want and not any(want in _plain(a) for a in s["addresses"]):
            continue
        if section and not any(k[0] == section.upper() for k in s["parcels"]):
            continue
        out.append(s)
    return out


def match_notices(sales, db_path, slack_days=60):
    """Council sale notices (parcels named in the minutes) paired with the recorded sale of the same parcel on or after the notice date."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    notices = db.execute("SELECT m.date, p.section, p.number, p.page FROM parcels p JOIN meetings m ON m.id = p.meeting_id").fetchall()
    out = []
    for notice_date, section, number, page in notices:
        for s in sales:
            if (section, number) in s["parcels"] and s["date"] and s["date"] >= (date.fromisoformat(notice_date) - timedelta(days=slack_days)).isoformat():
                out.append({"notice": notice_date, "page": page, "parcel": f"{section} {number}", "sale": s})
    seen, unique = set(), []
    for m in sorted(out, key=lambda m: (m["notice"], m["parcel"], m["sale"]["date"])):
        key = (m["notice"], m["parcel"], m["sale"]["id"])
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def describe(s):
    kind = "/".join(sorted(s["types"])) or "land"
    size = f"{s['built']:.0f} m2 built" if s["built"] else ""
    land = f"{s['land']:.0f} m2 land" if s["land"] else ""
    where = "; ".join(sorted(s["addresses"])) or "no address"
    return f"{s['date']}  {s['price']:>10,.0f} EUR  {kind}  {', '.join(x for x in (size, land) if x)}  {where}  parcels {', '.join(a + b for a, b in sorted(s['parcels']))}"
