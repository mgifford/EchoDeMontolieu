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


def render_facts(rec, d, date):
    kinds = Counter(x["kind"] for x in d["decisions"])
    out = [f"# Décisions et votes: {date}", "", disclosure.markdown("rules", "fr"), "",
           "> Lecture automatique et prudente d’un procès-verbal ancien (récupéré sur l’Internet Archive). Seules les phrases qui "
           "annoncent un vote sont gardées, avec la phrase qui les précède. **Tous les noms sont remplacés** (par excès : un nom "
           "de lieu inconnu peut l’être aussi) et les listes de votants sont supprimées. Les ventes de biens privés sont comptées, "
           "pas citées. Le texte fidèle et le PDF original font foi.", "",
           f"- Décisions avec vote repérées : {len(d['decisions'])} "
           f"({kinds.get('unanimous', 0)} à l’unanimité, {kinds.get('majority', 0)} à la majorité, {kinds.get('rejected', 0)} rejetées).",
           f"- Avis de vente de biens privés : {d['sale_notices']} (comptés seulement).", ""]
    if not d["decisions"]:
        out += ["Aucune phrase de vote n’a été reconnue dans ce procès-verbal. Lisez le [texte complet](minutes.md).", ""]
    for n, x in enumerate(d["decisions"], 1):
        link = f"[p.{x['page']}]({x['page_url']})" if x.get("page_url") else f"p.{x['page']}"
        counts = ", ".join(f"{label} {x[k]}" for label, k in (("pour", "for"), ("contre", "against"), ("abstentions", "abstentions")) if x[k])
        out += [f"## Décision {n} ({link})", "", f"“{x['text']}”", "", f"Vote : {KIND_FR[x['kind']]}{' (' + counts + ')' if counts else ''}.", ""]
    return "\n".join(out).rstrip() + "\n"
