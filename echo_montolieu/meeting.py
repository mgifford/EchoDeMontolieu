"""Parse one published record into a structured, derived meeting model.

The model is derived, machine-generated and heuristic. It never replaces the
faithful record: every item keeps its page range so a reader can go back to the
original. Derived text has personal names replaced; the faithful Markdown keeps
them. Property-sale items (right of pre-emption) keep only counts, because a
place, a price and a date together identify a seller in a village this size.
"""
import re

from .privacy import _fold, _patterns
from .signals import (find_amounts, find_exceptions, find_followups, find_legal_refs,
                      find_place_candidates, find_topics, is_property_transaction,
                      parse_votes, sentences)
from .text import clean_page_lines, paragraphs, sentence_case

PLACEHOLDER = "[name withheld]"
ACRONYMS = {"pv": "PV", "plu": "PLU", "ccas": "CCAS", "alsh": "ALSH", "cfu": "CFU", "dia": "DIA",
            "tva": "TVA", "cgct": "CGCT", "sdis": "SDIS", "siap": "SIAP", "epci": "EPCI",
            "rgpd": "RGPD", "mvdl": "MVDL", "syaden": "SYADEN", "abf": "ABF"}
MIN_PROSE_CHARS = 40

_HONORIFIC_NAME_ANYCASE = re.compile(
    r"\b(?i:Monsieur|Madame|Mademoiselle|M\.|Mme|Mlle)\s+"
    r"(?!(?i:le|la|les|Maire|Adjoint|Adjointe|Président|Présidente|Conseil|Trésorier)\b)"
    r"[A-ZÀ-Ý][\wÀ-ÿ’'\-]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ’'\-]+){0,2}")
_HONORIFIC_NAME = re.compile(
    r"\b(?:Monsieur|Madame|Mademoiselle|M\.|Mme|Mlle)\s+"
    r"(?!(?:le|la|les|Maire|Adjoint|Adjointe|Président|Présidente|Conseil|Trésorier)\b)"
    r"[A-ZÀ-Ý][\wÀ-ÿ’'\-]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ’'\-]+){0,2}")
_PRESENT = re.compile(r"[ée]taient?\s+pr[ée]sents?\s*:?\s*(.+?)(?=[ée]taient?\s+(?:absents?|excus)|la séance est ouverte|secr[ée]tariat|ordre du jour|$)", re.I | re.S)
_ABSENT = re.compile(r"[ée]taient?\s+(?:absents?|excus[ée]s?)\s*:?\s*(.+?)(?=la séance est ouverte|secr[ée]tariat|ordre du jour|$)", re.I | re.S)
_PROXY = re.compile(r"\s*(?:procuration|pouvoir)\s+à\s+", re.I)


def _name_list(block):
    """(main, proxy_holders) from a present/absent block.

    "A B procuration à C D" names an absent person (main) and the councillor who
    holds their proxy (a holder, who is present and counted elsewhere).
    """
    main, holders = [], []
    for chunk in re.split(r"[,;\n]|\.(?=\s+[A-ZÀ-Ý])|\bet\b", block):
        parts = _PROXY.split(chunk.strip(" ."), maxsplit=1)
        for i, part in enumerate(parts):
            part = part.strip(" .:")
            words = part.split()
            if 2 <= len(words) <= 4 and all(w[:1].isupper() for w in words):
                (holders if i else main).append(part)
    return main, holders


def attendance_names(full_text):
    """Names in the present and absent lists, and proxy holders. Used only to scrub text."""
    flat = " ".join(full_text.split())
    present, absent, holders = [], [], []
    for m in _PRESENT.finditer(flat):
        main, h = _name_list(m.group(1))
        present += main
        holders += h
    for m in _ABSENT.finditer(flat):
        main, h = _name_list(m.group(1))
        absent += main
        holders += h
    return present, absent, holders


def scrub_names(text, names):
    """Replace known names (any word order) and "M./Mme Surname" with a placeholder."""
    if not text:
        return text
    folded = _fold(text)
    spans = []
    for name in names:
        if len(name.split()) >= 2:
            for pat in _patterns(name):
                spans += [(m.start(), m.end()) for m in pat.finditer(folded)]
    spans += [(m.start(), m.end()) for m in _HONORIFIC_NAME.finditer(text)]
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept, last = [], -1
    for start, end in spans:
        if start >= last:
            kept.append((start, end))
            last = end
    for start, end in reversed(kept):
        text = text[:start] + PLACEHOLDER + text[end:]
    # "[name withheld], [name withheld] et [name withheld]" reads better as one marker.
    run = re.escape(PLACEHOLDER)
    return re.sub(rf"{run}(?:\s*(?:,|;|et|\bet\b)\s*{run})+", "[names withheld]", text)


def display_title(title_raw, agenda):
    """Sentence-case a heading, preferring the agenda entry that is the same words.

    Headings are printed in capitals without accents; the agenda list keeps the
    accents, so when both say the same thing the agenda wording is used.
    """
    key = title_key(title_raw)
    for entry in agenda:
        ek = title_key(entry)
        if ek and (ek == key or key.startswith(ek) or ek.startswith(key)):
            return entry.strip()
    title = sentence_case(title_raw)
    return re.sub(r"\b[A-Za-zÀ-ÿ]+\b", lambda m: ACRONYMS.get(m.group(0).lower(), m.group(0)), title)


def title_key(title):
    """Folded, order-preserving key of a title: lower case, no accents, no digits."""
    words = re.findall(r"[a-z]{2,}", _fold(title))
    return " ".join(w for w in words if w not in {"du", "de", "des", "la", "le", "les", "au", "aux", "et", "un", "une", "en", "d", "l"})


