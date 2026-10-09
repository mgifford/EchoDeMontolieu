"""A cautious digest of the 2003-2008 minutes, recovered from the Internet Archive.

The digest for current minutes (meeting.py) was built for today's layout, where agenda items have
headings. The old minutes are narrative, surnames are written in capitals or lower case, and the
vote lines list who voted how. Run through the current rules, 69 of 107 "items" named a councillor,
and attendance lists became item titles. So this digest keeps less and scrubs more:

- it lists only decisions: each sentence that states a vote, with the sentence before it for context;
- every name is replaced: surnames from the attendance lists of all the old minutes, names after an
  honorific, and any capitalised word that is not an everyday word of the minutes;
- parentheses that only listed voters are dropped, so no one's vote is shown;
- a passage about a property sale is counted, not quoted.

It over-masks on purpose (a place name that is not on the allow-list is masked too). It is software,
not a person's judgement: the faithful minutes next to it remain the authoritative text.
"""
import re
from collections import Counter

from . import disclosure
from .meeting import _HONORIFIC_NAME_ANYCASE
from .privacy import _fold
from .signals import is_property_transaction, parse_votes, sentences

PLACEHOLDER = "[name withheld]"
KIND_FR = {"unanimous": "à l’unanimité", "majority": "à la majorité", "rejected": "rejeté"}
# Capitalised words that are not people: the village, its institutions and the places the minutes name.
ALLOW = {_fold(w) for w in (
    "Montolieu Carcassonne Aude Narbonne Toulouse Lagrasse Saissac Cuxac Cabardes Villegly Mas Cabardès Languedoc Roussillon France "
    "Etat État Préfet Préfecture Sous-Préfecture Trésor Public Département Région Communauté Communes Mairie Conseil Municipal "
    "Maire Adjoint Monsieur Madame Mademoiselle Mesdames Messieurs Mme Mmes Mr Mrs MM Mlle Commission Syndicat SIVOM SIAEP SDIS "
    "EDF GDF France Télécom Telecom Poste DDE DDA DRAC ABF POS PLU ZPPAUP TVA CCAS CGCT SMICTOM Piscine Halle Eglise Église "
    "Janvier Février Mars Avril Mai Juin Juillet Août Aout Septembre Octobre Novembre Décembre Lundi Mardi Mercredi Jeudi Vendredi Samedi Dimanche "
    "Euros Euro Article Articles Loi Décret Arrêté Code Budget Compte Administratif Gestion Primitif Supplémentaire Questions Diverses "
    "Unanimité Voix Contre Pour Abstention Abstentions Proposition Délibération Ordre Jour").split()}
_COMMON_MIN_COUNT = 3
_HONORIFIC_MES = re.compile(r"\bMes\s+[A-ZÀ-Ý][\wÀ-ÿ’'\-]+(?:\s*[‘’',]\s*[A-ZÀ-Ý][\wÀ-ÿ’'\-]+)*(?:\s+et\s+[A-ZÀ-Ý][\wÀ-ÿ’'\-]+)?")
_ATTENDANCE = re.compile(r"pr[ée]sents?\s*:?(.{0,700}?)"
                         r"(?=secr[ée]tariat|secr[ée]taire|ordre du jour|monsieur le maire|la s[ée]ance|$)", re.I | re.S)
_WORD = re.compile(r"[A-Za-zÀ-ÿ][\wÀ-ÿ’'\-]*")
_PLACEHOLDER_ONLY_PARENS = re.compile(r"\(\s*(?:\[name withheld\][\s,.;et\-]*|\b[a-z]\.\s*)+\)")
_FILLER = {_fold(w) for w in "présents présent absents absent excusés excusé excusée procuration procurations à au de du des et la le les par pour contre abstention secrétaire mme mmes mr mrs mlle monsieur madame mademoiselle mesdames messieurs".split()}


