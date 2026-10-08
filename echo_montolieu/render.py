"""Markdown for readers: the cleaned minutes, a per-meeting summary and a to-do list.

minutes.md is the faithful text, tidied for reading (hard-wrapped lines joined,
page numbers moved into links, capitals headings in sentence case) and keeps every
name. summary.md and todo.md are derived by rules: they quote the sentence a
statement came from, link its page, and carry no personal names.
"""
import re

from .meeting import PLACEHOLDER, display_title
from .text import clean_page_lines, paragraphs, sentence_case

BANNER = ("> Machine-generated reading of the council minutes. It may contain errors; the "
          "original PDF is the authoritative document.")
VOTE_LABELS = {"unanimous": "unanimous", "majority": "majority (not unanimous)",
               "rejected": "rejected", None: "no vote found"}
TYPE_LABELS = {"authorisation": "Authorises someone to act",
               "deferred": "Postponed or to be revisited",
               "planned": "Planned or expected action"}


def _anchor(text):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"[àâä]", "a", re.sub(r"[éèêë]", "e", text.lower()))).strip("-")


def _esc(text):
    """Escape what would turn prose into Markdown formatting."""
    text = text.replace("\\", "\\\\")
    text = re.sub(r"([*_`<>|])", r"\\\1", text)
    return re.sub(r"^(\s*)([#+-]|\d+\.)\s", r"\1\\\2 ", text)


def page_link(source_url, page):
    return f"[p.{page}]({source_url}#page={page})"


def _front_matter(rec, kind):
    date = (rec.get("meeting_date") or {}).get("value") or "unknown"
    status = (rec.get("meeting_date") or {}).get("status")
    return "\n".join([
        "---",
        f'title: "{kind}: council meeting of {date}"',
        f"date: {date}",
        f"date_status: {status or 'unknown'}",
        f"document_id: {rec['document_id']}",
        f"version: {rec.get('version', 1)}",
        f"source: {rec['source_url']}",
        f"source_sha256: {rec['source_sha256']}",
        "language: fr",
        "machine_generated: true",
        "---", ""])


def _ocr_block(page, url):
    conf = (page.get("ocr") or {}).get("mean_conf")
    n = page["page"]
    out = [f"> **Page {n} is an image read by OCR** (confidence {conf}). "
           f"Treat it as unverified and check {page_link(url, n)}.", "",
           "```text", page["text"].strip(), "```", ""]
    if page.get("text_sparse"):
        out += ["<details><summary>Alternate OCR reading (finds more numbers, loses table layout)"
                "</summary>", "", "```text", page["text_sparse"].strip(), "```", "", "</details>", ""]
    return out


def render_minutes(rec):
    """Faithful, tidied Markdown of one record. Names are kept."""
    url = rec["source_url"]
    doc_date = (rec.get("meeting_date") or {}).get("value", "date not detected")

    # Text-layer pages become blocks; each OCR page stays a separate unit between them.
    units, run = [], []
    for p in rec["pages"]:
        if p["method"] == "tesseract":
            if run:
                units.append(("blocks", paragraphs(run)))
                run = []
            units.append(("ocr", p))
        else:
            run += [(l, p["page"]) for l in clean_page_lines(p.get("text"), p["page"])]
    if run:
        units.append(("blocks", paragraphs(run)))
    all_blocks = [b for kind, u in units if kind == "blocks" for b in u]
    headings = [i for i, b in enumerate(all_blocks) if b["kind"] == "heading"]
    agenda = [b["text"] for b in (all_blocks[headings[0] + 1: headings[1]] if len(headings) > 1 else [])
              if b["kind"] == "bullet"]
    doc_title = all_blocks[headings[0]] if headings else None
    heading = sentence_case(doc_title["text"]) if doc_title else f"Conseil municipal du {doc_date}"

    out = [_front_matter(rec, "Minutes"), f"# {heading}", "", BANNER, "",
           f"Original: [PDF]({url}) (SHA-256 `{rec['source_sha256'][:16]}…`, retrieved "
           f"{rec['retrieved_at'][:10]}). Version {rec.get('version', 1)} of "
           f"{len(rec.get('versions', [])) or 1}.", ""]
    review = [p["page"] for p in rec["pages"] if p.get("status") == "needs_review"]
    if review:
        out += [f"> **Check the original for page(s) {', '.join(map(str, review))}.** They were "
                "read by OCR with low confidence; figures and tables may be wrong.", ""]

    body, toc, seen_pages, previous_kind = [], [], set(), None
    for kind, unit in units:
        if kind == "ocr":
            seen_pages.add(unit["page"])
            body += _ocr_block(unit, url)
            previous_kind = "ocr"
            continue
        for b in unit:
            page_mark = ""
            if b["page"] not in seen_pages:
                seen_pages.add(b["page"])
                page_mark = f" {page_link(url, b['page'])}"
            if previous_kind == "bullet" and b["kind"] != "bullet":
                body.append("")
            previous_kind = b["kind"]
            if b["kind"] == "heading":
                if b is doc_title:
                    continue  # the document title is the page heading above
                title = display_title(b["text"], agenda)
                body += [f"## {title}{page_mark}", ""]
                toc.append((title, b["page"]))
            elif b["kind"] == "subheading":
                body += [f"### {_esc(b['text'])}{page_mark}", ""]
            elif b["kind"] == "bullet":
                body += [f"- {_esc(b['text'])}{page_mark}"]
            elif b["kind"] == "table":
                body += ["", "```text", b["text"], "```", ""]
            else:
                body += [f"{_esc(b['text'])}{page_mark}", ""]
    if toc:
        out += ["## Contents", ""] + [f"- [{t}](#{_anchor(t)}) ({page_link(url, p)})" for t, p in toc] + [""]
    out += body
    return "\n".join(out).rstrip() + "\n"


