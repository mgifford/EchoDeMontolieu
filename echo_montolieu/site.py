"""Static, trilingual site for GitHub Pages: French, English and Dutch trees with one navigation.

  /                 chooser; a small script sends visitors to their language (saved choice, else the browser's)
  /fr/ /en/ /nl/    the same pages in each language, each with the central navigation and a language switcher
  /places/map.html  the map (shared; its labels are English only)

Pages come from the Markdown in public/. A page is shown in the visitor's language when a file for it
exists (for example minutes.en.md); otherwise the page that does exist is shown with a visible notice
saying so, in a block marked with its own language. Markdown is rendered with raw HTML switched off.
Wording of the interface in French and Dutch was written by the AI assistant and has not been reviewed
by a native speaker (see AI.md); the footer says so.
"""
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from . import disclosure

LANGS = ("fr", "en", "nl")
NAMES = {"fr": "Français", "en": "English", "nl": "Nederlands"}
LANG_IN = {"en": {"fr": "French", "en": "English", "nl": "Dutch"},
           "fr": {"fr": "français", "en": "anglais", "nl": "néerlandais"},
           "nl": {"fr": "Frans", "en": "Engels", "nl": "Nederlands"}}
SITE_NAME = "L’Écho de Montolieu"
REPO_URL = "https://github.com/mgifford/EchoDeMontolieu"
PANNEAUPOCKET_URL = "https://app.panneaupocket.com/ville/922810321-montolieu-11170"
CSP = ("default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'")
KEY = "echo-lang"