class Vocabulary:
    """What the old minutes' text itself says is a name: attendance-list words (roster) and everyday words (common)."""

    def __init__(self, records):
        lower, blocks = Counter(), []
        for rec in records:
            flat = " ".join(" ".join((p.get("text") or "") for p in rec["pages"]).split())
            for w in _WORD.findall(flat):
                if w.islower():
                    lower[_fold(w)] += 1
            m = _ATTENDANCE.search(flat[:4000])
            if m:
                blocks.append(m.group(1))
        common = {w for w, n in lower.items() if n >= _COMMON_MIN_COUNT}
        roster = set()
        for block in blocks:        # the first attendance list of each meeting: capitalised words are surnames and first names
            for w in _WORD.findall(block):
                f = _fold(w)
                if w[0].isupper() and len(f) >= 3 and f not in _FILLER and f not in ALLOW and f not in common:
                    roster.add(f)
        self.roster = roster
        self.common = common
        self._rx = re.compile(r"(?<![\wÀ-ÿ])(" + "|".join(sorted(map(re.escape, roster), key=len, reverse=True)) + r")(?![\wÀ-ÿ])", re.I) if roster else None

    def scrub(self, sentence):
        s = _HONORIFIC_MES.sub(PLACEHOLDER, sentence)
        s = _HONORIFIC_NAME_ANYCASE.sub(lambda m: m.group(0).split()[0] + " " + PLACEHOLDER, s)
        if self._rx:        # match on the accent-folded text (same length), replace in the original
            folded, out, last = _fold(s), [], 0
            for m in self._rx.finditer(folded):
                out += [s[last:m.start()], PLACEHOLDER]
                last = m.end()
            s = "".join(out) + s[last:]

        def residual(m):
            w, start = m.group(0), m.start()
            f = _fold(w)
            if w == PLACEHOLDER or f in ALLOW or f in self.common or not w[0].isupper():
                return w
            before = s[:start].rstrip()
            if not before or before[-1] in ".!?:;«“\"(":      # sentence start: capitalised for grammar, not as a name
                return w if f in self.common or len(f) < 3 else w
            return PLACEHOLDER
        s = _WORD.sub(residual, s)
        s = re.sub(r"(?:\[name withheld\][\s,;.\-]*(?:et\s+)?){2,}", PLACEHOLDER + " ", s)
        s = _PLACEHOLDER_ONLY_PARENS.sub("", s)
        s = re.sub(r"\(\s*\)", "", s)
        return re.sub(r"\s+", " ", s).replace(" ,", ",").replace(" .", ".").strip()


def _tail(text, n):
    """The last `n` characters, from a word boundary."""
    return text if len(text) <= n else "… " + text[-n:].split(" ", 1)[-1]


def _head(text, n):
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


def digest(rec, vocab):
    """{"decisions": [{page, text, kind, for, against, abstentions}], "sale_notices": n} for one archived record."""
    decisions, sales = [], 0
    for pg in rec["pages"]:
        text = pg.get("text") or ""
        if not text.strip():
            continue
        sents = sentences(text)
        votes = parse_votes(text)["votes"]
        wanted = {v["sentence"] for v in votes}
        for i, s in enumerate(sents):
            if s not in wanted:
                continue
            v = next(v for v in votes if v["sentence"] == s)
            context = sents[i - 1] if i else ""
            if is_property_transaction("", context + " " + s):
                sales += 1
                continue
            decisions.append({"page": pg["page"], "page_url": pg.get("page_url"), "kind": v["kind"], "for": v["for"],
                              "against": v["against"], "abstentions": v["abstentions"],
                              "text": " ".join(x for x in (_tail(vocab.scrub(context), 220), _head(vocab.scrub(s), 420)) if x)})
    return {"decisions": decisions, "sale_notices": sales}


