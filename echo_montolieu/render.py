"""Markdown for readers: the cleaned minutes, a facts digest and a to-do list.

minutes.md is the faithful text, tidied for reading (hard-wrapped lines joined,
page numbers moved into links, capitals headings in sentence case) and keeps every
name. facts.md and todo.md are derived by rules: they quote the sentence a
statement came from, link its page, and carry no personal names. The narrative
summary (summary.md) and the translations (*.en.md, *.nl.md) come from a model and
are produced by generate.py.

The minutes can be rendered in French (the original) or in English or Dutch, by
passing a `tr` function that translates prose, headings and bullets. Tables and
OCR pages are never translated. Labels written by the project (not translated by a
model) exist in all three languages; the Dutch and English ones are unreviewed by a
native speaker.
"""
import re

from .meeting import PLACEHOLDER, display_title
from .text import clean_page_lines, paragraphs, sentence_case

LABELS = {
    "fr": {
        "banner": "> Lecture automatique du procès-verbal. Elle peut contenir des erreurs ; le PDF original fait foi.",
        "translation_notice": "",
        "original": "Original : [PDF]({url}) (SHA-256 `{sha}…`, récupéré le {date}). Version {v} sur {n}.",
        "check_pages": "> **Vérifiez l’original pour la ou les pages {pages}.** Elles ont été lues par OCR avec une faible confiance ; chiffres et tableaux peuvent être faux.",
        "ocr_page": "> **La page {n} est une image lue par OCR** (confiance {conf}). Considérez-la comme non vérifiée et consultez {link}.",
        "alt_ocr": "Lecture OCR alternative (trouve plus de nombres, perd la mise en page)",
        "contents": "Sommaire",
        "untranslated": "non traduit : une vérification automatique a échoué",
        "kind_minutes": "Procès-verbal", "meeting_of": "Conseil municipal du {date}",
    },
    "en": {
        "banner": "> Machine-generated reading of the council minutes. It may contain errors; the original PDF is the authoritative document.",
        "translation_notice": "> **Machine translation** of the French original. The French text is authoritative. Tables, image pages read by OCR and notices about private property sales are kept in French.",
        "original": "Original: [PDF]({url}) (SHA-256 `{sha}…`, retrieved {date}). Version {v} of {n}.",
        "check_pages": "> **Check the original for page(s) {pages}.** They were read by OCR with low confidence; figures and tables may be wrong.",
        "ocr_page": "> **Page {n} is an image read by OCR** (confidence {conf}). Treat it as unverified and check {link}.",
        "alt_ocr": "Alternate OCR reading (finds more numbers, loses the layout)",
        "contents": "Contents",
        "untranslated": "not translated: an automatic check failed",
        "kind_minutes": "Minutes", "meeting_of": "Municipal council of {date}",
    },
    "nl": {
        "banner": "> Automatisch gegenereerde weergave van de notulen. Ze kan fouten bevatten; de originele pdf is leidend.",
        "translation_notice": "> **Automatische vertaling** van de Franse originele tekst. De Franse tekst is leidend. Tabellen, door OCR gelezen beeldpagina’s en bekendmakingen over de verkoop van privébezit blijven in het Frans.",
        "original": "Origineel: [pdf]({url}) (SHA-256 `{sha}…`, opgehaald op {date}). Versie {v} van {n}.",
        "check_pages": "> **Controleer het origineel voor pagina {pages}.** Ze zijn met OCR gelezen met lage betrouwbaarheid; cijfers en tabellen kunnen onjuist zijn.",
        "ocr_page": "> **Pagina {n} is een afbeelding gelezen met OCR** (betrouwbaarheid {conf}). Beschouw ze als niet gecontroleerd en raadpleeg {link}.",
        "alt_ocr": "Alternatieve OCR-lezing (vindt meer getallen, verliest de opmaak)",
        "contents": "Inhoud",
        "untranslated": "niet vertaald: een automatische controle is mislukt",
        "kind_minutes": "Notulen", "meeting_of": "Gemeenteraad van {date}",
    },
}
BANNER = LABELS["en"]["banner"]
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


def _front_matter(rec, kind, lang="fr", extra=None):
    date = (rec.get("meeting_date") or {}).get("value") or "unknown"
    status = (rec.get("meeting_date") or {}).get("status")
    lines = ["---",
             f'title: "{kind}: {date}"',
             f"date: {date}",
             f"date_status: {status or 'unknown'}",
             f"document_id: {rec['document_id']}",
             f"version: {rec.get('version', 1)}",
             f"source: {rec['source_url']}",
             f"source_sha256: {rec['source_sha256']}",
             f"language: {lang}",
             "machine_generated: true"]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines + ["---", ""])


def _ocr_block(page, url, labels):
    conf = (page.get("ocr") or {}).get("mean_conf")
    n = page["page"]
    out = [labels["ocr_page"].format(n=n, conf=conf, link=page_link(url, n)), "",
           "```text", page["text"].strip(), "```", ""]
    if page.get("text_sparse"):
        out += [f"<details><summary>{labels['alt_ocr']}</summary>", "", "```text",
                page["text_sparse"].strip(), "```", "", "</details>", ""]
    return out


