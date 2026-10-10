"""The commune's finances over time, from the national accounts open data. A fetch step and a page, nothing more.

The Direction générale des Finances publiques (DGFiP) publishes the accounting balances of every commune,
one dataset per year, under the Licence Ouverte (https://data.economie.gouv.fr/, "Balances comptables des communes").
This module reads one exported file per year (the rows of Montolieu's SIREN), keeps the commune's main budget
(not the annex budgets), adds up a few headline figures per year and writes a page in French, English and Dutch.
It does not fetch anything: the portal's robots.txt asks automated clients to stay out of its API, so the files are
exported by a person (see `FILES_HELP`) and this step runs offline.

The figures are what was executed (the accounts), not what was voted: the voted budget documents are the
Mairie's own and are not published here. The sums follow simple, stated rules (see `RULES`); they are not an
official analysis and a person has not checked them.

Run by hand: `python -m echo_montolieu budget --from FOLDER`. `render` does not touch these pages.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import disclosure

SIREN = "211102538"
DATASET = "balances-comptables-des-communes-en-{year}"
SOURCE_PAGE = "https://data.economie.gouv.fr/explore/dataset/{dataset}/"
VOTED_2026 = "https://www.montolieu.fr/wp-content/uploads/2026/05/BUDGET-2026.pdf"
FILES_HELP = (f'One JSON file per year named balances-YYYY.json in the folder, each exported from the dataset "{DATASET}" on '
              f'data.economie.gouv.fr with the filter siren = {SIREN} (Export > JSON).')

# What each column adds up. Account numbers are prefixes of the public accounting plan (M14, then M57 from 2024).
RULES = {
    "revenue": dict(prefixes=("70", "73", "74", "75", "76", "77"), exclude=("775", "776", "777"), side="credit"),
    "spending": dict(prefixes=("60", "61", "62", "63", "64", "65", "66", "67"), exclude=("675", "676"), side="debit"),
    "staff": dict(prefixes=("64",), exclude=(), side="debit"),
    "interest": dict(prefixes=("66",), exclude=(), side="debit"),
    "taxes": dict(prefixes=("73",), exclude=(), side="credit"),
    "state": dict(prefixes=("74",), exclude=(), side="credit"),
}
DEBT_PREFIX, DEBT_EXCLUDE = "16", ("165", "1688", "169")
INVEST_PREFIXES = ("20", "21", "23")


def main_budget(rows):
    """Rows of the commune's main budget. Older files mark it budget == "BP" (annexes are "BA"); newer ones cbudg == "1"."""
    keep = []
    for r in rows:
        if r.get("bal") not in (None, "DEF"):
            continue
        if r.get("budget") is not None:
            ok = r["budget"] == "BP"
        else:
            ok = str(r.get("cbudg")) == "1"
        if ok:
            keep.append(r)
    return keep


def _sum(rows, prefixes, exclude, side):
    total = 0.0
    for r in rows:
        account = str(r.get("compte") or "")
        if not account.startswith(prefixes) or (exclude and account.startswith(exclude)):
            continue
        debit, credit = float(r.get("sd") or 0), float(r.get("sc") or 0)
        total += (credit - debit) if side == "credit" else (debit - credit)
    return total


def summarise(rows):
    """Headline figures in whole euros for one year, or None when the year has no rows for the main budget."""
    rows = main_budget(rows)
    if not rows:
        return None
    out = {name: round(_sum(rows, r["prefixes"], r["exclude"], r["side"])) for name, r in RULES.items()}
    out["result"] = out["revenue"] - out["spending"]
    out["investment"] = round(sum(float(r.get("obnetdeb") or 0) - float(r.get("obnetcre") or 0)
                                  for r in rows if str(r.get("compte") or "").startswith(INVEST_PREFIXES)))
    out["debt"] = round(_sum(rows, (DEBT_PREFIX,), DEBT_EXCLUDE, "credit"))
    out["nomenclature"] = sorted({r.get("nomen") for r in rows if r.get("nomen")})[0] if any(r.get("nomen") for r in rows) else None
    return out


