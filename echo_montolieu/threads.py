"""Issues over time: link agenda items across meetings and show how each one evolves.

Items are linked when their words overlap (tf-idf cosine similarity over the scrubbed text,
with names and civic boilerplate removed). That is a heuristic: a grouping is a suggestion,
shown with the words that caused it, never a fact. Routine items (approval of the previous
minutes, notices of private property sales) are kept apart as "standing items". Budget-table
captions are ignored.

"Possibly dropped" means only this: the last time an issue appears it carries a postponement or
a plan, and it does not appear again in the meetings that followed. It does not mean it was
forgotten; the discussion may have continued under another title.
"""
import collections
import json
import math
import re
from pathlib import Path

from . import disclosure
from .meeting import known_names, parse_meeting
from .privacy import _fold
from .render import meeting_folder, page_link

LINK_THRESHOLD = 0.30
MIN_MEETINGS_AFTER = 2          # an issue is only "possibly dropped" if this many meetings followed

STOP = set("""avec dans pour cette cela ainsi alors donc leur leurs elles nous vous sont sera seront etre avoir fait faire font
plus moins tout tous toute toutes entre depuis comme aussi autre autres meme celui celle ceux sans sous sur vers lors dont ils
elle ont ete etait etaient peut doit doivent faut quand lorsque tres bien encore notamment suite afin cet ces son ses mais car puis
ensuite apres avant pendant selon chez lui eux soit voir pas non oui""".split())
CIVIC = set("""conseil conseils municipal municipale commune communes maire monsieur madame mairie vote votes unanimite majorite
abstention deliberation seance point points propose proposition propos approuve approuver valide valider decide decider autorise
autoriser euros euro conseiller conseillere adjoint adjointe presente presenter membres delegue signature article demande demandes
dossier question informe indique precise explique rappelle""".split())
STANDING = re.compile(r"approbation|proces verbal|questions diverses|informations diverses|droit.? preemption|preemption")
TABLE_TITLE = re.compile(r"fonctionnement|investissement|recettes|depenses|section|total|budget (?:general|ccas|lotissement|groupe)")


ACRONYM_WEIGHT = 3
NOT_ACRONYMS = {"HT", "TTC", "TVA", "PDF", "EUR", "DIA"}


def item_terms(item, name_tokens):
    text = f"{item['title']} {item['title']} {item['text']}"
    counts = collections.Counter()
    for token in re.findall(r"[a-z]{4,}", _fold(text)):
        token = token[:-1] if token.endswith("s") and len(token) > 5 else token
        if token not in STOP and token not in CIVIC and token not in name_tokens:
            counts[token] += 1
    # Short ALL-CAPS acronyms (PLU, CCID, CLECT) are the best markers of a subject and are
    # three letters or fewer, so the word filter above would drop them.
    for acronym in re.findall(r"\b[A-Z]{3,6}\b", f"{item['title']} {item['text']}"):
        token = _fold(acronym)
        if acronym not in NOT_ACRONYMS and token not in name_tokens and token not in CIVIC:
            counts[token] += ACRONYM_WEIGHT
    return counts


RARE_ACRONYM_DF = 12      # an acronym in at most this many items marks a subject, not boilerplate
ACRONYM_MIN_COUNT = 2


def item_acronyms(item, name_tokens):
    """{acronym: occurrences in the text} and the set found in the title."""
    found = collections.Counter()
    for a in re.findall(r"\b[A-Z]{3,6}\b", item["text"] + " " + item["title"]):
        token = _fold(a)
        if a not in NOT_ACRONYMS and token not in name_tokens and token not in CIVIC:
            found[token] += 1
    in_title = {_fold(a) for a in re.findall(r"\b[A-Z]{3,6}\b", item["title"])}
    return found, in_title


def is_table_item(item):
    text = item["text"]
    if not text:
        return False
    digits = sum(c.isdigit() for c in text) / max(len(text), 1)
    return digits > 0.12 or (bool(TABLE_TITLE.search(item["title_key"])) and len(text) < 600)


def load_meetings(public_dir):
    """Parsed meetings, oldest first, each with the name tokens to keep out of the vocabulary."""
    public = Path(public_dir)
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    taken, out = set(), []
    entries = sorted(index["documents"], key=lambda d: ((d["meeting_date"] or {}).get("value") or "", d["filename"] or ""))
    for entry in entries:
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        folder = meeting_folder(rec, taken)       # computed for every record so folder names match render_all
        if rec.get("origin"):
            continue                              # archived minutes have no digest yet (see render_all)
        meeting = parse_meeting(rec)
        tokens = {t for n in known_names(rec) for t in re.findall(r"[a-z]{3,}", _fold(n))}
        out.append({"meeting": meeting, "folder": folder, "name_tokens": tokens})
    out.sort(key=lambda m: m["meeting"]["date"] or "")
    return out