def _vote_text(item):
    label = VOTE_LABELS.get(item["vote_result"], item["vote_result"])
    extras = []
    for v in item["votes"]:
        bits = [f"{k.replace('_', ' ')}: {v[k]}" for k in ("for", "against", "abstentions", "did_not_vote") if v.get(k)]
        if bits:
            extras.append(", ".join(bits))
    return label + (f" ({'; '.join(extras)})" if extras else "")


def _money(a):
    value = a["value"]
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",") if value != int(value) else f"{int(value):,}".replace(",", " ")
    return f"{text} €" if a["kind"] == "eur" else f"{text} %"


def render_summary(meeting):
    """What was decided, item by item, with sources. Names withheld."""
    url, d = meeting["source_url"], meeting["date"] or "date not detected"
    out = [_front_matter({**meeting, "meeting_date": {"value": meeting["date"], "status": meeting["date_status"]},
                          "version": meeting["version"], "source_url": url,
                          "source_sha256": meeting["source_sha256"]}, "Summary"),
           f"# Summary of the council meeting of {d}", "", BANNER, "",
           "This summary is extracted by rules, not written by a person: each line quotes the "
           f"sentence it comes from and links the page. Personal names are replaced by "
           f"`{PLACEHOLDER}`. Read the [full minutes](minutes.md) or the [original PDF]({url}).", "",
           f"- Attendance: {meeting['attendance']['present']} present, {meeting['attendance']['absent']} absent or represented.",
           f"- Items: {len(meeting['items'])}. Pages: {meeting['page_count']}."]
    if meeting["pages_needing_review"]:
        out.append(f"- Pages read by low-confidence OCR: {', '.join(map(str, meeting['pages_needing_review']))}. Check the original.")
    out.append("")
    for it in meeting["items"]:
        first = it["pages"][0]
        out += [f"## {it['title']}", "",
                f"{page_link(url, first)}" + (f" to {page_link(url, it['pages'][1])}" if it['pages'][1] != first else "")
                + f" · Vote: {_vote_text(it)}"
                + (f" · Topics: {', '.join(it['topics'])}" if it["topics"] else ""), ""]
        if it["sensitive"]:
            out += [f"Decisions about sales of private property ({it.get('sale_notices', 0)} notice(s)). "
                    "Details are in the minutes; they are left out here on purpose.", ""]
            continue
        if it["snippet"]:
            out += [f"> {it['snippet']}", ""]
        eur, rates = [a for a in it["amounts"] if a["kind"] == "eur"], []
        rates = [a for a in it["amounts"] if a["kind"] == "pct" and re.search(r"taux|indice|taxe|%", a["sentence"], re.I)
                 and re.search(r"taux|indice|taxe", a["sentence"], re.I)]
        for title, rows in (("Amounts", eur), ("Rates", rates)):
            if rows:
                grouped = {}
                for a in rows:
                    grouped.setdefault(a["sentence"], []).append(_money(a))
                out += [f"**{title}**", ""] + [f"- {', '.join(vals)}: “{sent[:220]}”"
                                              for sent, vals in list(grouped.items())[:6]] + [""]
        if it["legal_refs"]:
            out += ["**Legal references**", ""] + [f"- {r['key']}" for r in it["legal_refs"][:8]] + [""]
        if it["exceptions"]:
            out += ["**Exceptions or derogations mentioned**", ""] + [f"- “{e['sentence'][:200]}”" for e in it["exceptions"][:4]] + [""]
        places = [p["label"] for p in it["places"]]
        if places:
            out += [f"**Places mentioned (unverified):** {', '.join(places)}", ""]
    return "\n".join(out).rstrip() + "\n"


