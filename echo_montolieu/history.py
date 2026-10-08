"""A machine-readable history of the council across every minutes document we hold.

This is a map of what the record contains, built by programmed rules (no AI model writes any of
it): who chaired, how often the council met, what it talked about, the money it mentioned, and
where the record has gaps. It is written to the private folder by default so the maintainer can
decide what to publish. Only the chair's name (an elected official) is extracted; no other person
is named.

Method limits: topics are keyword counts over the whole text, amounts are euro figures found in
sentences (some are unit prices, rates or totals, so they are evidence, not budgets), and the
2003-2008 documents have a different layout from today's, so item-level parsing is not attempted.
"""
import json
import re
from datetime import date
from pathlib import Path

from . import disclosure
from .signals import find_amounts, find_legal_refs, find_topics

_CHAIR = re.compile(
    r"[Pp]r[ée]sidence\s+(?:de\s+(?:Monsieur|Madame|M\.|Mme)\s+|du\s+Maire,?\s+(?:M\.|Monsieur|Madame|Mme)\s+)"
    r"([^,.]{3,60}?)\s*(?:,|\.|\s+Maire)", re.S)
_UNANIMOUS = re.compile(r"à l[’']unanimité", re.I)
_MAJORITY = re.compile(r"à la majorité|voix contre|abstention", re.I)


def surname(name):
    """The family name of "Max DELPERIER" / "RICARD Edouard" / "Jacques SAFONT": the capitalised word."""
    words = re.findall(r"[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’-]{2,}", name)
    return (words[0] if words else name.split()[-1]).title()