UI = {
    "en": {
        "summary": "Summary", "full": "Full minutes", "facts_l": "Facts", "todo_l": "Follow-ups", "orig": "Original",
        "no_summary": "no summary yet", "data_l": "Data", "meeting_nav": "This meeting", "col_date": "Date",
        "meetings_intro": "One page per meeting: an AI-written summary where one exists, the full minutes tidied for reading, and a link to the original. Dates link to the summary when there is one, otherwise to the full minutes.",
        "months": ("January","February","March","April","May","June","July","August","September","October","November","December"),
        "datefmt": "{d} {m} {y}",
        "skip": "Skip to main content", "nav": "Main navigation", "language": "Language",
        "home": "Home", "minutes": "Council minutes", "meetings": "Meetings", "issues": "Issues over time",
        "finance": "Finance", "places": "Places", "map": "Map (English only)", "about_ai": "About AI",
        "table": "Table", "open_source": "Open source (AGPL-3.0)", "ai_page": "About AI in this project",
        "review": "The French and Dutch wording of this interface was written by an AI assistant and has not been reviewed by a native speaker.",
        "fallback": "This page is not available in {want} yet. It is shown in {have}.",
        "alerts_h": "Urgent alerts",
        "alerts_p": "For urgent, real-time notices from the Mairie (water cuts, weather warnings, emergencies), use {link}, an external service. This site is not updated in real time.",
        "intro": "This project helps people find information about the village of Montolieu. It points to the pages of the Mairie and other local sites and does not replace them. Text from council minutes is machine-extracted, may contain errors, and is always shown with a link to the original. Check the original before relying on anything.",
        "explore": "Explore",
        "e_meetings": "Each meeting: the minutes, with summaries and follow-ups",
        "e_issues": "what keeps coming back, and what may have been dropped",
        "e_finance": "as far as the minutes state them",
        "e_places": "Places discussed (list)",
        "e_map": "Map of places discussed",
        "minutes_h": "Council minutes",
        "minutes_total": "{total} {sets} across {years} {yrs} ({span}). Most recent first.", "sets": ("set of minutes", "sets of minutes"), "yrs": ("year", "years"),
        "none_yet": "No minutes have been published yet.",
        "gaps": "No minutes found for: {gaps}. We found none on the Mairie's site or in the Internet Archive; ask the Mairie if you need them.",
        "year_h": "{year}: {n} {sets}", "undated": "Date not detected",
        "read": "read the minutes", "pdf": "original PDF", "archive": "Internet Archive copy", "json": "extracted text (JSON)",
        "changes": "what changed in version {n}", "of": "of {date}",
        "revised": "Revised by the Mairie: {n} versions are kept.",
        "ocr": "OCR was used on {n} page(s); {r} need review.", "draft": " (draft suspected)",
        "where_h": "Where to find things", "where_note": "on {owner}; check there for current details.",
        "owner_default": "the Mairie site",
        "data": "The data is available as JSON: {a} and {b}.",
        "chooser_p": "Choose your language",
    },
    "fr": {
        "summary": "Résumé", "full": "Procès-verbal complet", "facts_l": "Faits", "todo_l": "Suites", "orig": "Original",
        "no_summary": "pas encore de résumé", "data_l": "Données", "meeting_nav": "Cette séance", "col_date": "Date",
        "meetings_intro": "Une page par séance : un résumé écrit par une IA quand il existe, le procès-verbal complet mis en forme pour la lecture, et un lien vers l’original. La date mène au résumé s’il existe, sinon au procès-verbal complet.",
        "months": ("janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"),
        "datefmt": "{d} {m} {y}",
        "skip": "Aller au contenu principal", "nav": "Navigation principale", "language": "Langue",
        "home": "Accueil", "minutes": "Procès-verbaux", "meetings": "Séances", "issues": "Sujets au fil du temps",
        "finance": "Finances", "places": "Lieux", "map": "Carte (en anglais)", "about_ai": "À propos de l’IA",
        "table": "Tableau", "open_source": "Logiciel libre (AGPL-3.0)", "ai_page": "L’IA dans ce projet",
        "review": "Les termes français et néerlandais de cette interface ont été écrits par un assistant d’IA et n’ont pas été relus par un locuteur natif.",
        "fallback": "Cette page n’existe pas encore en {want}. Elle est affichée en {have}.",
        "alerts_h": "Alertes urgentes",
        "alerts_p": "Pour les avis urgents et en temps réel de la mairie (coupures d’eau, alertes météo, urgences), utilisez {link}, un service externe. Ce site n’est pas mis à jour en temps réel.",
        "intro": "Ce projet aide à trouver des informations sur le village de Montolieu. Il renvoie vers les pages de la mairie et d’autres sites locaux et ne les remplace pas. Le texte des procès-verbaux est extrait automatiquement, peut contenir des erreurs et est toujours accompagné d’un lien vers l’original. Vérifiez l’original avant de vous y fier.",
        "explore": "Explorer",
        "e_meetings": "Chaque séance : le procès-verbal, avec résumés et suites à donner",
        "e_issues": "ce qui revient souvent, et ce qui a peut-être été abandonné",
        "e_finance": "dans la mesure où les procès-verbaux les indiquent",
        "e_places": "Lieux évoqués (liste)",
        "e_map": "Carte des lieux évoqués",
        "minutes_h": "Procès-verbaux du conseil municipal",
        "minutes_total": "{total} {sets} sur {years} {yrs} ({span}). Le plus récent d’abord.", "sets": ("procès-verbal", "procès-verbaux"), "yrs": ("année", "années"),
        "none_yet": "Aucun procès-verbal n’a encore été publié.",
        "gaps": "Aucun procès-verbal trouvé pour : {gaps}. Nous n’en avons trouvé ni sur le site de la mairie ni dans l’Internet Archive ; demandez-les à la mairie si nécessaire.",
        "year_h": "{year} : {n} {sets}", "undated": "Date non détectée",
        "read": "lire le procès-verbal", "pdf": "PDF original", "archive": "copie de l’Internet Archive", "json": "texte extrait (JSON)",
        "changes": "ce qui a changé dans la version {n}", "of": "du {date}",
        "revised": "Révisé par la mairie : {n} versions conservées.",
        "ocr": "L’OCR a servi pour {n} page(s) ; {r} à vérifier.", "draft": " (projet suspecté)",
        "where_h": "Où trouver quoi", "where_note": "sur {owner} ; vérifiez-y les informations à jour.",
        "owner_default": "le site de la mairie",
        "data": "Les données sont disponibles en JSON : {a} et {b}.",
        "chooser_p": "Choisissez votre langue",
    },
    "nl": {
        "summary": "Samenvatting", "full": "Volledige notulen", "facts_l": "Feiten", "todo_l": "Vervolg", "orig": "Origineel",
        "no_summary": "nog geen samenvatting", "data_l": "Gegevens", "meeting_nav": "Deze vergadering", "col_date": "Datum",
        "meetings_intro": "Eén pagina per vergadering: een door AI geschreven samenvatting waar die bestaat, de volledige notulen leesbaar opgemaakt, en een link naar het origineel. De datum verwijst naar de samenvatting, anders naar de volledige notulen.",
        "months": ("januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"),
        "datefmt": "{d} {m} {y}",
        "skip": "Naar de hoofdinhoud", "nav": "Hoofdnavigatie", "language": "Taal",
        "home": "Home", "minutes": "Notulen", "meetings": "Vergaderingen", "issues": "Onderwerpen in de tijd",
        "finance": "Financiën", "places": "Plaatsen", "map": "Kaart (alleen Engels)", "about_ai": "Over AI",
        "table": "Tabel", "open_source": "Open source (AGPL-3.0)", "ai_page": "AI in dit project",
        "review": "De Franse en Nederlandse teksten van deze interface zijn door een AI-assistent geschreven en niet door een moedertaalspreker nagelezen.",
        "fallback": "Deze pagina is nog niet beschikbaar in het {want}. Ze wordt getoond in het {have}.",
        "alerts_h": "Dringende meldingen",
        "alerts_p": "Voor dringende meldingen in realtime van de gemeente (waterafsluitingen, weerswaarschuwingen, noodgevallen) gebruikt u {link}, een externe dienst. Deze site wordt niet in realtime bijgewerkt.",
        "intro": "Dit project helpt mensen informatie over het dorp Montolieu te vinden. Het verwijst naar de pagina’s van de gemeente en andere lokale sites en vervangt ze niet. Tekst uit de notulen is automatisch uitgelezen, kan fouten bevatten en wordt altijd met een link naar het origineel getoond. Controleer het origineel voordat u erop vertrouwt.",
        "explore": "Verkennen",
        "e_meetings": "Elke vergadering: de notulen, met samenvattingen en vervolgacties",
        "e_issues": "wat steeds terugkomt, en wat misschien is blijven liggen",
        "e_finance": "voor zover de notulen ze vermelden",
        "e_places": "Besproken plaatsen (lijst)",
        "e_map": "Kaart van besproken plaatsen",
        "minutes_h": "Notulen van de gemeenteraad",
        "minutes_total": "{total} {sets} uit {years} {yrs} ({span}). Meest recente eerst.", "sets": ("set notulen", "sets notulen"), "yrs": ("jaar", "jaar"),
        "none_yet": "Er zijn nog geen notulen gepubliceerd.",
        "gaps": "Geen notulen gevonden voor: {gaps}. We vonden er geen op de site van de gemeente of in het Internet Archive; vraag ze aan de gemeente als u ze nodig hebt.",
        "year_h": "{year}: {n} {sets}", "undated": "Datum niet gevonden",
        "read": "lees de notulen", "pdf": "originele pdf", "archive": "kopie uit het Internet Archive", "json": "uitgelezen tekst (JSON)",
        "changes": "wat er in versie {n} veranderde", "of": "van {date}",
        "revised": "Herzien door de gemeente: {n} versies bewaard.",
        "ocr": "OCR is gebruikt op {n} pagina(’s); {r} te controleren.", "draft": " (vermoedelijk concept)",
        "where_h": "Waar vindt u wat", "where_note": "op {owner}; controleer daar de actuele gegevens.",
        "owner_default": "de site van de gemeente",
        "data": "De gegevens zijn beschikbaar als JSON: {a} en {b}.",
        "chooser_p": "Kies uw taal",
    },
}
def _word(lang, key, n):
    one, many = UI[lang][key]
    return one if n == 1 else many