def collect(folder):
    """{year: figures} from the files balances-YYYY.json in `folder`; a year without a file, or without rows for the main budget, is left out."""
    found = {}
    for path in sorted(Path(folder).glob("balances-*.json")):
        year = int(path.stem.split("-")[1])
        figures = summarise(json.loads(path.read_text(encoding="utf-8")))
        if figures:
            found[year] = figures
    return found


# ---------------------------------------------------------------- the page

T = {
    "en": dict(
        title="Finances over the years", lead="Montolieu's accounts, year by year",
        intro=("This page adds up the commune's executed accounts for each year from the national open data of the public finance "
               "administration (DGFiP). It shows what was spent and received, not what was voted. The voted budget documents are the Mairie's; "
               "the only one found on its site is the {voted}."),
        voted="2026 budget note (PDF, French)", table1="Running costs and income", table2="Investment and debt",
        year="Year", revenue="Operating income", spending="Operating spending", result="Difference", staff="Of which staff",
        interest="Of which loan interest", taxes="Taxes", state="State grants", investment="Equipment spending", debt="Loans outstanding at year end",
        summary=("From {first} to {last}, operating income went from {r0} to {r1} and operating spending from {s0} to {s1}. "
                 "Loans outstanding went from {d0} to {d1}."),
        how="How the figures are made", caveats="What to keep in mind",
        rules=["Operating income: accounts 70 and 73 to 77, without 775 to 777 (sales of assets and accounting transfers), taxes net of levies.",
               "Operating spending: accounts 60 to 67, without 675 and 676 (accounting transfers). Staff is account 64, interest is account 66.",
               "Equipment spending: money spent in the year on accounts 20, 21 and 23 (studies, buildings, land, works in progress).",
               "Loans outstanding: account 16 at year end, without deposits (165), accrued interest (1688) and 169."],
        notes=["These are the commune's main budget only. Annex budgets (for example the housing lot) are left out.",
               "These are executed accounts, not the voted budget. A year can differ from what the council voted.",
               "The accounting plan changed from M14 to M57 in 2024; the sums above use accounts that exist in both, but a change of a few per cent between 2023 and 2024 can come from that.",
               "Figures are rounded to the euro. Amounts are not adjusted for inflation or for the number of residents.",
               "Made by software from the open data. A person has not checked it: the source is authoritative."],
        source="Source", source_line="Each year is one dataset on data.economie.gouv.fr, \"Balances comptables des communes\", released under the Licence Ouverte 2.0.",
        updated="Fetched {when}.", back="Back to the finance page"),
    "fr": dict(
        title="Les finances au fil des années", lead="Les comptes de Montolieu, année par année",
        intro=("Cette page additionne, pour chaque année, les comptes exécutés de la commune à partir des données ouvertes de la "
               "Direction générale des Finances publiques (DGFiP). Elle montre ce qui a été dépensé et reçu, pas ce qui a été voté. "
               "Les documents budgétaires votés sont ceux de la Mairie ; le seul trouvé sur son site est la {voted}."),
        voted="note de synthèse du budget 2026 (PDF)", table1="Fonctionnement", table2="Investissement et dette",
        year="Année", revenue="Recettes de fonctionnement", spending="Dépenses de fonctionnement", result="Différence", staff="dont personnel",
        interest="dont intérêts des emprunts", taxes="Impôts et taxes", state="Dotations de l’État", investment="Dépenses d’équipement", debt="Emprunts restant dus en fin d’année",
        summary=("De {first} à {last}, les recettes de fonctionnement sont passées de {r0} à {r1} et les dépenses de fonctionnement de {s0} à {s1}. "
                 "Les emprunts restant dus sont passés de {d0} à {d1}."),
        how="Comment les chiffres sont calculés", caveats="À garder en tête",
        rules=["Recettes de fonctionnement : comptes 70 et 73 à 77, sans 775 à 777 (cessions et opérations d’ordre), impôts nets des prélèvements.",
               "Dépenses de fonctionnement : comptes 60 à 67, sans 675 et 676 (opérations d’ordre). Le personnel est le compte 64, les intérêts le compte 66.",
               "Dépenses d’équipement : sommes dépensées dans l’année sur les comptes 20, 21 et 23 (études, bâtiments, terrains, travaux en cours).",
               "Emprunts restant dus : compte 16 en fin d’année, sans les dépôts (165), les intérêts courus (1688) et le 169."],
        notes=["Il s’agit du budget principal de la commune seulement. Les budgets annexes (par exemple le lotissement) sont exclus.",
               "Ce sont les comptes exécutés, pas le budget voté. Une année peut différer de ce que le conseil a voté.",
               "La nomenclature comptable est passée de M14 à M57 en 2024 ; les sommes utilisent des comptes présents dans les deux, mais un écart de quelques pour cent entre 2023 et 2024 peut venir de là.",
               "Les chiffres sont arrondis à l’euro. Les montants ne sont corrigés ni de l’inflation ni du nombre d’habitants.",
               "Page produite par un logiciel à partir des données ouvertes. Aucune personne ne l’a vérifiée : la source fait foi."],
        source="Source", source_line="Chaque année est un jeu de données sur data.economie.gouv.fr, « Balances comptables des communes », sous Licence Ouverte 2.0.",
        updated="Données récupérées le {when}.", back="Retour à la page Finances"),
    "nl": dict(
        title="De financiën door de jaren heen", lead="De rekeningen van Montolieu, jaar na jaar",
        intro=("Deze pagina telt per jaar de uitgevoerde rekeningen van de gemeente op, uit de open data van de Franse "
               "overheidsfinanciën (DGFiP). Ze toont wat is uitgegeven en ontvangen, niet wat is goedgekeurd. "
               "De goedgekeurde begrotingsstukken zijn die van het gemeentehuis; het enige dat op de site staat is de {voted}."),
        voted="samenvattende nota bij de begroting 2026 (pdf, Frans)", table1="Lopende kosten en inkomsten", table2="Investeringen en schuld",
        year="Jaar", revenue="Inkomsten uit de werking", spending="Uitgaven voor de werking", result="Verschil", staff="waarvan personeel",
        interest="waarvan rente op leningen", taxes="Belastingen", state="Bijdragen van de staat", investment="Uitgaven voor uitrusting", debt="Openstaande leningen aan het einde van het jaar",
        summary=("Van {first} tot {last} gingen de inkomsten uit de werking van {r0} naar {r1} en de uitgaven voor de werking van {s0} naar {s1}. "
                 "De openstaande leningen gingen van {d0} naar {d1}."),
        how="Hoe de cijfers worden berekend", caveats="Houd rekening met",
        rules=["Inkomsten uit de werking: rekeningen 70 en 73 tot 77, zonder 775 tot 777 (verkoop van bezit en boekhoudkundige overdrachten), belastingen na heffingen.",
               "Uitgaven voor de werking: rekeningen 60 tot 67, zonder 675 en 676 (boekhoudkundige overdrachten). Personeel is rekening 64, rente is rekening 66.",
               "Uitgaven voor uitrusting: in het jaar uitgegeven bedragen op rekeningen 20, 21 en 23 (studies, gebouwen, grond, lopende werken).",
               "Openstaande leningen: rekening 16 aan het einde van het jaar, zonder waarborgen (165), opgelopen rente (1688) en 169."],
        notes=["Dit is alleen de hoofdbegroting van de gemeente. Bijbegrotingen (bijvoorbeeld de verkaveling) zijn weggelaten.",
               "Dit zijn uitgevoerde rekeningen, niet de goedgekeurde begroting. Een jaar kan afwijken van wat de raad heeft goedgekeurd.",
               "Het rekeningstelsel veranderde in 2024 van M14 naar M57; de sommen gebruiken rekeningen die in beide bestaan, maar een verschil van enkele procenten tussen 2023 en 2024 kan daardoor komen.",
               "Cijfers zijn afgerond op de euro. Bedragen zijn niet gecorrigeerd voor inflatie of aantal inwoners.",
               "Gemaakt door software uit de open data. Een persoon heeft het niet gecontroleerd: de bron is gezaghebbend."],
        source="Bron", source_line="Elk jaar is één dataset op data.economie.gouv.fr, \"Balances comptables des communes\", onder de Licence Ouverte 2.0.",
        updated="Gegevens opgehaald op {when}.", back="Terug naar de pagina Financiën"),
}


