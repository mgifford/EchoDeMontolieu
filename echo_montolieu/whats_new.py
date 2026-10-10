"""What is new and what to watch: a dated digest of the latest meetings, built from the derived layer only.

Everything here comes from the same scrubbed items as the facts and topics pages: no faithful text, no names,
no private sales (counted elsewhere, never listed). The output is a data file, `public/whats-new/whats-new.json`;
the website turns it into pages and an Atom feed in each language. Nothing is predicted: "upcoming" means a
date, a plan or a postponement that the latest minutes themselves mention, with the sentence and the page.
"""
import hashlib
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


def clip(text, limit, around=None):
    """`text` cut at the end of a sentence, or else of a word, within `limit` characters; "…" marks anything left out.

    With `around` (a position in the text) a long text keeps the stretch that contains that position instead of the start."""
    text = text.strip()
    if len(text) <= limit:
        return text
    if around is not None and around > limit - 60:
        start = text.rfind(" ", 0, max(0, around - limit // 2)) + 1
        return "…" + clip(text[start:], limit - 1)
    head = text[:limit]
    end = max(head.rfind(". "), head.rfind("? "), head.rfind("! "))
    if end >= limit // 2:
        return head[:end + 1]
    return head[:head.rfind(" ")].rstrip(" ,;:") + "…"


def looks_like_prose(sentence):
    """False for table rows and column headings that the text extraction turned into a "sentence"."""
    words = sentence.split()
    if len(words) < 3 or sum(1 for w in words if any(c.isdigit() for c in w)) >= 6:      # a run of figures is a table
        return False
    return sum(1 for w in words[1:] if w[:1].isupper()) / (len(words) - 1) <= 0.4          # many capitals are headings


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
                    pending.append({"date": mt["date"], "title": it["title"], "type": f["type"], "sentence": clip(f["sentence"], 260),
                                    "page": it["pages"][0], "page_url": f"{mt['source_url']}#page={it['pages'][0]}"})
            for s in sentences(it["text"]):
                if sum(c.isdigit() for c in s) > 0.15 * len(s) or not looks_like_prose(s):       # table rows, not prose
                    continue
                for d in mentioned_dates(s, mt["date"]):
                    dates.append({"meeting": mt["date"], "mentioned": d, "sentence": clip(s, 360, around=list(_DATE.finditer(s))[-1].end()), "title": it["title"],
                                  "page": it["pages"][0], "page_url": f"{mt['source_url']}#page={it['pages'][0]}"})
    seen, unique = set(), []
    for d in sorted(dates, key=lambda d: (d["mentioned"], d["meeting"])):
        key = (d["mentioned"], d["sentence"][:80])
        if key not in seen:
            seen.add(key)
            unique.append(d)
    dropped = [{"title": t["title"], "last": t["meetings"][-1], "later_meetings": t["later_meetings"],
                "sentence": clip(t["pending"][0]["sentence"], 200)} for t in result["threads"] if t["possibly_dropped"]]
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


def string_key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def display_strings(data):
    """The French titles and sentences the What's new page shows, in page order, without repeats."""
    out = []
    for m in data.get("recent_meetings", []):
        out += [d["title"] for d in m["decisions"]]
    out += [t["title"] for t in data.get("coming_back", [])]
    for x in data.get("pending", []):
        out += [x["title"], x["sentence"]]
    out += [x["sentence"] for x in data.get("dates_mentioned", [])]
    out += [x["title"] for x in data.get("possibly_dropped", [])]
    return list(dict.fromkeys(s for s in out if s))


def write_translations(public_dir, data, translator, langs, force=False):
    """Write public/whats-new/translations.json: each French title and sentence on the page, translated.

    Same translator and checks as the other translations (numbers, legal references and language are verified; a failed
    segment is left out and the page shows the French). Strings already translated by the same model are not sent again.
    """
    from .translate import PROMPT_VERSION
    target = Path(public_dir) / "whats-new" / "translations.json"
    old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    reuse = old.get("model") == translator.model and old.get("prompt_version") == PROMPT_VERSION and not force
    strings = display_strings(data)
    texts, report = {}, {"translated": 0, "failed": 0, "needs_review": []}
    for lang in langs:
        kept = {k: v for k, v in (old.get("texts", {}).get(lang, {}) if reuse else {}).items() if k in {string_key(x) for x in strings}}
        todo = [x for x in strings if string_key(x) not in kept]
        if todo:
            for text, (shown, ok, failed) in zip(todo, translator.translate_many(todo, lang, ())):
                if ok:
                    kept[string_key(text)] = shown
                    report["translated"] += 1
                else:
                    report["failed"] += 1
        texts[lang] = kept
    if report["failed"]:
        report["needs_review"].append(f"whats-new/translations.json: {report['failed']} segment(s) failed their checks (French shown instead)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"labels": disclosure.labels("translation", translator.model), "kind": "whats-new-strings",
                                  "prompt_version": PROMPT_VERSION, "model": translator.model, "texts": texts}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def write(public_dir, meetings, result):
    target = Path(public_dir) / "whats-new"
    target.mkdir(parents=True, exist_ok=True)
    data = {**disclosure.labels("rules"), **build(meetings, result)}
    (target / "whats-new.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"latest": data["latest"], "recent": len(data["recent_meetings"]), "pending": len(data["pending"]),
            "dates": len(data["dates_mentioned"]), "dropped": len(data["possibly_dropped"])}


# ---- the plain-language paragraph, written by a model ----------------------------------------------------

INTRO_PROMPT_VERSION = "1"
INTRO_SYSTEM = (
    "Tu rédiges un court paragraphe « En bref » pour la page « Nouveautés » d’un site d’information communal. "
    "Tu reçois la liste des points des derniers conseils municipaux de Montolieu, avec leurs votes, les reports "
    "ou projets annoncés et les dates citées. Écris UN seul paragraphe de quatre à six phrases, en français clair "
    "et simple, pour des habitants.\\n"
    "Règles :\\n"
    "- N’utilise que ce qui est dans le texte. Ne devine rien, ne prédis rien, ne donne aucun conseil.\\n"
    "- Recopie exactement les dates, chiffres et montants.\\n"
    "- Ne nomme aucune personne. Ne dis rien des ventes de biens privés.\\n"
    "- Dis que ces informations viennent des procès-verbaux et peuvent être en retard sur l’actualité.\\n"
    "- Pas de titre, pas de liste, pas de préambule : seulement le paragraphe."
)


def intro_input(data):
    """What the model is given: the digest as plain lines (titles are already scrubbed)."""
    lines = []
    for m in data["recent_meetings"]:
        votes = "; ".join(f"{d['title']} ({d['vote'] or 'pas de vote repéré'})" for d in m["decisions"])
        lines.append(f"Séance du {m['date']} : {votes}.")
    for x in data["pending"][:6]:
        lines.append(f"Reporté ou prévu ({x['date']}) : {x['title']} : {x['sentence']}")
    for x in data["dates_mentioned"][:6]:
        lines.append(f"Date citée : {x['mentioned']} : {x['sentence']}")
    return "\n".join(lines)


def check_intro(text, source):
    from .translate import _NUM, _stop_ratio, number_cores
    body = text.strip()
    must_exist = [c for m in _NUM.finditer(body) for c in [re.sub(r"\D", "", m.group(0))]
                  if len(c) >= 3 or re.search(r"\d[.,]\d", m.group(0))]
    source_cores = set(number_cores(source)) | {c[:4] for c in number_cores(source)}
    sentences_n = len(re.findall(r"[.!?](?:\s|$)", body))
    return {
        "one_paragraph": "\n\n" not in body and not re.search(r"(?m)^\s*(?:[-*#]|\d+\.)", body),
        "figures_in_source": all(c in source_cores for c in must_exist),
        "is_french": _stop_ratio(body, "fr") > max(_stop_ratio(body, "en"), _stop_ratio(body, "nl")),
        "no_preamble": not re.match(r"\s*(?:voici|here is|sure|bien sûr|certainement)", body, re.I),
        "no_placeholder": "withheld" not in body,
        "length_plausible": 250 <= len(body) <= 1800 and 3 <= sentences_n <= 9,
    }


def write_intro(public_dir, data, summary_model, translator, langs, force=False, now=None):
    """Write public/whats-new/intro.json: a model-written French paragraph and its translations. Returns a report."""
    import hashlib
    from datetime import datetime, timezone
    target = Path(public_dir) / "whats-new" / "intro.json"
    report = {"written": False, "status": None, "needs_review": []}
    if not data.get("recent_meetings"):
        return report
    source = intro_input(data)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    fresh = (old.get("input_sha256") == source_hash and old.get("prompt_version") == INTRO_PROMPT_VERSION
             and old.get("summary_model") == summary_model.model
             and all(old.get("texts", {}).get(l, {}).get("model") == translator.model for l in langs))
    if fresh and not force:
        report["status"] = "unchanged"
        return report
    messages = [{"role": "system", "content": INTRO_SYSTEM}, {"role": "user", "content": source}]
    text = summary_model.complete("whats-new-intro", messages, [source, INTRO_PROMPT_VERSION]).text.strip()
    checks = check_intro(text, source)
    failed = [k for k, v in checks.items() if not v]
    if failed:
        hint = "Ta réponse précédente a échoué à ces vérifications : " + ", ".join(failed) + ". Corrige-la en respectant les règles."
        second = summary_model.complete("whats-new-intro-retry", messages + [{"role": "assistant", "content": text},
                                        {"role": "user", "content": hint}], [source, INTRO_PROMPT_VERSION, hint]).text.strip()
        second_checks = check_intro(second, source)
        if sum(second_checks.values()) >= sum(checks.values()):
            text, checks = second, second_checks
        failed = [k for k, v in checks.items() if not v]
    texts = {"fr": {"text": text, "model": summary_model.model}}
    if failed:
        report["needs_review"].append("whats-new/intro.json: " + ", ".join(failed))
    elif langs:
        for lang in langs:
            (shown, ok, _), = translator.translate_many([text], lang, ())
            if ok:
                texts[lang] = {"text": shown, "model": translator.model}
            else:
                report["needs_review"].append(f"whats-new/intro.json: {lang} translation failed its checks (French shown instead)")
    out = {"labels": disclosure.labels("summary", summary_model.model), "kind": "whats-new-intro", "prompt_version": INTRO_PROMPT_VERSION,
           "summary_model": summary_model.model, "input_sha256": source_hash,
           "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
           "status": "ok" if not failed else "needs_review", "checks_failed": failed, "texts": texts}
    if failed:
        out["texts"] = {}                      # a paragraph that failed its checks is not shown; the report names the problem
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    report.update(written=True, status=out["status"])
    return report