_MD = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_TRANSLATION_LINK = re.compile(r" · \[[^\]]*\]\([^)]*\.(?:en|nl)\.md\)")


def anchor(text):
    """Heading id; the same rule the Markdown writer used for its table of contents."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"[àâä]", "a", re.sub(r"[éèêë]", "e", text.lower()))).strip("-")


def split_front(text):
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end():]


def _fix_href(href, root=""):
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not parts.path:
        return href
    if parts.path == "map.html":                      # the map lives once, at the site root
        return root + "places/map.html"
    path = re.sub(r"(?:\.(?:en|nl))?\.md$", ".html", parts.path)
    return path + (f"#{parts.fragment}" if parts.fragment else "")


def render_markdown(text, table_label, root=""):
    """HTML for a Markdown page: heading ids, .md links turned into .html, tables in a labelled scroll region."""
    tokens = _MD.parse(text)
    seen = {}
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            base = anchor(tokens[i + 1].content.split(" [p.")[0])      # the contents list links to the title, not the page mark
            if base:
                n = seen.get(base, 0)
                seen[base] = n + 1
                tok.attrSet("id", base if n == 0 else f"{base}-{n}")
        if tok.type == "inline":
            for child in tok.children or []:
                if child.type == "link_open":
                    child.attrSet("href", _fix_href(child.attrGet("href") or "", root))
    out = _MD.renderer.render(tokens, _MD.options, {})
    out = re.sub(r"<th(?=[ >])", '<th scope="col"', out)
    count = iter(range(1, 10_000))       # region names must be unique on a page
    out = re.sub(r"<table>", lambda _: f'<div class="tablewrap" role="region" aria-label="{html.escape(table_label)} {next(count)}" tabindex="0"><table>', out)
    return out.replace("</table>", "</table></div>")


def first_heading(text, default):
    m = re.search(r"^# (.+)$", text, re.M)
    return re.sub(r"[`*_\\]", "", m.group(1)).strip() if m else default


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def pick(base, lang):
    """(path, language of the text) for the page `base` (a path without .md) as seen in `lang`, or None."""
    translated = base.with_name(f"{base.name}.{lang}.md")
    if translated.exists():
        return translated, lang
    original = base.with_name(f"{base.name}.md")
    if original.exists():
        meta, _ = split_front(original.read_text(encoding="utf-8"))
        return original, meta.get("language", "en")
    return None


def page_bases(public):
    """Every page in public/ as (relative path without extension), counting a page once however many languages it has."""
    bases = set()
    for p in Path(public).rglob("*.md"):
        rel = p.relative_to(public)
        if rel.parts[0] == "redacted":
            continue
        stem = re.sub(r"\.(?:en|nl)$", "", rel.with_suffix("").as_posix())
        bases.add(stem)
    return sorted(bases)


class Page:
    def __init__(self, lang, rel, title, body, content_lang=None, description=None):
        self.lang, self.rel, self.title, self.body = lang, rel, title, body
        self.content_lang, self.description = content_lang or lang, description

    @property
    def depth(self):
        return self.rel.count("/")


def _up(depth):
    return "../" * depth


def layout(page, available_langs):
    """Full HTML document: skip link, header with central navigation and language switcher, main, footer."""
    lang, ui, d = page.lang, UI[page.lang], page.depth
    root = _up(d + 1)                 # the site root, from this page
    home = _up(d) or "./"             # this language's home
    e = html.escape
    nav_items = [("home", home + "index.html", "index.html"), ("minutes", home + "index.html#minutes", None),
                 ("meetings", home + "meetings/index.html", "meetings/index.html"),
                 ("issues", home + "topics/index.html", "topics/index.html"),
                 ("finance", home + "finance/index.html", "finance/index.html"),
                 ("places", home + "places/index.html", "places/index.html"),
                 ("map", root + "places/map.html", None), ("about_ai", disclosure.AI_PAGE_URL, None)]
    links = []
    for key, href, own in nav_items:
        current = ' aria-current="page"' if own and own == page.rel else ""
        links.append(f'<li><a href="{e(href)}"{current}>{e(ui[key])}</a></li>')
    switch = []
    for code in LANGS:
        href = f"{root}{code}/{page.rel}"
        cur = ' aria-current="true"' if code == lang else ""
        switch.append(f'<li><a href="{e(href)}" lang="{code}" hreflang="{code}" data-setlang="{code}"{cur}>{NAMES[code]}</a></li>')
    alternates = "".join(f'<link rel="alternate" hreflang="{c}" href="{root}{c}/{page.rel}">' for c in LANGS)
    notice = ""
    if page.content_lang != lang:
        notice = (f'<p class="notice" role="note">{e(ui["fallback"].format(want=LANG_IN[lang][lang], have=LANG_IN[lang][page.content_lang]))}</p>')
    body = f'<div lang="{page.content_lang}">{page.body}</div>' if page.content_lang != lang else page.body
    title = f"{page.title} – {SITE_NAME}" if page.rel != "index.html" else SITE_NAME
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{e(title)}</title>
{f'<meta name="description" content="{e(page.description)}">' if page.description else ''}
{alternates}<link rel="alternate" hreflang="x-default" href="{root}">
<link rel="stylesheet" href="{root}assets/site.css">
<script src="{root}assets/site.js" defer></script>
</head>
<body>
<a class="skip" href="#main">{e(ui['skip'])}</a>
<header>
<p class="brand"><a href="{home}index.html" lang="fr">{SITE_NAME}</a></p>
<nav aria-label="{e(ui['nav'])}"><ul>{''.join(links)}</ul></nav>
<nav aria-label="{e(ui['language'])}" class="langs"><ul>{''.join(switch)}</ul></nav>
</header>
<main id="main" tabindex="-1">
{notice}
{body}
</main>
<footer>
{disclosure.html('site', lang)}
<p class="note">{e(ui['review'])}</p>
<p class="note">{e(ui['open_source'])}: <a href="{REPO_URL}">{REPO_URL}</a>. <a href="{disclosure.AI_PAGE_URL}">{e(ui['ai_page'])}</a>.</p>
</footer>
</body>
</html>
"""