def _fold(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def canonical_names(names):
    """Map spelling variants (Delperier / Delpérier / Demperier) to the most frequent spelling."""
    from collections import Counter
    from difflib import SequenceMatcher
    counts = Counter(n for n in names if n)
    canon = {}
    for name, _ in counts.most_common():
        for known in set(canon.values()):
            if SequenceMatcher(None, _fold(name), _fold(known)).ratio() >= 0.85:
                canon[name] = known
                break
        else:
            canon[name] = name
    return canon


def chair_of(text):
    m = _CHAIR.search(" ".join(text.split()))
    return surname(m.group(1)) if m else None


def analyse(rec):
    text = "\n".join(p.get("text") or "" for p in rec["pages"])
    when = (rec.get("meeting_date") or {}).get("value")
    amounts = [a for a in find_amounts(text) if a["kind"] == "eur" and a["value"]]
    top = sorted(amounts, key=lambda a: -a["value"])[:3]
    origin = rec.get("origin") or {}
    return {
        "date": when, "date_status": (rec.get("meeting_date") or {}).get("status"),
        "document_id": rec["document_id"], "source_url": rec["source_url"], "source_sha256": rec["source_sha256"],
        "recovered_from_internet_archive": bool(origin), "mirror_path": origin.get("mirror_path"),
        "chair": chair_of(text), "pages": rec["page_count"], "characters": len(text),
        "ocr_pages": sum(p.get("method") == "tesseract" for p in rec["pages"]),
        "needs_review_pages": sum(p.get("status") == "needs_review" for p in rec["pages"]),
        "topics": [{"topic": t, "hits": n} for t, n in find_topics("", text)],
        "amounts": {"count": len(amounts), "largest": [
            {"eur": a["value"], "page_hint": None, "sentence": " ".join(a["sentence"].split())[:200]} for a in top]},
        "legal_references": len(find_legal_refs(text)),
        "votes": {"unanimous_mentions": len(_UNANIMOUS.findall(text)), "split_or_abstention_mentions": len(_MAJORITY.findall(text))},
    }


def build(public_dir):
    public = Path(public_dir)
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    rows = []
    for entry in index["documents"]:
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        rows.append(analyse(rec))
    rows = [r for r in rows if r["date"]]
    rows.sort(key=lambda r: r["date"])
    canon = canonical_names([r["chair"] for r in rows])
    variants = {}
    for r in rows:
        if r["chair"]:
            if canon[r["chair"]] != r["chair"]:
                variants.setdefault(canon[r["chair"]], set()).add(r["chair"])
            r["chair"] = canon[r["chair"]]
    years = {}
    for r in rows:
        y = years.setdefault(r["date"][:4], {"meetings": 0, "pages": 0, "chairs": set(), "topics": {}, "amount_mentions": 0})
        y["meetings"] += 1
        y["pages"] += r["pages"]
        y["amount_mentions"] += r["amounts"]["count"]
        if r["chair"]:
            y["chairs"].add(r["chair"])
        for t in r["topics"]:
            y["topics"][t["topic"]] = y["topics"].get(t["topic"], 0) + t["hits"]
    by_year = {y: {"meetings": v["meetings"], "pages": v["pages"], "chairs": sorted(v["chairs"]), "amount_mentions": v["amount_mentions"],
                   "top_topics": [t for t, _ in sorted(v["topics"].items(), key=lambda kv: -kv[1])[:4]]} for y, v in sorted(years.items())}
    first, last = int(rows[0]["date"][:4]), int(rows[-1]["date"][:4])
    missing = [y for y in range(first, last + 1) if str(y) not in by_year]
    eras, cur = [], None
    for r in rows:
        if r["chair"] and (cur is None or cur["chair"] != r["chair"]):
            cur = {"chair": r["chair"], "first_meeting": r["date"], "last_meeting": r["date"], "meetings": 0}
            eras.append(cur)
        if cur and r["chair"] == cur["chair"]:
            cur["last_meeting"], cur["meetings"] = r["date"], cur["meetings"] + 1
    gaps = []
    for a, b in zip(rows, rows[1:]):
        days = (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days
        if days > 180:
            gaps.append({"after": a["date"], "before": b["date"], "days": days})
    return {"generated_by": disclosure.produced_by("rules"), "human_reviewed": False, "ai_disclosure": disclosure.AI_PAGE_URL,
            "disclaimer": disclosure.text("rules", "en"),
            "coverage": {"first": rows[0]["date"], "last": rows[-1]["date"], "meetings": len(rows),
                         "years_with_no_minutes": missing, "gaps_over_180_days": gaps},
            "chairs": eras, "chair_spelling_variants_merged": {k: sorted(v) for k, v in variants.items()}, "by_year": by_year, "meetings": rows}


def render_md(h):
    cov = h["coverage"]
    out = ["---", 'title: "History of the council, from the minutes we hold"', "machine_generated: true",
           *[f"{k}: {v}" for k, v in disclosure.front_matter("rules").items()], "---", "",
           "# History of the council, from the minutes we hold", "", disclosure.markdown("rules"), "",
           "> A map of what the record contains, not a history of the village. Topics are keyword counts, amounts are euro "
           "figures found in sentences (some are rates or unit prices), and nothing here was checked by a person.", "",
           "## Coverage", "",
           f"- {cov['meetings']} meetings, from {cov['first']} to {cov['last']}.",
           f"- Years with no minutes at all: {', '.join(map(str, cov['years_with_no_minutes'])) if cov['years_with_no_minutes'] else 'none'}.",
           f"- Gaps of more than six months: " + ("; ".join(f"{g['after']} to {g['before']} ({g['days']} days)" for g in cov["gaps_over_180_days"]) or "none") + ".", "",
           "## Who chaired", "", "| Chair | First meeting | Last meeting | Meetings |", "|---|---|---|---|"]
    out += [f"| {e['chair']} | {e['first_meeting']} | {e['last_meeting']} | {e['meetings']} |" for e in h["chairs"]]
    out += ["", "Read from the opening sentence of each document; meetings where it was not found are not counted.", "",
            "## Year by year", "", "| Year | Meetings | Pages | Chair(s) | Most discussed | Euro figures mentioned |", "|---|---|---|---|---|---|"]
    out += [f"| {y} | {v['meetings']} | {v['pages']} | {', '.join(v['chairs']) or '?'} | {', '.join(v['top_topics']) or '-'} | {v['amount_mentions']} |"
            for y, v in h["by_year"].items()]
    out += ["", "## Meetings", "", "| Date | Chair | Pages | Topics | Largest euro figure | Source |", "|---|---|---|---|---|---|"]
    for m in h["meetings"]:
        big = m["amounts"]["largest"][0]["eur"] if m["amounts"]["largest"] else None
        src = f"[Internet Archive]({m['source_url']})" if m["recovered_from_internet_archive"] else f"[PDF]({m['source_url']})"
        out.append(f"| {m['date']} | {m['chair'] or '?'} | {m['pages']} | {', '.join(t['topic'] for t in m['topics'][:3]) or '-'} | "
                   f"{f'{big:,.0f} €'.replace(',', ' ') if big else '-'} | {src} |")
    return "\n".join(out) + "\n"


def write(public_dir, out_dir):
    h = build(public_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "timeline.json").write_text(json.dumps(h, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "HISTORY.md").write_text(render_md(h), encoding="utf-8")
    return h
