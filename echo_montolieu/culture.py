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


CHURCH = {'fr': {'church': 'Église Saint-André : chantier, phase 1', 'sign_h': 'Ce que dit le panneau de chantier', 'sign': 'Panneau vu {seen}. L’église est classée Monument historique depuis le {listed}. Coût de la phase 1 : {total} HT (une tranche ferme en cours et trois tranches optionnelles). Tranche ferme : {firm} HT, financée par {funders}. La Fondation du Patrimoine ouvre une souscription.', 'rec_h': 'Ce que disent les procès-verbaux, et pourquoi les chiffres diffèrent', 'rec': 'Les deux montants de la tranche ferme sont justes et ne mesurent pas la même chose. Le {d1} le procès-verbal donne l’estimation des travaux : {est} HT (le panneau et la somme des financeurs donnent {firm}, donc l’écart de {diff} est réel et sans explication : probablement une coquille, dans le procès-verbal ou sur le panneau). Après l’appel d’offres, le montant validé de la tranche ferme est {val} HT, car le lot 3 (plâtrerie) n’a pas été attribué et a été relancé ; l’ensemble des tranches des lots attribués fait {allt} HT. Le {d2} le lot 3 a été attribué à Europlâtre pour {lot3} HT, toutes tranches. Ajouter les deux donne {sum} HT, comparé aux {total} HT du panneau : c’est un calcul de ce projet, non un chiffre officiel, et le panneau peut dater d’avant l’appel d’offres.', 'est': 'estimation', 'val': 'validé'}, 'en': {'church': 'St André church: phase 1 works', 'sign_h': 'What the site notice says', 'sign': 'Notice seen {seen}. The church has been a listed historic monument since {listed}. Phase 1 costs {total} excl. VAT (a firm tranche under way and three optional tranches). Firm tranche: {firm} excl. VAT, funded by {funders}. The Fondation du Patrimoine has a public appeal open.', 'rec_h': 'What the minutes say, and why the figures differ', 'rec': 'The two firm-tranche amounts are both right and measure different things. On {d1} the minutes give the works estimate: {est} excl. VAT (the notice and the sum of the funders say {firm}, so the {diff} gap is real and unexplained: probably a typo, in the minutes or on the notice). After the tender, the validated firm-tranche amount is {val} excl. VAT, because lot 3 (plastering) was not awarded and was put out again; all tranches of the awarded lots come to {allt} excl. VAT. On {d2} lot 3 was awarded to Europlâtre for {lot3} excl. VAT, all tranches. Adding the two gives {sum} excl. VAT, compared with the notice’s {total} excl. VAT: that is this project’s arithmetic, not an official figure, and the notice may predate the tender.', 'est': 'estimate', 'val': 'validated'}, 'nl': {'church': 'Sint-Andrékerk: werken fase 1', 'sign_h': 'Wat het bouwbord zegt', 'sign': 'Bord gezien {seen}. De kerk is sinds {listed} beschermd monument. Fase 1 kost {total} excl. btw (een lopende vaste tranche en drie optionele tranches). Vaste tranche: {firm} excl. btw, gefinancierd door {funders}. De Fondation du Patrimoine heeft een inzameling open.', 'rec_h': 'Wat de notulen zeggen, en waarom de bedragen verschillen', 'rec': 'Beide bedragen voor de vaste tranche zijn juist en meten iets anders. Op {d1} geven de notulen de raming van de werken: {est} excl. btw (het bord en de som van de financiers zeggen {firm}, dus het verschil van {diff} is echt en onverklaard: waarschijnlijk een tikfout, in de notulen of op het bord). Na de aanbesteding is het goedgekeurde bedrag van de vaste tranche {val} excl. btw, omdat kavel 3 (stucwerk) niet werd gegund en opnieuw werd uitgeschreven; alle tranches van de gegunde kavels samen zijn {allt} excl. btw. Op {d2} werd kavel 3 gegund aan Europlâtre voor {lot3} excl. btw, alle tranches. Samen is dat {sum} excl. btw, tegenover {total} excl. btw op het bord: dit is een berekening van dit project, geen officieel cijfer, en het bord kan van voor de aanbesteding dateren.', 'est': 'raming', 'val': 'goedgekeurd'}}


def load_links(data_file="data/culture.json"):
    entries = json.loads(Path(data_file).read_text(encoding="utf-8")).get("entries", [])
    return [e for e in entries if str(e.get("url", "")).startswith("https://")]


def load_church(data_file="data/culture.json"):
    return json.loads(Path(data_file).read_text(encoding="utf-8")).get("church")


def _eur(x, lang):
    s = f"{x:,.2f}"
    s = s.replace(",", "\u202f").replace(".", ",") if lang != "en" else s
    return f"€{s}" if lang == "en" else f"{s}\u00a0€"


def church_section(lang, church):
    """The church notice and how it matches the minutes. Every figure comes from data/culture.json."""
    if not church:
        return []
    c, sign = CHURCH[lang], church["sign"]
    m = {x["label"]: x for x in church["minutes"]}
    e = lambda v: _eur(v, lang)
    link = lambda x: f"[{e(x['amount_ht'])}]({x['url']})"
    funders = ", ".join(f"{n} {e(v)}" for n, v in sign["funders"])
    firm, est = sign["firm_tranche_ht"], m["firm_estimate"]["amount_ht"]
    lines = [f"## {c['church']}", "", f"### {c['sign_h']}", "",
             c["sign"].format(seen=sign["seen"][lang], listed=sign["listed_since"], total=e(sign["phase1_total_ht"]),
                              firm=e(firm), funders=funders), "",
             f"### {c['rec_h']}", "",
             c["rec"].format(d1=m["firm_estimate"]["date"], est=link(m["firm_estimate"]), firm=e(firm), diff=e(abs(firm - est)),
                             val=link(m["firm_validated"]), v=c["val"], allt=link(m["awarded_all_tranches"]), d2=m["lot3_all_tranches"]["date"],
                             lot3=link(m["lot3_all_tranches"]), total=e(sign["phase1_total_ht"]),
                             sum=e(m["awarded_all_tranches"]["amount_ht"] + m["lot3_all_tranches"]["amount_ht"])), ""]
    return lines


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


def render(lang, links, groups, checked, church=None):
    t = T[lang]
    lines = [f"# {t['title']}", "", disclosure.markdown("site", lang), "", f"> {t['basis']}", "", t["intro"], "", f"> {t['gap']}", ""]
    lines += [f"## {t['links']}", ""]
    for e in links:
        lines.append(f"- [{e['title'][lang]}]({e['url']}): {e['about'][lang]}")
    lines += ["", f"*{t['ok']} {checked}.*", ""] + church_section(lang, church) + [f"## {t['decisions']}", ""]
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
        page = disclosure.with_front_matter(render(lang, links, groups, checked, load_church(data_file)), T[lang]["title"], kind="site")
        if lang == "fr":
            page = page.replace("---\n", "---\nlanguage: fr\n", 1)
        (target / name).write_text(page, encoding="utf-8")
    return {"links": len(links), "decisions": sum(len(v) for v in groups.values())}