def human_date(lang, iso):
    """'2025-06-24' as '24 June 2025' (localised); anything else is returned unchanged."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso or ""
    y, mo, d = m.groups()
    day = "1er" if lang == "fr" and d == "01" else str(int(d))
    return UI[lang]["datefmt"].format(d=day, m=UI[lang]["months"][int(mo) - 1], y=y)


def meeting_files(public):
    """folder -> set of page names that exist for it (minutes, summary, facts, todo), in any language."""
    out = {}
    for f in (Path(public) / "meetings").glob("*/*.md"):
        name = re.sub(r"\.(?:en|nl)$", "", f.stem)
        out.setdefault(f.parent.name, set()).add(name)
    return out


def meeting_links(lang, folder, have, prefix=""):
    """Human-readable links to one meeting's pages: [(label, href)], summary first."""
    ui = UI[lang]
    pairs = [("summary", "summary"), ("full", "minutes"), ("facts_l", "facts"), ("todo_l", "todo")]
    return [(ui[label], f"{prefix}{folder}/{name}.html") for label, name in pairs if name in have]


def meetings_list(lang, index, folders, files, prefix="meetings/", up="../", every=False):
    """The minutes as a list: a dated heading, then Summary, Full minutes and Original as plain links."""
    ui, e = UI[lang], html.escape
    by_year = {}
    docs = sorted(index.get("documents", []), key=lambda d: ((d.get("meeting_date") or {}).get("value") or "", d.get("filename") or ""), reverse=True)
    for d in docs:
        when = (d.get("meeting_date") or {}).get("value")
        folder = folders.get(d["document_id"])
        shown = e(human_date(lang, when)) if when else e(ui["undated"])
        about = f'<span class="sr"> {e(ui["of"].format(date=human_date(lang, when)))}</span>' if when else ""
        have = files.get(folder, set()) if folder else set()
        links = [f'<a href="{prefix}{e(href)}">{e(label)}{about}</a>' for label, href in meeting_links(lang, folder, have)
                 if every or label in (ui["summary"], ui["full"])] if folder else []
        if folder and "summary" not in have:
            links.insert(0, f'<span class="note">{e(ui["no_summary"])}</span>')
        src = d.get("source_url")
        if src and src.startswith("https://"):
            label = ui["archive"] if src.startswith("https://web.archive.org/") else ui["pdf"]
            links.append(f'<a href="{e(src)}" lang="fr">{e(label)}{about}</a>')
        data = [f'<a href="{up}minutes/{e(d["document_id"])}.json">{e(ui["json"])}{about}</a>']
        n = d.get("versions", 1)
        flags = ""
        if n > 1:
            data.append(f'<a href="{up}minutes/{e(d["document_id"])}/diff-v{n - 1}-v{n}.json">{e(ui["changes"].format(n=n))}{about}</a>')
            flags += " " + ui["revised"].format(n=n)
        if d.get("ocr_pages"):
            flags += " " + ui["ocr"].format(n=len(d["ocr_pages"]), r=len(d.get("needs_review_pages", [])))
        lead = f'<strong>{shown}</strong>{e(ui["draft"]) if d.get("draft_suspected") else ""}'
        by_year.setdefault(when[:4] if when else "undated", []).append(
            f'<li>{lead}: {" · ".join(links)}.{e(flags)} <span class="note">{e(ui["data_l"])}: {", ".join(data)}.</span></li>')
    return by_year