def euros(lang, n):
    """1234567 as '1 234 567 €' (fr), '€1,234,567' (en) or '€ 1.234.567' (nl); a minus sign is a real minus."""
    sign, body = ("−" if n < 0 else ""), f"{abs(int(n)):,}"
    if lang == "fr":
        return f"{sign}{body.replace(',', chr(0x202f))} €"
    if lang == "nl":
        return f"{sign}€ {body.replace(',', '.')}"
    return f"{sign}€{body}"


def render(lang, years, fetched):
    t = T[lang]
    ys = sorted(years)
    first, last = ys[0], ys[-1]
    e = lambda n: euros(lang, n)
    voted = f"[{t['voted']}]({VOTED_2026})"
    lines = [f"# {t['title']}", "", disclosure.markdown("rules", lang), "", f"{t['lead']}.", "", t["intro"].format(voted=voted), ""]
    lines += [t["summary"].format(first=first, last=last, r0=e(years[first]["revenue"]), r1=e(years[last]["revenue"]),
                                  s0=e(years[first]["spending"]), s1=e(years[last]["spending"]),
                                  d0=e(years[first]["debt"]), d1=e(years[last]["debt"])), ""]
    cols1 = ("revenue", "spending", "result", "staff", "interest")
    lines += [f"## {t['table1']}", "", "| " + " | ".join([t["year"]] + [t[c] for c in cols1]) + " |", "|" + "---|" * (len(cols1) + 1)]
    lines += [f"| {y} | " + " | ".join(e(years[y][c]) for c in cols1) + " |" for y in reversed(ys)]
    cols2 = ("taxes", "state", "investment", "debt")
    lines += ["", f"## {t['table2']}", "", "| " + " | ".join([t["year"]] + [t[c] for c in cols2]) + " |", "|" + "---|" * (len(cols2) + 1)]
    lines += [f"| {y} | " + " | ".join(e(years[y][c]) for c in cols2) + " |" for y in reversed(ys)]
    lines += ["", f"## {t['how']}", ""] + [f"- {x}" for x in t["rules"]]
    lines += ["", f"## {t['caveats']}", ""] + [f"- {x}" for x in t["notes"]]
    lines += ["", f"## {t['source']}", "", t["source_line"], ""]
    lines += [f"- [{y}]({SOURCE_PAGE.format(dataset=DATASET.format(year=y))})" for y in ys]
    lines += ["", t["updated"].format(when=fetched), "", f"[{t['back']}](index.md)", ""]
    return "\n".join(lines)


def write(public_dir, years, data_file="data/budget_years.json", fetched=None):
    """budget.md (French, the language of the source), budget.en.md and budget.nl.md under public/finance/, and the figures as JSON."""
    fetched = fetched or datetime.now(timezone.utc).date().isoformat()
    target = Path(public_dir) / "finance"
    target.mkdir(parents=True, exist_ok=True)
    for lang, name in (("fr", "budget.md"), ("en", "budget.en.md"), ("nl", "budget.nl.md")):
        page = disclosure.with_front_matter(render(lang, years, fetched), T[lang]["title"])
        if lang == "fr":
            page = page.replace("---\n", "---\nlanguage: fr\n", 1)
        (target / name).write_text(page, encoding="utf-8")
    Path(data_file).parent.mkdir(parents=True, exist_ok=True)
    Path(data_file).write_text(json.dumps({"siren": SIREN, "fetched": fetched, "years": {str(y): v for y, v in sorted(years.items())}},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"years": sorted(years), "pages": 3}


def run(folder, public_dir="public", data_file="data/budget_years.json"):
    years = collect(folder)
    if not years:
        raise SystemExit(f"no rows for SIREN {SIREN} in {folder}. {FILES_HELP}")
    return write(public_dir, years, data_file)