def surname_tokens(names):
    """Folded surname-like tokens (ALL-CAPS words) of the attendance names, hyphens split."""
    out = set()
    for name in names:
        for word in name.split():
            if len(word) >= 3 and word.upper() == word:
                out.update(t for t in re.findall(r"[a-z]{3,}", _fold(word)))
    return out


def scrub_title(raw_title, names, surnames):
    """Scrub a heading. Headings are often a person's name introducing their statement."""
    text = scrub_names(raw_title, names)
    text = _HONORIFIC_NAME_ANYCASE.sub(PLACEHOLDER, text)
    words = text.split()
    kept = []
    for w in words:
        tokens = re.findall(r"[a-z]{3,}", _fold(w))
        kept.append(PLACEHOLDER if tokens and all(t in surnames for t in tokens) else w)
    text = " ".join(kept)
    return re.sub(rf"(?:{re.escape(PLACEHOLDER)}\s*)+", PLACEHOLDER + " ", text).strip()


def _sentence_blocks(blocks):
    return [b for b in blocks if b["kind"] == "paragraph" and len(b["text"].split()) >= 8]


def _prose_length(blocks):
    return sum(len(re.findall(r"[a-zà-ÿ]", b["text"])) for b in blocks
               if b["kind"] in ("paragraph", "bullet"))


def split_items(blocks):
    """Header blocks, document title, and items (heading + body blocks)."""
    headings = [i for i, b in enumerate(blocks) if b["kind"] == "heading"]
    if not headings:
        return None, blocks, []
    title = blocks[headings[0]]
    cut = headings[1] if len(headings) > 1 else len(blocks)
    header = blocks[headings[0] + 1: cut]
    items = []
    for n, start in enumerate(headings[1:], start=0):
        end = headings[n + 2] if n + 2 < len(headings) else len(blocks)
        body = blocks[start + 1: end]
        heading = blocks[start]
        # A heading whose body has almost no prose is a table caption or sub-heading:
        # fold it into the previous item.
        if items and (_prose_length(body) < MIN_PROSE_CHARS or not _sentence_blocks(body)):
            items[-1]["blocks"].append({"kind": "subheading", "text": heading["text"],
                                        "page": heading["page"]})
            items[-1]["blocks"].extend(body)
            continue
        items.append({"title_raw": heading["text"], "blocks": list(body), "page": heading["page"]})
    return title, header, items


def _block_text(blocks):
    return "\n".join(b["text"] for b in blocks)


def _snippet(body, scrub, limit=320):
    out = []
    for s in sentences(body):
        if re.search(r"^vote\b|unanimit|à la majorité|voix pour|abstention", s, re.I):
            continue
        out.append(scrub(s))
        if sum(len(x) for x in out) > limit:
            break
    text = " ".join(out)
    return (text[:limit].rsplit(" ", 1)[0] + "…") if len(text) > limit else text


def parse_meeting(record):
    """Structured model of one record (its current version)."""
    lines = [(l, p["page"]) for p in record["pages"] if p.get("text")
             for l in clean_page_lines(p["text"], p["page"])]
    blocks = paragraphs(lines)
    full = "\n".join(l for l, _ in lines)
    present, absent, holders = attendance_names(full)
    names = present + absent + holders

    surnames = surname_tokens(names)

    def scrub(text):
        return scrub_names(text, names)

    title_block, header, raw_items = split_items(blocks)
    agenda = [b["text"] for b in header if b["kind"] == "bullet"]
    items = []
    for n, raw in enumerate(raw_items, start=1):
        body = _block_text(raw["blocks"])
        pages = [raw["page"]] + [b["page"] for b in raw["blocks"]]
        safe_raw = scrub_title(raw["title_raw"], names, surnames)
        title = display_title(safe_raw, agenda) if safe_raw == raw["title_raw"] else sentence_case(safe_raw)
        sensitive = is_property_transaction(raw["title_raw"], body)
        votes = parse_votes(body)
        item = {
            "id": f"{record['document_id']}-{n:02d}",
            "title": scrub(title),
            "title_key": title_key(scrub(title)),
            "pages": [min(pages), max(pages)],
            "topics": [t for t, hits in find_topics(safe_raw, body) if hits >= 3][:3],
            "vote_result": votes["result"],
            "votes": [{k: (scrub(v) if k == "sentence" else v) for k, v in vote.items()}
                      for vote in votes["votes"]],
            "sensitive": sensitive,
        }
        if sensitive:
            # Counts only: no places, amounts or sentences from private sales.
            item["sale_notices"] = len(votes["votes"])
            item.update({"amounts": [], "legal_refs": [], "exceptions": [], "followups": [],
                         "places": [], "snippet": ""})
        else:
            def keep(rows):
                return [{**r, "sentence": scrub(r["sentence"])} for r in rows]
            item.update({
                "amounts": keep(find_amounts(body)),
                "legal_refs": keep(find_legal_refs(body)),
                "exceptions": keep(find_exceptions(body)),
                "followups": keep(find_followups(body)),
                "places": find_place_candidates(body),
                "snippet": _snippet(body, scrub),
            })
        items.append(item)

    date = record.get("meeting_date") or {}
    return {
        "document_id": record["document_id"],
        "date": date.get("value"),
        "date_status": date.get("status"),
        "title": sentence_case(title_block["text"]) if title_block else None,
        "source_url": record["source_url"],
        "source_sha256": record["source_sha256"],
        "version": record.get("version", 1),
        "versions": len(record.get("versions", [])) or 1,
        "page_count": record["page_count"],
        "pages_needing_review": [p["page"] for p in record["pages"]
                                 if p.get("status") == "needs_review"],
        "attendance": {"present": len(present), "absent": len(absent)},
        "agenda": [scrub(a) for a in agenda],
        "items": items,
    }