def meetings_index_body(lang, index, folders, files):
    """The meetings page: every meeting by year with all its pages as plain links."""
    ui, e = UI[lang], html.escape
    by_year = meetings_list(lang, index, folders, files, prefix="", up="../../", every=True)
    parts = [f'<h1>{e(ui["meetings"])}</h1>', disclosure.html("rules", lang), f'<p>{e(ui["meetings_intro"])}</p>']
    for y in sorted((y for y in by_year if y != "undated"), reverse=True) + (["undated"] if "undated" in by_year else []):
        heading = ui["undated"] if y == "undated" else y
        parts.append(f'<h2 id="y{y}">{e(heading)}</h2><ul>{"".join(by_year[y])}</ul>')
    return "\n".join(parts)


def meeting_nav(lang, folder, name, files):
    """Strip at the top of a meeting page linking its sibling pages (summary, full minutes, facts, follow-ups)."""
    ui, e = UI[lang], html.escape
    items = []
    for label, href in meeting_links(lang, folder, files.get(folder, set())):
        here = href.endswith(f"/{name}.html")
        items.append(f'<li><a href="{e(href.split("/", 1)[1])}"{" aria-current=\"page\"" if here else ""}>{e(label)}</a></li>')
    return f'<nav class="mnav" aria-label="{e(ui["meeting_nav"])}"><ul>{"".join(items)}</ul></nav>' if len(items) > 1 else ""


