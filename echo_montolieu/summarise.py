"""A readable French summary of one meeting, written by a model from the scrubbed text.

The model is given only the scrubbed text of each item (private names replaced; private
property sales reduced to a count). Its output is a machine-written summary and is treated
as one: it is checked, labelled, and never presented as the minutes.

Checks (a failure does not delete the summary; it marks it "à relire"):
  * the three required sections are present;
  * every figure of three digits or more, and every decimal, appears in the source;
  * every cited page exists, and at least one page is cited;
  * it is French, has no preamble, and is neither tiny nor huge.
"""
import hashlib
import re
from datetime import datetime, timezone

from . import disclosure
from .translate import _NUM, _STOP, _stop_ratio, number_cores

SUMMARY_PROMPT_VERSION = "1"
MAX_ITEM_CHARS = 7000
SECTIONS = ("## Résumé", "## Points abordés", "## Suites annoncées")

SYSTEM = (
    "Tu rédiges des résumés pour un site d’information communal. Tu reçois le texte d’un procès-verbal "
    "de conseil municipal, découpé en points numérotés avec leurs pages. Rédige un résumé fidèle, en "
    "français clair et simple, sans jargon inutile.\n"
    "Règles :\n"
    "- N’utilise que ce qui est dans le texte. Ne devine rien. N’ajoute aucun jugement ni commentaire.\n"
    "- Recopie exactement les chiffres, montants, dates et références juridiques.\n"
    "- Si un point indique seulement des décisions sur des ventes de biens privés, dis qu’il y a eu des "
    "décisions sur des ventes, sans aucun détail.\n"
    "- Ne nomme pas de personne privée. Les élus peuvent être nommés lorsque le texte les nomme.\n"
    "- Cite toujours la page entre crochets, par exemple [p.3].\n"
    "- Reste concis : une ou deux phrases par point.\n"
    "Format exact, sans rien avant ni après :\n"
    "## Résumé\n(trois à cinq phrases sur l’ensemble de la séance)\n"
    "## Points abordés\n- **Titre du point** : une ou deux phrases. Vote : à l’unanimité, à la majorité ou non précisé. [p.N]\n"
    "## Suites annoncées\n- une puce par suite annoncée (reporté, à prévoir, autorisation donnée) avec sa page, "
    "ou la phrase « Aucune suite annoncée dans le texte. »"
)


def summary_input(meeting):
    """The text given to the model: numbered items with page ranges, scrubbed."""
    parts = [f"Séance du {meeting['date'] or 'date inconnue'} ({meeting['page_count']} pages)."]
    for n, item in enumerate(meeting["items"], start=1):
        a, b = item["pages"]
        pages = f"p.{a}" if a == b else f"p.{a}-{b}"
        if item["sensitive"]:
            body = (f"[Décisions relatives à des ventes de biens privés : {item.get('sale_notices', 0)} avis. "
                    "Aucun détail fourni.]")
        else:
            body = item["text"]
            if len(body) > MAX_ITEM_CHARS:
                body = body[:MAX_ITEM_CHARS] + " […texte coupé]"
        parts.append(f"### Point {n} : {item['title']} ({pages})\n{body}")
    return "\n\n".join(parts)


def check_summary(summary, source, page_count):
    """{check: bool}. Small numbers are not checked: counts and days are often restated."""
    body = re.sub(r"\[p\.\s*\d+(?:\s*[-–]\s*\d+)?\]", " ", summary)
    source_cores = set(number_cores(source))
    must_exist = [c for m in _NUM.finditer(body)
                  for c in [re.sub(r"\D", "", m.group(0))]
                  if len(c) >= 3 or re.search(r"\d[.,]\d", m.group(0))]
    cited = [int(x) for grp in re.findall(r"\[p\.\s*(\d+(?:\s*[-–]\s*\d+)?)\]", summary)
             for x in re.findall(r"\d+", grp)]
    return {
        "sections_present": all(h in summary for h in SECTIONS),
        "figures_in_source": all(c in source_cores for c in must_exist),
        "pages_cited": bool(cited),
        "pages_exist": all(1 <= c <= page_count for c in cited),
        "is_french": (_stop_ratio(summary, "fr") > _stop_ratio(summary, "en")
                      and _stop_ratio(summary, "fr") > _stop_ratio(summary, "nl")),
        "no_preamble": not re.match(r"\s*(?:voici|here is|sure|bien sûr|certainement)", summary, re.I),
        "no_placeholder": "[name withheld]" not in summary and "[names withheld]" not in summary,
        "length_plausible": 400 <= len(summary) <= 6000,
    }


def summary_front_matter(meeting, model, checks, source_hash, generated_at):
    failed = [k for k, v in checks.items() if not v]
    return "\n".join([
        "---",
        f'title: "Résumé : {meeting["date"]}"',
        f"date: {meeting['date']}",
        f"document_id: {meeting['document_id']}",
        f"version: {meeting['version']}",
        f"source: {meeting['source_url']}",
        "language: fr",
        "machine_generated: true",
        "kind: summary",
        f"summary_model: {model}",
        f"prompt_version: {SUMMARY_PROMPT_VERSION}",
        f"input_sha256: {source_hash}",
        f"generated_at: {generated_at}",
        f"status: {'ok' if not failed else 'needs_review'}",
        f"checks_failed: [{', '.join(failed)}]",
        *[f"{k}: {v}" for k, v in disclosure.front_matter("summary", model).items()],
        "---", ""])


def render_summary_file(meeting, summary, model, checks, source_hash, generated_at):
    failed = [k for k, v in checks.items() if not v]
    url = meeting["source_url"]
    head = [summary_front_matter(meeting, model, checks, source_hash, generated_at),
            f"# Résumé du conseil municipal du {meeting['date']}", "",
            disclosure.markdown("summary", "fr", model), "",
            f"> Lire le [procès-verbal](minutes.md) ou le [PDF original]({url}).", ""]
    if failed:
        head += [f"> **À relire** : une vérification automatique a échoué ({', '.join(failed)}).", ""]
    return "\n".join(head) + summary.strip() + "\n"


def summarise(meeting, model, now=None):
    """(markdown, checks, status). `model` is a ChatModel. One corrective retry if checks fail."""
    source = summary_input(meeting)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    generated_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": source}]
    summary = model.complete("summarise", messages, [source, SUMMARY_PROMPT_VERSION]).text
    checks = check_summary(summary, source, meeting["page_count"])
    failed = [k for k, v in checks.items() if not v]
    if failed:
        hint = ("Ta réponse précédente a échoué à ces vérifications : " + ", ".join(failed) +
                ". Corrige-la en respectant exactement le format et les règles.")
        retry = messages + [{"role": "assistant", "content": summary}, {"role": "user", "content": hint}]
        second = model.complete("summarise-retry", retry, [source, SUMMARY_PROMPT_VERSION, hint]).text
        second_checks = check_summary(second, source, meeting["page_count"])
        if sum(second_checks.values()) >= sum(checks.values()):
            summary, checks = second, second_checks
    md = render_summary_file(meeting, summary, model.model, checks, source_hash, generated_at)
    return md, checks, ("ok" if all(checks.values()) else "needs_review")