def render_minutes(rec, lang="fr", tr=None, extra=None):
    """Tidied Markdown of one record. French keeps every name; `tr` translates the prose."""
    tr = tr or (lambda text, page=None: text)
    labels = LABELS[lang]
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
    heading = tr(sentence_case(doc_title["text"]) if doc_title else f"Conseil municipal du {doc_date}",
                 doc_title["page"] if doc_title else 1)

    out = [_front_matter(rec, labels["kind_minutes"], lang, extra), f"# {heading}", "", labels["banner"], ""]
    if labels["translation_notice"]:
        out += [labels["translation_notice"], ""]
    out += [labels["original"].format(url=url, sha=rec["source_sha256"][:16], date=rec["retrieved_at"][:10],
                                      v=rec.get("version", 1), n=len(rec.get("versions", [])) or 1), ""]
    review = [p["page"] for p in rec["pages"] if p.get("status") == "needs_review"]
    if review:
        out += [labels["check_pages"].format(pages=", ".join(map(str, review))), ""]

    body, toc, seen_pages, previous_kind = [], [], set(), None
    for kind, unit in units:
        if kind == "ocr":
            seen_pages.add(unit["page"])
            body += _ocr_block(unit, url, labels)
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
                title = tr(display_title(b["text"], agenda), b["page"])
                body += [f"## {title}{page_mark}", ""]
                toc.append((title, b["page"]))
            elif b["kind"] == "subheading":
                body += [f"### {_esc(tr(b['text'], b['page']))}{page_mark}", ""]
            elif b["kind"] == "bullet":
                body += [f"- {_esc(tr(b['text'], b['page']))}{page_mark}"]
            elif b["kind"] == "table":
                body += ["", "```text", b["text"], "```", ""]
            else:
                body += [f"{_esc(tr(b['text'], b['page']))}{page_mark}", ""]
    if toc:
        out += [f"## {labels['contents']}", ""] + [f"- [{t}](#{_anchor(t)}) ({page_link(url, p)})" for t, p in toc] + [""]
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


def render_facts(meeting):
    """What the text says, item by item, with sources: votes, amounts, references. Rules, not a model."""
    url, d = meeting["source_url"], meeting["date"] or "date not detected"
    out = [_front_matter({**meeting, "meeting_date": {"value": meeting["date"], "status": meeting["date_status"]},
                          "version": meeting["version"], "source_url": url,
                          "source_sha256": meeting["source_sha256"]}, "Facts"),
           f"# Facts found in the council meeting of {d}", "", BANNER, "",
           "This digest is extracted by rules, not written by a person (see `summary.md` for a readable summary): each line quotes the "
           f"sentence it comes from and links the page. Elected officials on the attendance list are "
           f"named; other personal names are replaced by `{PLACEHOLDER}`. Read the [full minutes](minutes.md) or the [original PDF]({url}).", "",
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
           "as published). `facts.md` and `todo.md` are extracted by rules and carry no personal "
           "names. Every line links back to the page of the original PDF.", "",
           "| Date | Items | Votes | Pages to check | Read | Original |", "|---|---|---|---|---|---|"]
    for r in rows:
        review = ", ".join(map(str, r["review"])) or "none"
        links = (f"[minutes]({r['folder']}/minutes.md) · [facts]({r['folder']}/facts.md) · "
                 f"[follow-ups]({r['folder']}/todo.md)" + "".join(f" · [{label}]({r['folder']}/{name})" for label, name in r.get("extra", [])))
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
        (target / "facts.md").write_text(render_facts(meeting), encoding="utf-8")
        (target / "todo.md").write_text(render_todo(meeting, status_by_item), encoding="utf-8")
        meetings.append(meeting)
        counts = {}
        for it in meeting["items"]:
            counts[it["vote_result"]] = counts.get(it["vote_result"], 0) + 1
        extra = [(label, name) for label, name in (
            ("résumé", "summary.md"), ("summary EN", "summary.en.md"), ("samenvatting NL", "summary.nl.md"),
            ("minutes EN", "minutes.en.md"), ("notulen NL", "minutes.nl.md")) if (target / name).exists()]
        rows.append({"date": meeting["date"] or "undated", "folder": folder, "extra": extra, "items": len(meeting["items"]),
                     "votes": ", ".join(f"{n} {VOTE_LABELS[k].split(' ')[0]}" for k, n in counts.items() if k) or "none found",
                     "review": meeting["pages_needing_review"], "draft": bool(rec.get("draft_suspected")),
                     "version": meeting["version"], "url": rec["source_url"]})
    rows.sort(key=lambda r: r["date"], reverse=True)
    (out_dir / "index.md").write_text(render_index(rows), encoding="utf-8")
    return {"meetings": len(meetings), "folders": sorted(taken)}, meetings