def landing_body(lang, index, pointers, folders, files):
    """Home page: alerts, introduction, explore links, the minutes grouped by year, where to find things."""
    ui, e = UI[lang], html.escape
    by_year = meetings_list(lang, index, folders, files)
    years = sorted((y for y in by_year if y != "undated"), reverse=True)
    total = sum(len(v) for v in by_year.values())
    if total:
        span = f"{years[-1]}–{years[0]}" if len(years) > 1 else (years[0] if years else "")
        missing = [y for y in range(int(years[-1]), int(years[0])) if str(y) not in by_year] if years else []
        gaps, run = [], []
        for y in missing + [None]:
            if run and (y is None or y != run[-1] + 1):
                gaps.append(str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}")
                run = []
            if y is not None:
                run.append(y)
        minutes = f'<p>{e(ui["minutes_total"].format(total=total, sets=_word(lang, "sets", total), years=len(years), yrs=_word(lang, "yrs", len(years)), span=span))}</p>'
        if gaps:
            minutes += f'<p class="note">{e(ui["gaps"].format(gaps="; ".join(gaps)))}</p>'
        for y in years + (["undated"] if "undated" in by_year else []):
            n = len(by_year[y])
            heading = ui["undated"] + f": {n}" if y == "undated" else ui["year_h"].format(year=y, n=n, sets=_word(lang, "sets", n))
            minutes += f'<h3 id="minutes-{y}">{e(heading)}</h3><ul>{"".join(by_year[y])}</ul>'
    else:
        minutes = f'<p>{e(ui["none_yet"])}</p>'
    where = []
    for p in pointers.get("entries", []):
        url = p.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            label, label_lang = (p["label_fr"], "fr") if lang == "fr" else (p["label_en"], "en")
            where.append(f'<li><a href="{e(url)}" lang="{label_lang}">{e(label)}</a> '
                         f'<span class="note">{e(ui["where_note"].format(owner=p.get("owner") or ui["owner_default"]))}</span></li>')
    pocket = f'<a href="{PANNEAUPOCKET_URL}">PanneauPocket Montolieu</a>'
    data = ui["data"].format(a='<a href="../index.json">index.json</a>', b='<a href="../where_to_find_mairie.json">where_to_find_mairie.json</a>')
    return f"""<h1>{SITE_NAME}</h1>
<section class="alerts" aria-labelledby="alerts-heading"><h2 id="alerts-heading">{e(ui['alerts_h'])}</h2>
<p>{e(ui['alerts_p']).replace('{link}', pocket)}</p></section>
{disclosure.html('site', lang)}
<p>{e(ui['intro'])}</p>
<h2>{e(ui['explore'])}</h2>
<ul>
<li><a href="meetings/index.html">{e(ui['meetings'])}</a>: {e(ui['e_meetings'])}</li>
<li><a href="topics/index.html">{e(ui['issues'])}</a>: {e(ui['e_issues'])}</li>
<li><a href="finance/index.html">{e(ui['finance'])}</a>, {e(ui['e_finance'])}</li>
<li><a href="places/index.html">{e(ui['e_places'])}</a></li>
<li><a href="../places/map.html">{e(ui['e_map'])}</a> ({e(ui['map'])})</li>
</ul>
<h2 id="minutes">{e(ui['minutes_h'])}</h2>
{minutes}
<h2>{e(ui['where_h'])}</h2>
<ul>{''.join(where)}</ul>
<p class="note">{data}</p>"""


