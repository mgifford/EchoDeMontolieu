"""A page on culture and tourism: what the council decided, and where to look for the rest.

Built from the published decisions table (public/data/decisions.csv), so it carries the same
vote and page link as the rest of the record, and from a short hand-chosen list of links in
data/culture.json. It says what the minutes say. It does not count visitors or list events:
the minutes do not, and the owners of those pages do (see the links).
Written in French, English and Dutch by `render`; nothing is fetched.
"""
import csv
import json
from pathlib import Path

from . import disclosure

CULTURE_TOPICS = ("musée Cérès Franco", "Village du Livre (MVDL)", "église Saint-André", "patrimoine, culture, tourisme")
GROUP_ORDER = CULTURE_TOPICS

T = {
    "fr": dict(title="Culture et tourisme", basis="Les décisions viennent des procès-verbaux publiés (règles de tri, non relues). Les liens sont choisis à la main.",
               intro="Ce que le conseil municipal a décidé sur le musée, le village du livre, l’église et le tourisme, et où trouver le reste : événements, horaires et fréquentation ne figurent pas dans les procès-verbaux.",
               groups={"musée Cérès Franco": "Musée Cérès Franco", "Village du Livre (MVDL)": "Association Village du Livre",
                       "église Saint-André": "Église Saint-André", "patrimoine, culture, tourisme": "Patrimoine, culture et tourisme (autres)"},
               links="Où trouver événements et informations", decisions="Décisions du conseil", vote="Vote",
               votes={"unanimous": "unanimité", "majority": "majorité", "rejected": "rejeté", "none": "pas de vote trouvé"},
               gap="Ce que cette page ne dit pas : le nombre de visiteurs par an n’est pas dans les procès-verbaux et n’a pas été trouvé dans des sources publiques ; demandez-le à l’association, au musée ou à l’office de tourisme.",
               ok="Liens choisis le"),
    "en": dict(title="Culture and tourism", basis="Decisions come from the published minutes (sorted by rules, not reviewed). The links are hand-chosen.",
               intro="What the council decided about the museum, the book village, the church and tourism, and where to find the rest: events, opening hours and visitor numbers are not in the minutes.",
               groups={"musée Cérès Franco": "Cérès Franco museum", "Village du Livre (MVDL)": "Village du Livre association",
                       "église Saint-André": "St André church", "patrimoine, culture, tourisme": "Heritage, culture and tourism (other)"},
               links="Where to find events and information", decisions="Council decisions", vote="Vote",
               votes={"unanimous": "unanimous", "majority": "majority", "rejected": "rejected", "none": "no vote found"},
               gap="What this page does not say: the number of visitors per year is not in the minutes and was not found in public sources; ask the association, the museum or the tourist office.",
               ok="Links chosen on"),
    "nl": dict(title="Cultuur en toerisme", basis="De besluiten komen uit de gepubliceerde notulen (op regels gesorteerd, niet nagelezen). De links zijn met de hand gekozen.",
               intro="Wat de gemeenteraad besloot over het museum, het boekendorp, de kerk en het toerisme, en waar de rest te vinden is: evenementen, openingstijden en bezoekersaantallen staan niet in de notulen.",
               groups={"musée Cérès Franco": "Museum Cérès Franco", "Village du Livre (MVDL)": "Vereniging Village du Livre",
                       "église Saint-André": "Sint-Andrékerk", "patrimoine, culture, tourisme": "Erfgoed, cultuur en toerisme (overig)"},
               links="Waar vindt u evenementen en informatie", decisions="Besluiten van de raad", vote="Stemming",
               votes={"unanimous": "unaniem", "majority": "meerderheid", "rejected": "verworpen", "none": "geen stemming gevonden"},
               gap="Wat deze pagina niet zegt: het aantal bezoekers per jaar staat niet in de notulen en is niet in openbare bronnen gevonden; vraag het de vereniging, het museum of het toeristenbureau.",
               ok="Links gekozen op"),
}


def load_links(data_file="data/culture.json"):
    entries = json.loads(Path(data_file).read_text(encoding="utf-8")).get("entries", [])
    return [e for e in entries if str(e.get("url", "")).startswith("https://")]


def load_decisions(public_dir):
    path = Path(public_dir) / "data" / "decisions.csv"
    if not path.exists():
        return {g: [] for g in GROUP_ORDER}
    groups = {g: [] for g in GROUP_ORDER}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            topics = [t.strip() for t in row["topics"].split(";")]
            for g in GROUP_ORDER:          # an item can sit in several groups
                if g in topics:
                    groups[g].append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: (r["date"], int(r["n"] or 0)), reverse=True)
    return groups


def _vote(row, t):
    v = row["vote"]
    key = v if v in ("unanimous", "rejected") else "majority" if v.startswith("majority") else "none"
    counts = ""
    if row["votes_for"] or row["votes_against"]:
        counts = f" ({row['votes_for'] or 0}/{row['votes_against'] or 0}/{row['abstentions'] or 0})"
    return t["votes"][key] + counts


def render(lang, links, groups, checked):
    t = T[lang]
    lines = [f"# {t['title']}", "", disclosure.markdown("site", lang), "", f"> {t['basis']}", "", t["intro"], "", f"> {t['gap']}", ""]
    lines += [f"## {t['links']}", ""]
    for e in links:
        lines.append(f"- [{e['title'][lang]}]({e['url']}): {e['about'][lang]}")
    lines += ["", f"*{t['ok']} {checked}.*", "", f"## {t['decisions']}", ""]
    for g in GROUP_ORDER:
        rows = groups.get(g, [])
        if not rows:
            continue
        lines += [f"### {t['groups'][g]}", ""]
        for r in rows:
            amount = ""
            lines.append(f"- {r['date']}: [{r['title']}]({r['original_page_url']}) ({t['vote']}: {_vote(r, t)}){amount}")
        lines.append("")
    return "\n".join(lines)


def write(public_dir, data_file="data/culture.json", checked="2026-10-10"):
    links = load_links(data_file)
    groups = load_decisions(public_dir)
    target = Path(public_dir) / "culture"
    target.mkdir(parents=True, exist_ok=True)
    for lang, name in (("fr", "index.md"), ("en", "index.en.md"), ("nl", "index.nl.md")):
        page = disclosure.with_front_matter(render(lang, links, groups, checked), T[lang]["title"], kind="site")
        if lang == "fr":
            page = page.replace("---\n", "---\nlanguage: fr\n", 1)
        (target / name).write_text(page, encoding="utf-8")
    return {"links": len(links), "decisions": sum(len(v) for v in groups.values())}