# The page's own words, in each language. The quoted sentences are always French (the minutes' language) until a
# model translates them; the labels around them are fixed text, written once here.
LABELS = {
    "fr": {
        "title": "Décisions et votes: {date}", "note": "Lecture automatique et prudente d’un procès-verbal ancien (récupéré sur l’Internet Archive). Seules les phrases qui annoncent un vote sont gardées, avec la phrase qui les précède. **Tous les noms sont remplacés** (par excès : un nom de lieu inconnu peut l’être aussi) et les listes de votants sont supprimées. Les ventes de biens privés sont comptées, pas citées. Le texte fidèle et le PDF original font foi.",
        "found": "Décisions avec vote repérées : {n} ({u} à l’unanimité, {m} à la majorité, {r} rejetées).",
        "sales": "Avis de vente de biens privés : {n} (comptés seulement).",
        "none": "Aucune phrase de vote n’a été reconnue dans ce procès-verbal. Lisez le [texte complet](minutes.md).",
        "decision": "Décision {n}", "vote": "Vote", "for": "pour", "against": "contre", "abstentions": "abstentions",
        "kind": {"unanimous": "à l’unanimité", "majority": "à la majorité", "rejected": "rejeté"}, "quote": "",
        "tr": "", "orig": "", "note_tr": ""},
    "en": {
        "title": "Decisions and votes: {date}", "note": "Cautious automatic reading of an old set of minutes (recovered from the Internet Archive). Only sentences that state a vote are kept, with the sentence before. **All names are replaced** (more than strictly needed, on purpose: an unfamiliar place name may be replaced too) and lists of voters are removed. Private property sales are counted, not quoted. **The quoted sentences are in French, the language of the minutes, and are not translated yet.** The full French text and the original PDF are authoritative.",
        "found": "Votes found: {n} ({u} unanimous, {m} by majority, {r} rejected).",
        "sales": "Private property sale notices: {n} (counted only).",
        "none": "No vote sentence was recognised in these minutes. Read the [full text](minutes.md) (in French).",
        "decision": "Decision {n}", "vote": "Vote", "for": "for", "against": "against", "abstentions": "abstentions",
        "kind": {"unanimous": "unanimous", "majority": "by majority", "rejected": "rejected"}, "quote": "French text:",
        "tr": "Machine translation:", "orig": "French original:",
        "note_tr": "Cautious automatic reading of an old set of minutes (recovered from the Internet Archive). Only sentences that state a vote are kept, with the sentence before. **All names are replaced** (more than strictly needed, on purpose) and lists of voters are removed. Private property sales are counted, not quoted. **The quoted sentences were machine-translated from the French, which is shown under each one; the French is authoritative.** The original PDF is authoritative too."},
    "nl": {
        "title": "Besluiten en stemmingen: {date}", "note": "Voorzichtige automatische lezing van oude notulen (teruggevonden in het Internet Archive). Alleen zinnen die een stemming vermelden zijn bewaard, met de zin ervoor. **Alle namen zijn vervangen** (bewust meer dan strikt nodig: ook een onbekende plaatsnaam kan vervangen zijn) en lijsten van stemmers zijn verwijderd. Verkopen van particuliere panden worden geteld, niet geciteerd. **De geciteerde zinnen staan in het Frans, de taal van de notulen, en zijn nog niet vertaald.** De volledige Franse tekst en de originele pdf zijn leidend.",
        "found": "Gevonden stemmingen: {n} ({u} unaniem, {m} bij meerderheid, {r} verworpen).",
        "sales": "Meldingen van verkoop van particuliere panden: {n} (alleen geteld).",
        "none": "In deze notulen is geen zin met een stemming herkend. Lees de [volledige tekst](minutes.md) (in het Frans).",
        "decision": "Besluit {n}", "vote": "Stemming", "for": "voor", "against": "tegen", "abstentions": "onthoudingen",
        "kind": {"unanimous": "unaniem", "majority": "bij meerderheid", "rejected": "verworpen"}, "quote": "Franse tekst:",
        "tr": "Machinevertaling:", "orig": "Frans origineel:",
        "note_tr": "Voorzichtige automatische lezing van oude notulen (teruggevonden in het Internet Archive). Alleen zinnen die een stemming vermelden zijn bewaard, met de zin ervoor. **Alle namen zijn vervangen** (bewust meer dan strikt nodig) en lijsten van stemmers zijn verwijderd. Verkopen van particuliere panden worden geteld, niet geciteerd. **De geciteerde zinnen zijn machinaal uit het Frans vertaald; het Frans staat eronder en is leidend.** De originele pdf is ook leidend."},
}