def render_todo(meeting, status_by_item=None):
    """Follow-up candidates. status_by_item maps item id to a later-mention note."""
    status_by_item = status_by_item or {}
    url, d = meeting["source_url"], meeting["date"] or "date not detected"
    out = [_front_matter({**meeting, "meeting_date": {"value": meeting["date"], "status": meeting["date_status"]},
                          "version": meeting["version"], "source_url": url,
                          "source_sha256": meeting["source_sha256"]}, "To do"),
           f"# Follow-ups from the council meeting of {d}", "", BANNER, "",
           "These are sentences that *look like* a commitment, a postponement or a plan. They are "
           "candidates found by wording, not a checked action list. Verify each against the page.", ""]
    found = False
    for it in meeting["items"]:
        if not it["followups"]:
            continue
        found = True
        out += [f"## {it['title']} ({page_link(url, it['pages'][0])})", ""]
        for kind in ("deferred", "planned", "authorisation"):
            rows = [f for f in it["followups"] if f["type"] == kind]
            if rows:
                out += [f"**{TYPE_LABELS[kind]}**", ""] + [f"- [ ] “{f['sentence'][:260]}”" for f in rows] + [""]
        note = status_by_item.get(it["id"])
        if note:
            out += [f"_Later mentions: {note}_", ""]
    if not found:
        out += ["No follow-up wording was found in this meeting.", ""]
    return "\n".join(out).rstrip() + "\n"


def meeting_folder(rec, taken):
    """Folder name for a record: its date, plus the document id if two share a date."""
    date = (rec.get("meeting_date") or {}).get("value") or "undated"
    name = date if date not in taken else f"{date}-{rec['document_id']}"
    taken.add(name)
    return name


def render_index(rows):
    """Table of all meetings: what exists, and what to check."""
    out = ["# Council meetings", "", BANNER, "",
           "One folder per meeting. `minutes.md` is the full text tidied for reading (names kept, "
           "as published). `summary.md` and `todo.md` are extracted by rules and carry no personal "
           "names. Every line links back to the page of the original PDF.", "",
           "| Date | Items | Votes | Pages to check | Read | Original |", "|---|---|---|---|---|---|"]
    for r in rows:
        review = ", ".join(map(str, r["review"])) or "none"
        links = f"[minutes]({r['folder']}/minutes.md) · [summary]({r['folder']}/summary.md) · [follow-ups]({r['folder']}/todo.md)"
        out.append(f"| {r['date']}{' (draft?)' if r['draft'] else ''}{' v' + str(r['version']) if r['version'] > 1 else ''} "
                   f"| {r['items']} | {r['votes']} | {review} | {links} | [PDF]({r['url']}) |")
    return "\n".join(out) + "\n"


def render_all(public_dir, status_by_item=None):
    """Write meetings/<date>/{minutes,summary,todo}.md and meetings/index.md. Returns a report."""
    import json
    from pathlib import Path
    from .meeting import parse_meeting

    public = Path(public_dir)
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    out_dir = public / "meetings"
    out_dir.mkdir(parents=True, exist_ok=True)
    taken, rows, meetings = set(), [], []
    for entry in sorted(index["documents"], key=lambda d: ((d["meeting_date"] or {}).get("value") or "", d["filename"] or "")):
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        folder = meeting_folder(rec, taken)
        meeting = parse_meeting(rec)
        meeting["folder"] = folder
        target = out_dir / folder
        target.mkdir(exist_ok=True)
        (target / "minutes.md").write_text(render_minutes(rec), encoding="utf-8")
        (target / "summary.md").write_text(render_summary(meeting), encoding="utf-8")
        (target / "todo.md").write_text(render_todo(meeting, status_by_item), encoding="utf-8")
        meetings.append(meeting)
        counts = {}
        for it in meeting["items"]:
            counts[it["vote_result"]] = counts.get(it["vote_result"], 0) + 1
        rows.append({"date": meeting["date"] or "undated", "folder": folder, "items": len(meeting["items"]),
                     "votes": ", ".join(f"{n} {VOTE_LABELS[k].split(' ')[0]}" for k, n in counts.items() if k) or "none found",
                     "review": meeting["pages_needing_review"], "draft": bool(rec.get("draft_suspected")),
                     "version": meeting["version"], "url": rec["source_url"]})
    rows.sort(key=lambda r: r["date"], reverse=True)
    (out_dir / "index.md").write_text(render_index(rows), encoding="utf-8")
    return {"meetings": len(meetings), "folders": sorted(taken)}, meetings