def chooser():
    e = html.escape
    links = "".join(f'<li><a href="{c}/" lang="{c}" hreflang="{c}" data-setlang="{c}">{NAMES[c]}</a></li>' for c in LANGS)
    hint = " / ".join(f'<span lang="{c}">{e(UI[c]["chooser_p"])}</span>' for c in LANGS)
    return f"""<!doctype html>
<html lang="en" data-chooser>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{SITE_NAME}</title>
<link rel="stylesheet" href="assets/site.css">
<script src="assets/site.js" defer></script>
</head>
<body class="chooser">
<main id="main">
<h1>{SITE_NAME}</h1>
<p>{hint}</p>
<ul class="choose">{links}</ul>
{disclosure.html('site', 'en')}
</main>
</body>
</html>
"""


def folders_by_document(public):
    out = {}
    for p in (Path(public) / "meetings").glob("*/minutes.md"):
        meta, _ = split_front(p.read_text(encoding="utf-8"))
        if meta.get("document_id"):
            out[meta["document_id"]] = p.parent.name
    return out


CSS = """\
:root{--bg:#FBF9F5;--fg:#1A1A1A;--brand:#004B87;--tint:#EBF3FA;--grey:#F1EFEA;--rule:#6b6b6b;color-scheme:light}
*{box-sizing:border-box}
body{margin:0;font:1rem/1.6 system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--fg)}
a{color:var(--brand)}
a:focus-visible,[tabindex]:focus-visible{outline:3px solid #005A9C;outline-offset:2px}
.skip{position:absolute;left:-999px;top:0;background:#fff;color:#000;padding:.75rem 1rem;z-index:10}
.skip:focus{left:0}
header{background:var(--brand);color:#fff;padding:.75rem 1rem}
header a{color:#fff}
header a:focus-visible{outline-color:#fff}
.brand{margin:0 0 .25rem;font-size:1.4rem;font-weight:700}
.brand a{text-decoration:none}
header ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.25rem .5rem}
header li{margin:0}
header nav a{display:inline-flex;align-items:center;min-height:44px;min-width:44px;padding:0 .6rem;text-decoration:underline}
header a[aria-current]{font-weight:700;text-decoration-thickness:3px}
.langs{margin-top:.25rem;border-top:1px solid rgba(255,255,255,.5)}
main{max-width:56rem;margin:0 auto;padding:1rem;overflow-wrap:anywhere}
main:focus{outline:none}
footer{max-width:56rem;margin:0 auto;padding:1rem;overflow-wrap:anywhere}
li{margin:.5rem 0}
.note{font-size:.95rem}
.sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
.alerts{background:var(--tint);border-left:6px solid var(--brand);padding:.5rem 1rem;margin:1rem 0}
.alerts h2{margin:.25rem 0;font-size:1.1rem}
.ai,blockquote{border-left:6px solid var(--rule);background:var(--grey);padding:.25rem 1rem;margin:1rem 0}
blockquote p{margin:.5rem 0}
.notice{border:2px solid var(--brand);background:var(--tint);padding:.5rem 1rem;margin:1rem 0}
.tablewrap{overflow-x:auto;margin:1rem 0}
table{border-collapse:collapse;min-width:100%}
th,td{border:1px solid var(--rule);padding:.4rem .6rem;text-align:left;vertical-align:top}
th{background:var(--grey)}
code{background:var(--grey);padding:0 .2rem;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--grey);padding:.5rem}
h1{font-size:1.7rem;line-height:1.25}
.mnav ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.25rem .5rem}
.mnav a{display:inline-flex;align-items:center;min-height:44px;padding:0 .75rem;border:2px solid var(--brand);border-radius:4px;background:var(--tint)}
.mnav a[aria-current]{background:var(--brand);color:#fff;font-weight:700}
.choose{list-style:none;padding:0}
.choose a{display:inline-block;min-height:44px;padding:.5rem 1rem;font-size:1.2rem}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""
JS = f"""(function () {{
  var L = ['fr', 'en', 'nl'], KEY = '{KEY}';
  function stored() {{ try {{ var v = localStorage.getItem(KEY); return L.indexOf(v) >= 0 ? v : null; }} catch (e) {{ return null; }} }}
  function browser() {{
    var l = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ''];
    for (var i = 0; i < l.length; i++) {{ var p = String(l[i]).toLowerCase().split('-')[0]; if (L.indexOf(p) >= 0) return p; }}
    return 'en';
  }}
  if (document.documentElement.hasAttribute('data-chooser')) {{ location.replace((stored() || browser()) + '/'); return; }}
  document.addEventListener('click', function (ev) {{
    var a = ev.target.closest && ev.target.closest('a[data-setlang]');
    if (a) {{ try {{ localStorage.setItem(KEY, a.getAttribute('data-setlang')); }} catch (e) {{}} }}
  }});
}})();
"""


def build(out_dir, public="public", data="data"):
    out, public, data = Path(out_dir), Path(public), Path(data)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "site.css").write_text(CSS, encoding="utf-8")
    (out / "assets" / "site.js").write_text(JS, encoding="utf-8")
    index = _read_json(public / "index.json", {"count": 0, "documents": []})
    pointers = _read_json(data / "where_to_find_mairie.json", {"entries": []})
    # data files and the map, as before
    if (public / "index.json").exists():
        shutil.copyfile(public / "index.json", out / "index.json")
    if (public / "minutes").exists():
        shutil.copytree(public / "minutes", out / "minutes")
    for name in ("map.html", "places.json"):
        if (public / "places" / name).exists():
            (out / "places").mkdir(exist_ok=True)
            shutil.copyfile(public / "places" / name, out / "places" / name)
    if (data / "where_to_find_mairie.json").exists():
        shutil.copyfile(data / "where_to_find_mairie.json", out / "where_to_find_mairie.json")
    (out / "index.html").write_text(chooser(), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    folders = folders_by_document(public)
    for lang in LANGS:
        pages = [Page(lang, "index.html", SITE_NAME, landing_body(lang, index, pointers, folders, meeting_files(public)))]
        for base in page_bases(public):
            found = pick(public / base, lang)
            if not found:
                continue
            path, content_lang = found
            meta, text = split_front(path.read_text(encoding="utf-8"))
            text = _TRANSLATION_LINK.sub("", text)
            body = render_markdown(text, UI[lang]["table"], _up(base.count("/") + 1))
            parts = base.split("/")
            if base == "meetings/index":
                body, content_lang = meetings_index_body(lang, index, folders, meeting_files(public)), lang
            elif len(parts) == 3 and parts[0] == "meetings":
                body = meeting_nav(lang, parts[1], parts[2], meeting_files(public)) + body
            pages.append(Page(lang, base + ".html", first_heading(text, base), body, content_lang))
        for page in pages:
            target = out / lang / page.rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(layout(page, LANGS), encoding="utf-8")
    return out
