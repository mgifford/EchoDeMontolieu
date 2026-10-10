"""Finance, rules and exceptions: what the minutes themselves say, and how rarely they say it.

For every agenda item that involves euro amounts, show side by side:
  * amounts and rates;
  * legal references the text cites (an article, a law, a decree, a budget instruction);
  * wording that points to a rule or limit without citing one ("conformément à", "plafond");
  * exception wording ("à l'exception de", "dérogation", "subvention exceptionnelle"), with the
    accounting categories "charges/produits exceptionnels" removed.
These are co-mentions inside one agenda item. They are NOT a legal analysis: an item that cites
nothing may still have a legal basis, and a citation next to an amount does not prove the amount
follows from it. The page says how rare explicit citations are, so nothing looks more connected
than it is.
"""
import collections
from pathlib import Path

from . import disclosure
from .render import page_link
from .threads import NOTE, slug

CAVEAT = (disclosure.markdown("rules") + "\n>\n> Machine-generated from the minutes' own wording. Co-mentions in one agenda item, not a legal "
          "analysis: an item that cites nothing may still have a legal basis, and a citation next to an amount "
          "does not prove the amount follows from it. Every row links to the original page.")


def _eur(item, limit=4):
    values = [a["value"] for a in item["amounts"] if a["kind"] == "eur"]
    shown = ", ".join(f"{v:,.0f} €".replace(",", " ") for v in values[:limit])
    return shown + (f" (+{len(values) - limit} more)" if len(values) > limit else "")


def _rates(item):
    return ", ".join(f"{a['value']:g} %".replace(".", ",") for a in item["amounts"]
                     if a["kind"] == "pct" and "taux" in a["sentence"].lower())[:60]


def money_rows(meetings):
    rows = []
    for m in meetings:
        for it in m["meeting"]["items"]:
            if it["sensitive"] or not any(a["kind"] == "eur" for a in it["amounts"]):
                continue
            rows.append({"date": m["meeting"]["date"] or "undated", "folder": m["folder"],
                         "url": m["meeting"]["source_url"], "item": it,
                         "refs": it["legal_refs"], "wording": it.get("rule_mentions", []),
                         "exceptions": it["exceptions"]})
    rows.sort(key=lambda r: (r["date"], r["item"]["pages"][0]))
    return rows


def exception_rows(meetings):
    """Items with real exception wording, whether or not they carry a euro amount."""
    return [{"date": m["meeting"]["date"] or "undated", "url": m["meeting"]["source_url"], "item": it}
            for m in meetings for it in m["meeting"]["items"] if not it["sensitive"] and it["exceptions"]]


def basis(row):
    if row["refs"]:
        return "cites: " + "; ".join(dict.fromkeys(r["key"] for r in row["refs"]))[:80]
    if row["wording"]:
        return "rule wording only"
    return "none stated"


def render_finance(meetings, threads_result=None):
    rows, exc = money_rows(meetings), exception_rows(meetings)
    n = len(rows)
    cited = sum(1 for r in rows if r["refs"])
    worded = sum(1 for r in rows if not r["refs"] and r["wording"])
    exceptional = sum(1 for r in rows if r["exceptions"])
    out = ["# Finance, rules and exceptions", "", CAVEAT, "",
           "## How much the minutes say explicitly", "",
           f"- Agenda items with euro amounts: **{n}** (of {sum(len(m['meeting']['items']) for m in meetings)} items in "
           f"{len(meetings)} meetings).",
           f"- Of those, items that **cite a law, article, decree or budget instruction**: **{cited}**.",
           f"- Items with **wording that points to a rule or limit** but no citation: **{worded}**.",
           f"- Items that **say nothing about a rule**: **{n - cited - worded}**.",
           f"- Items with **exception wording**: **{exceptional}** (plus {len(exc) - exceptional} without amounts).", "",
           "The minutes seldom state their legal basis, so most of the picture cannot be read from them. "
           "\"None stated\" below does not mean there is no basis.", ""]

    by_year = collections.defaultdict(list)
    for r in rows:
        by_year[r["date"][:4]].append(r)
    out += ["## Decisions with money, by year", ""]
    for year in sorted(by_year):
        out += [f"### {year}", "", "| Date | Item | Amounts | Rates | Rule basis in the text | Exception wording | Vote | Page |",
                "|---|---|---|---|---|---|---|---|"]
        for r in by_year[year]:
            it = r["item"]
            flag = "yes" if r["exceptions"] else ""
            out.append(f"| {r['date']} | {it['title'][:70]} | {_eur(it)} | {_rates(it)} | {basis(r)} | {flag} | "
                       f"{it['vote_result'] or '-'} | {page_link(r['url'], it['pages'][0])} |")
        out.append("")

    refs = collections.defaultdict(list)
    for r in rows:
        for ref in r["refs"]:
            refs[ref["key"]].append(r)
    out += ["## Rules cited by name", ""]
    if refs:
        out += ["| Reference | Cited in | Items |", "|---|---|---|"]
        for key, rs in sorted(refs.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            where = ", ".join(sorted({f"{r['date']} ({page_link(r['url'], r['item']['pages'][0])})" for r in rs}))[:300]
            out.append(f"| {key} | {len(rs)} | {where} |")
        out += ["", "A reference shown as `?` has no code named near it in the text, so it is not guessed.", ""]
    else:
        out += ["None found.", ""]

    out += ["## Exceptions and exemptions mentioned", ""]
    if exc:
        for r in exc:
            it = r["item"]
            e = it["exceptions"][0]
            extra = []
            if it["legal_refs"]:
                extra.append("cites " + "; ".join(dict.fromkeys(x["key"] for x in it["legal_refs"])))
            if _eur(it):
                extra.append("amounts " + _eur(it))
            out += [f"- **{r['date']}, {it['title'][:80]}** ({page_link(r['url'], it['pages'][0])}) "
                    f"[{e['marker']}]: “{e['sentence'][:260]}”" + (f" ({'; '.join(extra)})" if extra else "")]
        out.append("")
    else:
        out += ["None found.", ""]

    if threads_result:
        money_threads = [t for t in threads_result["threads"] if t["status"] != "one-off"
                         and sum(1 for x in t["members"] if any(a["kind"] == "eur" for a in x["item"]["amounts"])) >= 2]
        out += ["## Recurring money issues: amounts over time", "",
                "Issues that came up in several meetings with amounts each time. Open an issue for its full timeline.", ""]
        for t in money_threads:
            out += [f"### [{t['title'][:90]}](../topics/{slug(t)}.md)", "", "| Date | Amounts |", "|---|---|"]
            out += [f"| {x['date']} | {_eur(x['item'])} |" for x in t["members"] if _eur(x["item"])]
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_finance(public_dir, meetings, threads_result=None):
    target = Path(public_dir) / "finance"
    target.mkdir(parents=True, exist_ok=True)
    body = render_finance(meetings, threads_result)
    if (target / "budget.md").exists():                      # written by `python -m echo_montolieu budget`, from exported open data
        body += "\n## Over the years\n\n[The commune's accounts year by year](budget.md), from the national open data.\n"
    (target / "index.md").write_text(disclosure.with_front_matter(body, "Finance, rules and exceptions"), encoding="utf-8")
    return {"money_items": len(money_rows(meetings)), "exception_items": len(exception_rows(meetings))}