def _cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def build_threads(meetings):
    """Threads of linked items. Returns {"threads": [...], "standing": [...], "meeting_dates": [...]}."""
    dates = [m["meeting"]["date"] or "undated" for m in meetings]
    rows = []        # one per linkable item
    standing = collections.defaultdict(list)
    for m in meetings:
        meeting, folder = m["meeting"], m["folder"]
        for item in meeting["items"]:
            entry = {"date": meeting["date"] or "undated", "folder": folder, "item": item,
                     "url": meeting["source_url"]}
            if item["sensitive"] or STANDING.search(item["title_key"]):
                standing["Notices of private property sales (counts only)" if item["sensitive"]
                         else "Approval of the previous minutes and routine items"].append(entry)
            elif item["text"] and not is_table_item(item):
                entry["terms"] = item_terms(item, m["name_tokens"])
                entry["acronyms"], entry["title_acronyms"] = item_acronyms(item, m["name_tokens"])
                rows.append(entry)
    df = collections.Counter(t for r in rows for t in r["terms"])
    n = len(rows)
    idf = {t: math.log((n + 1) / (d + 0.5)) for t, d in df.items()}
    for r in rows:
        v = {t: (1 + math.log(c)) * idf[t] for t, c in r["terms"].items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        r["vec"] = {t: x / norm for t, x in v.items()}
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    acronym_df = collections.Counter(a for r in rows for a in r["acronyms"])

    def share_rare_acronym(a, b):
        return any(acronym_df[x] <= RARE_ACRONYM_DF and a["acronyms"][x] >= ACRONYM_MIN_COUNT
                   and b["acronyms"].get(x, 0) >= ACRONYM_MIN_COUNT
                   and (x in a["title_acronyms"] or x in b["title_acronyms"]) for x in a["acronyms"])

    for i in range(n):
        for j in range(i + 1, n):
            if rows[i]["date"] == rows[j]["date"]:
                continue
            if _cosine(rows[i]["vec"], rows[j]["vec"]) >= LINK_THRESHOLD or share_rare_acronym(rows[i], rows[j]):
                parent[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(rows[i])

    threads = []
    for members in groups.values():
        members.sort(key=lambda r: (r["date"], r["item"]["pages"][0]))
        weight = collections.Counter()
        for r in members:
            for t, x in r["vec"].items():
                weight[t] += x
        label_terms = [t for t, _ in weight.most_common(4)]
        meeting_dates = sorted({r["date"] for r in members})
        last = members[-1]
        later = [d for d in dates if d > meeting_dates[-1]]
        stalled = [f for f in last["item"]["followups"] if f["type"] == "deferred"]
        threads.append({
            "label_terms": label_terms, "title": members[0]["item"]["title"], "members": members,
            "meetings": meeting_dates, "n_meetings": len(meeting_dates),
            "status": "recurring" if len(meeting_dates) >= 3 else "returned" if len(meeting_dates) == 2 else "one-off",
            "possibly_dropped": bool(stalled) and len(later) >= MIN_MEETINGS_AFTER,
            "pending": stalled[:2], "later_meetings": len(later),
        })
    threads.sort(key=lambda t: (-t["n_meetings"], t["meetings"][0]))
    return {"threads": threads, "standing": dict(standing), "meeting_dates": dates}


def slug(thread):
    return re.sub(r"[^a-z0-9]+", "-", "-".join(thread["label_terms"][:3])).strip("-") + "-" + thread["meetings"][0]


def todo_status(result):
    """{item id: note} for the to-do files: where an issue came back, or that it did not."""
    status = {}
    for t in result["threads"]:
        for i, r in enumerate(t["members"]):
            if not r["item"]["followups"]:
                continue
            later = sorted({x["date"] for x in t["members"][i + 1:] if x["date"] > r["date"]})
            if later:
                status[r["item"]["id"]] = "the issue comes back on " + ", ".join(later)
            else:
                after = sum(1 for d in result["meeting_dates"] if d > r["date"])
                status[r["item"]["id"]] = (
                    f"no later mention found in the {after} meeting(s) that followed (heuristic: it may continue "
                    "under another title)" if after else "this is the most recent meeting")
    return status


# ---- Markdown -------------------------------------------------------------------------------

NOTE = (disclosure.markdown("rules") + "\n>\n> Machine-generated grouping. Items are linked because they share distinctive words, and the words are "
        "shown so you can judge. A grouping can be wrong, and a missing link does not mean there is none. "
        "Every entry links to the page of the original PDF.")


def _eur(item):
    return ", ".join(f"{a['value']:,.0f} €".replace(",", " ") for a in item["amounts"] if a["kind"] == "eur")[:120]


def render_thread(t):
    out = [f"# {t['title']}", "", NOTE, "",
           f"- **Status:** {t['status']} ({t['n_meetings']} meetings, {t['meetings'][0]} to {t['meetings'][-1]})",
           f"- **Linked by shared words:** {', '.join(t['label_terms'])}"]
    if t["possibly_dropped"]:
        out.append(f"- **Possibly dropped:** the last mention carries a postponement or plan and the issue does not "
                   f"appear in the {t['later_meetings']} meeting(s) that followed. This is a heuristic.")
    out += ["", "## Timeline", ""]
    for r in t["members"]:
        it = r["item"]
        vote = it["vote_result"] or "no vote found"
        out += [f"### {r['date']}: {it['title']}", "",
                f"{page_link(r['url'], it['pages'][0])} · vote: {vote} · [facts](../meetings/{r['folder']}/facts.md)"
                + (f" · amounts: {_eur(it)}" if _eur(it) else ""), ""]
        if it["snippet"]:
            out += [f"> {it['snippet']}", ""]
        for f in it["followups"][:2]:
            out.append(f"- Follow-up ({f['type']}): “{f['sentence'][:220]}”")
        if it["followups"]:
            out.append("")
    amounts = [(r["date"], _eur(r["item"])) for r in t["members"] if _eur(r["item"])]
    if len(amounts) >= 2:
        out += ["## Amounts across meetings", "", "| Date | Amounts mentioned |", "|---|---|"] + \
               [f"| {d} | {a} |" for d, a in amounts] + [""]
    return "\n".join(out).rstrip() + "\n"


def render_themes(meetings):
    """Items per theme per quarter, from the item topics."""
    def quarter(date):
        return f"{date[:4]}-Q{(int(date[5:7]) - 1) // 3 + 1}" if date and len(date) >= 7 else "undated"
    counts = collections.defaultdict(collections.Counter)
    totals = collections.Counter()
    for m in meetings:
        q = quarter(m["meeting"]["date"])
        for it in m["meeting"]["items"]:
            totals[q] += 1
            for topic in it["topics"]:
                counts[topic][q] += 1
    quarters = sorted(totals)
    out = ["# Themes over time", "", NOTE, "",
           "Number of agenda items per theme and quarter. An item can have up to three themes, so rows "
           "do not add up to the total. Themes are found by keywords in the title and text.", "",
           "| Theme | " + " | ".join(quarters) + " | Total |", "|---|" + "---|" * (len(quarters) + 1)]
    for topic, c in sorted(counts.items(), key=lambda kv: -sum(kv[1].values())):
        out.append(f"| {topic} | " + " | ".join(str(c.get(q, "")) for q in quarters) + f" | {sum(c.values())} |")
    out.append("| **All items** | " + " | ".join(str(totals[q]) for q in quarters) + f" | {sum(totals.values())} |")
    return "\n".join(out) + "\n"


def render_index(result, meetings):
    threads, standing = result["threads"], result["standing"]
    recurring = [t for t in threads if t["status"] in ("recurring", "returned")]
    out = ["# Issues over time", "", NOTE, "",
           f"{len(recurring)} issues came up in more than one of the {len(result['meeting_dates'])} meetings "
           f"({sum(t['n_meetings'] for t in recurring) and len([t for t in recurring if t['status'] == 'recurring'])} "
           "in three or more). See also [themes over time](themes.md).", "",
           "## Recurring issues", "", "| Issue | Meetings | First | Last | Linked by |", "|---|---|---|---|---|"]
    for t in recurring:
        out.append(f"| [{t['title']}]({slug(t)}.md) | {t['n_meetings']} | {t['meetings'][0]} | {t['meetings'][-1]} | {', '.join(t['label_terms'][:3])} |")
    dropped = [t for t in threads if t["possibly_dropped"]]
    out += ["", "## Possibly dropped", "",
            "The last mention carries a postponement or a plan and the issue does not appear again in the meetings "
            "that followed. A heuristic, not a finding: it may have continued under another title.", ""]
    if dropped:
        out += ["| Issue | Last mentioned | Pending wording | Meetings since |", "|---|---|---|---|"]
        for t in dropped:
            last = t["members"][-1]
            f = t["pending"][0]
            link = f"[{t['title']}]({slug(t)}.md)" if t["n_meetings"] > 1 else t["title"]
            out.append(f"| {link} | {t['meetings'][-1]} ({page_link(last['url'], last['item']['pages'][0])}) | “{f['sentence'][:120]}” | {t['later_meetings']} |")
    else:
        out.append("None found.")
    out += ["", "## Standing items", "", "These come back in most meetings by nature, so they are not treated as issues.", ""]
    for name, rows in standing.items():
        out.append(f"- {name}: {len(rows)} items in {len({r['date'] for r in rows})} meetings")
    singles = [t for t in threads if t["status"] == "one-off"]
    out += ["", f"{len(singles)} further items appeared in a single meeting only.", ""]
    return "\n".join(out)


def write_topics(public_dir, result, meetings):
    topics = Path(public_dir) / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    keep = {"index.md", "themes.md"}
    for t in result["threads"]:
        if t["status"] != "one-off":
            (topics / f"{slug(t)}.md").write_text(disclosure.with_front_matter(render_thread(t), t["title"].replace('"', "'")), encoding="utf-8")
            keep.add(f"{slug(t)}.md")
    (topics / "index.md").write_text(disclosure.with_front_matter(render_index(result, meetings), "Issues over time"), encoding="utf-8")
    (topics / "themes.md").write_text(disclosure.with_front_matter(render_themes(meetings), "Themes over time"), encoding="utf-8")
    for old in topics.glob("*.md"):
        if old.name not in keep:
            old.unlink()          # the folder is generated: drop pages for groupings that no longer exist
    return len(keep) - 2
