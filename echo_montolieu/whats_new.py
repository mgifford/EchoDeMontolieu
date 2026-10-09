"""What is new and what to watch: a dated digest of the latest meetings, built from the derived layer only.

Everything here comes from the same scrubbed items as the facts and topics pages: no faithful text, no names,
no private sales (counted elsewhere, never listed). The output is a data file, `public/whats-new/whats-new.json`;
the website turns it into pages and an Atom feed in each language. Nothing is predicted: "upcoming" means a
date, a plan or a postponement that the latest minutes themselves mention, with the sentence and the page.
"""
import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import disclosure
from .signals import TOPICS, sentences

RECENT = 3                # meetings shown in full
SCAN = 5                  # meetings searched for postponements and dates
FEED_ENTRIES = 10
WATCH_MONTHS = 12
WATCH_TOPICS = [t for t in TOPICS if t not in ("droit de préemption", "vie institutionnelle")]
_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
           "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}
_DATE = re.compile(r"\b(\d{1,2}|1er)\s+(" + "|".join(_MONTHS) + r")(?:\s+(20\d{2}))?\b", re.I)


def mentioned_dates(sentence, meeting_date):
    """ISO dates written as '30 septembre' or '1er juillet 2026' in `sentence`, from the meeting date to a year later."""
    start = date.fromisoformat(meeting_date)
    out = []
    for m in _DATE.finditer(sentence):
        day = 1 if m.group(1).lower() == "1er" else int(m.group(1))
        month = _MONTHS[m.group(2).lower()]
        year = int(m.group(3)) if m.group(3) else start.year
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if not m.group(3) and d < start:        # "le 9 avril" in an April meeting is the past, not next year
            continue
        if start <= d <= start + timedelta(days=400):
            out.append(d.isoformat())
    return out


def _item_row(item, meeting):
    return {"title": item["title"], "vote": item["vote_result"], "page": item["pages"][0],
            "page_url": f"{meeting['source_url']}#page={item['pages'][0]}", "topics": item["topics"]}


def build(meetings, result):
    """The digest as plain data. `meetings` are the parsed current meetings (oldest first), `result` the thread analysis."""
    dated = [m for m in meetings if m["meeting"]["date"]]
    if not dated:
        return {"latest": None, "recent_meetings": [], "coming_back": [], "pending": [], "possibly_dropped": [], "dates_mentioned": [], "watch": []}
    recent = sorted(dated, key=lambda m: m["meeting"]["date"], reverse=True)[:RECENT]
    recent_dates = {m["meeting"]["date"] for m in recent}
    latest = recent[0]["meeting"]["date"]

    def meeting_row(m):
        mt = m["meeting"]
        items = [it for it in mt["items"] if not it["sensitive"]]
        return {"date": mt["date"], "folder": m["folder"], "source_url": mt["source_url"],
                "decisions": [_item_row(it, mt) for it in items],
                "sale_notices": sum(1 for it in mt["items"] if it["sensitive"])}

    coming_back = [{"title": t["title"], "meetings": t["meetings"], "n_meetings": t["n_meetings"], "last": t["meetings"][-1]}
                   for t in result["threads"] if t["status"] != "one-off" and t["meetings"][-1] in recent_dates][:12]
    pending, dates = [], []
    for m in sorted(dated, key=lambda m: m["meeting"]["date"], reverse=True)[:SCAN]:
        mt = m["meeting"]
        for it in mt["items"]:
            if it["sensitive"]:
                continue
            for f in it["followups"]:
                if f["type"] in ("deferred", "planned"):
                    pending.append({"date": mt["date"], "title": it["title"], "type": f["type"], "sentence": f["sentence"][:260],
                                    "page": it["pages"][0], "page_url": f"{mt['source_url']}#page={it['pages'][0]}"})
            for s in sentences(it["text"]):
                if sum(c.isdigit() for c in s) > 0.15 * len(s):       # table rows, not prose
                    continue
                for d in mentioned_dates(s, mt["date"]):
                    dates.append({"meeting": mt["date"], "mentioned": d, "sentence": s[:260], "title": it["title"],
                                  "page": it["pages"][0], "page_url": f"{mt['source_url']}#page={it['pages'][0]}"})
    seen, unique = set(), []
    for d in sorted(dates, key=lambda d: (d["mentioned"], d["meeting"])):
        key = (d["mentioned"], d["sentence"][:80])
        if key not in seen:
            seen.add(key)
            unique.append(d)
    dropped = [{"title": t["title"], "last": t["meetings"][-1], "later_meetings": t["later_meetings"],
                "sentence": t["pending"][0]["sentence"][:200]} for t in result["threads"] if t["possibly_dropped"]]
    cutoff = (date.fromisoformat(latest) - timedelta(days=30 * WATCH_MONTHS)).isoformat()
    watch = []
    for topic in WATCH_TOPICS:
        rows = [(m["meeting"]["date"], it) for m in dated for it in m["meeting"]["items"] if topic in it["topics"] and not it["sensitive"]]
        recent_rows = [(d, it) for d, it in rows if d >= cutoff]
        if rows:
            watch.append({"topic": topic, "items_last_year": len(recent_rows),
                          "meetings_last_year": len({d for d, _ in recent_rows}), "last": max(d for d, _ in rows)})
    watch.sort(key=lambda w: (-w["items_last_year"], w["topic"]))
    return {"latest": latest, "recent_meetings": [meeting_row(m) for m in recent],
            "feed_meetings": [{"date": m["meeting"]["date"], "folder": m["folder"], "decisions": len([i for i in m["meeting"]["items"] if not i["sensitive"]])}
                              for m in sorted(dated, key=lambda m: m["meeting"]["date"], reverse=True)[:FEED_ENTRIES]],
            "coming_back": coming_back, "pending": pending[:15], "possibly_dropped": dropped, "dates_mentioned": unique[:15], "watch": watch}


def write(public_dir, meetings, result):
    target = Path(public_dir) / "whats-new"
    target.mkdir(parents=True, exist_ok=True)
    data = {**disclosure.labels("rules"), **build(meetings, result)}
    (target / "whats-new.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"latest": data["latest"], "recent": len(data["recent_meetings"]), "pending": len(data["pending"]),
            "dates": len(data["dates_mentioned"]), "dropped": len(data["possibly_dropped"])}
