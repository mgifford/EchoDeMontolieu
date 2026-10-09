"""Open data: the derived layer as downloadable files.

`public/data/council.json` and three CSV files (meetings, decisions, places) built from the same scrubbed items as
the facts pages, the summaries and the confirmed places. Nothing here comes from the faithful text: names are
already replaced, private property sales are counted and never listed, and every row links to the page of the
original. The files are static and are rebuilt by `render`; the website publishes them under /data/.

No licence has been chosen for this derived data yet. Each file says so, and says that machine-written text is
unreviewed and the original documents are authoritative.
"""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from . import disclosure
from .db import _front, _summary_body

NOTICE = ("Derived, machine-generated data about the council minutes of Montolieu (Aude, France). Names are replaced, private "
          "property sales are counted and not listed, and summaries are written by AI models and not reviewed by a person. "
          "The original documents are authoritative; every row links to the page of the original. No reuse licence has been "
          "chosen for this derived data yet.")
MEETING_COLUMNS = ["date", "source", "folder", "document_id", "version", "page_count", "pages_to_check", "decisions",
                   "private_sale_notices", "summary_languages", "original_url", "site_page_en"]
DECISION_COLUMNS = ["date", "source", "n", "title", "text_fr", "vote", "votes_for", "votes_against", "abstentions",
                    "first_page", "last_page", "original_page_url", "topics", "euro_amounts"]
PLACE_COLUMNS = ["label", "kind", "latitude", "longitude", "openstreetmap_url", "meetings", "first_meeting", "last_meeting"]
SITE = "https://mgifford.github.io/EchoDeMontolieu/"


def _cell(value):
    """A CSV cell. Text that a spreadsheet would read as a formula gets a leading apostrophe."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(columns, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return out.getvalue()


def _summaries(public, folder):
    found = {}
    for lang, name in (("fr", "summary.md"), ("en", "summary.en.md"), ("nl", "summary.nl.md")):
        path = Path(public) / "meetings" / folder / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        meta, _ = _front(text)
        body = _summary_body(text)
        if body and meta.get("produced_by", "").startswith("AI model"):
            found[lang] = {"text": body, "written_by": meta["produced_by"], "human_reviewed": False}
    return found


def _places(public):
    from .places import _osm            # standard library only above; places.py needs requests, so import it here, lazily
    path = Path(public) / "places" / "places.json"
    if not path.exists():
        return []
    out = []
    for p in json.loads(path.read_text(encoding="utf-8")).get("places", []):
        dates = sorted({o["date"] for o in p["items"]})
        out.append({"label": p["label"], "kind": p["kind"], "latitude": p["lat"], "longitude": p["lon"], "openstreetmap_url": _osm(p),
                    "meetings": dates, "first_meeting": dates[0], "last_meeting": dates[-1]})
    return out


def build(public_dir, meetings, archived=()):
    """({file name: text}, summary counts). `meetings` come from threads.load_meetings, `archived` from archive_translate.archived_digests."""
    public = Path(public_dir)
    json_meetings, meeting_rows, decision_rows = [], [], []
    for m in sorted(meetings, key=lambda m: m["meeting"]["date"] or ""):
        mt, folder = m["meeting"], m["folder"]
        if not mt["date"]:
            continue
        items = [it for it in mt["items"] if not it["sensitive"]]
        sales = sum(1 for it in mt["items"] if it["sensitive"])
        summaries = _summaries(public, folder)
        decisions = []
        for n, it in enumerate(items, 1):
            eur = [a["value"] for a in it["amounts"] if a["kind"] == "eur"]
            d = {"n": n, "title": it["title"], "vote": it["vote_result"], "first_page": it["pages"][0], "last_page": it["pages"][1],
                 "original_page_url": f"{mt['source_url']}#page={it['pages'][0]}", "topics": it["topics"], "euro_amounts": eur}
            decisions.append(d)
            decision_rows.append({"date": mt["date"], "source": "current", **d, "topics": "; ".join(it["topics"]),
                                  "euro_amounts": "; ".join(f"{v:.2f}" for v in eur)})
        site_page = f"{SITE}en/meetings/{folder}/{'summary' if 'en' in summaries or 'fr' in summaries else 'minutes'}.html"
        json_meetings.append({"date": mt["date"], "source": "current", "folder": folder, "document_id": mt["document_id"], "version": mt["version"],
                              "page_count": mt["page_count"], "pages_to_check": mt["pages_needing_review"], "original_url": mt["source_url"],
                              "original_sha256": mt["source_sha256"], "site_page_en": site_page, "private_sale_notices": sales,
                              "summaries": summaries, "decisions": decisions})
        meeting_rows.append({"date": mt["date"], "source": "current", "folder": folder, "document_id": mt["document_id"], "version": mt["version"],
                             "page_count": mt["page_count"], "pages_to_check": "; ".join(map(str, mt["pages_needing_review"])),
                             "decisions": len(decisions), "private_sale_notices": sales, "summary_languages": "; ".join(sorted(summaries)),
                             "original_url": mt["source_url"], "site_page_en": site_page})
    for folder, date, rec, d in archived:
        decisions = []
        for n, x in enumerate(d["decisions"], 1):
            row = {"n": n, "text_fr": x["text"], "vote": x["kind"], "votes_for": x["for"], "votes_against": x["against"],
                   "abstentions": x["abstentions"], "first_page": x["page"], "last_page": x["page"], "original_page_url": x.get("page_url")}
            decisions.append(row)
            decision_rows.append({"date": date, "source": "archive", **row})
        json_meetings.append({"date": date, "source": "archive", "folder": folder, "document_id": rec["document_id"], "original_url": rec["source_url"],
                              "private_sale_notices": d["sale_notices"], "summaries": {}, "decisions": decisions,
                              "note": "Recovered from the Internet Archive; only vote sentences are kept, with every name replaced."})
        meeting_rows.append({"date": date, "source": "archive", "folder": folder, "document_id": rec["document_id"], "decisions": len(decisions),
                             "private_sale_notices": d["sale_notices"], "original_url": rec["source_url"],
                             "site_page_en": f"{SITE}en/meetings/{folder}/facts.html"})
    json_meetings.sort(key=lambda m: m["date"], reverse=True)
    meeting_rows.sort(key=lambda r: r["date"], reverse=True)
    decision_rows.sort(key=lambda r: (r["date"], r["n"]), reverse=True)
    places = _places(public)
    generated = {"meetings": len(json_meetings), "decisions": len(decision_rows), "places": len(places),
                 "newest_meeting": json_meetings[0]["date"] if json_meetings else None}
    document = {"labels": disclosure.labels("rules"), "source": "https://github.com/mgifford/EchoDeMontolieu", "notice": NOTICE,
                "counts": {k: generated[k] for k in ("meetings", "decisions", "places")}, "newest_meeting": generated["newest_meeting"],
                "columns": {"meetings.csv": MEETING_COLUMNS, "decisions.csv": DECISION_COLUMNS, "places.csv": PLACE_COLUMNS},
                "meetings": json_meetings, "places": places}
    files = {"council.json": json.dumps(document, ensure_ascii=False, indent=1) + "\n",
             "meetings.csv": to_csv(MEETING_COLUMNS, meeting_rows), "decisions.csv": to_csv(DECISION_COLUMNS, decision_rows),
             "places.csv": to_csv(PLACE_COLUMNS, [{**p, "meetings": len(p["meetings"])} for p in places])}
    return files, generated


def write(public_dir, meetings, archived=()):
    files, info = build(public_dir, meetings, archived)
    target = Path(public_dir) / "data"
    target.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (target / name).write_text(text, encoding="utf-8")
    return info