def facts_sha(rec, d, date):
    """Fingerprint of the French page: a translation made from different French is stale."""
    import hashlib
    return hashlib.sha256(render_facts(rec, d, date, "fr").encode("utf-8")).hexdigest()


def render_facts(rec, d, date, lang="fr", translated=None, model=None):
    """The decisions page. `translated` maps a decision's index to (text, ok) when a model translated the quotes."""
    L = LABELS[lang]
    kinds = Counter(x["kind"] for x in d["decisions"])
    note = L["note_tr"] if translated is not None else L["note"]
    kind = "translation" if translated is not None else "rules"
    out = [f"# {L['title'].format(date=date)}", "", disclosure.markdown(kind, lang, model), "", f"> {note}", "",
           f"- {L['found'].format(n=len(d['decisions']), u=kinds.get('unanimous', 0), m=kinds.get('majority', 0), r=kinds.get('rejected', 0))}",
           f"- {L['sales'].format(n=d['sale_notices'])}", ""]
    if not d["decisions"]:
        out += [L["none"], ""]
    for n, x in enumerate(d["decisions"], 1):
        link = f"[p.{x['page']}]({x['page_url']})" if x.get("page_url") else f"p.{x['page']}"
        counts = ", ".join(f"{L[label]} {x[k]}" for label, k in (("for", "for"), ("against", "against"), ("abstentions", "abstentions")) if x[k])
        out += [f"## {L['decision'].format(n=n)} ({link})", ""]
        got = translated.get(n - 1) if translated is not None else None
        if got and got[1]:
            out += [f"{L['tr']} “{got[0]}”", "", f"{L['orig']} “{x['text']}”", ""]
        else:
            out += [f"{L['quote']} “{x['text']}”".strip(), ""]
        out += [f"{L['vote']}: {L['kind'][x['kind']]}{' (' + counts + ')' if counts else ''}.", ""]
    return "\n".join(out).rstrip() + "\n"


def place_meetings(public_dir):
    """The recovered minutes as pseudo-meetings, so their street and lieu-dit mentions can be geocoded like the rest.

    One pseudo-item per page that names a place. A sentence about a property sale, and the sentence on each side of it,
    is skipped; names from the attendance lists and after honorifics are replaced first, and a candidate that still
    holds a replaced name is dropped. Only the place label is kept: no text of the minutes goes into the item."""
    import json
    from pathlib import Path

    from .render import meeting_folder
    from .signals import find_place_candidates
    public = Path(public_dir)
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    entries = sorted(index["documents"], key=lambda d: ((d["meeting_date"] or {}).get("value") or "", d["filename"] or ""))
    records, taken = [], set()
    for entry in entries:
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        folder = meeting_folder(rec, taken)          # computed for every record so folder names match render_all
        if rec.get("origin"):
            records.append((folder, rec))
    vocab = Vocabulary([r for _, r in records])
    out = []
    for folder, rec in records:
        date = (rec.get("meeting_date") or {}).get("value")
        items = []
        for pg in rec["pages"]:
            sents = sentences(pg.get("text") or "")
            sale = {j for i, s in enumerate(sents) if is_property_transaction("", s) for j in (i - 1, i, i + 1)}
            labels = []
            for i, s in enumerate(sents):
                if i in sale:
                    continue
                masked = _HONORIFIC_NAME_ANYCASE.sub(lambda m: m.group(0).split()[0] + " " + PLACEHOLDER, s)
                if vocab._rx:
                    folded, parts, last = _fold(masked), [], 0
                    for m in vocab._rx.finditer(folded):
                        parts += [masked[last:m.start()], PLACEHOLDER]
                        last = m.end()
                    masked = "".join(parts) + masked[last:]
                labels += [c for c in find_place_candidates(masked) if PLACEHOLDER not in c["label"]]
            if labels:
                items.append({"id": f"{rec['document_id']}-p{pg['page']}", "sensitive": False, "title": f"Mentioned in the minutes of {date}",
                              "title_key": "", "pages": [pg["page"], pg["page"]], "topics": [], "places": labels})
        if items:
            out.append({"meeting": {"date": date, "source_url": rec["source_url"], "items": items}, "folder": folder, "name_tokens": set()})
    return out
