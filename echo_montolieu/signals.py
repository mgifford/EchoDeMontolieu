"""Rule-based signals found in the text of a council item.

Everything here is a heuristic over French municipal minutes: a regular
expression decides, and the matching sentence is kept as evidence so a reader can
check it. Nothing is inferred beyond what the words say. Results are candidates,
not facts.
"""
import re

NUMBER_WORDS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
                "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12}
_NUM = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"


_ABBREVIATIONS = {"m", "mm", "mme", "mmes", "mlle", "dr", "pr", "st", "ste", "art", "n", "cf", "etc", "vs"}


def sentences(text):
    """Rough sentence split that does not break after "M.", "Mme." or an initial.

    Good enough to quote evidence; not linguistics.
    """
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý«“\"])", " ".join(text.split()))
    merged = []
    for part in parts:
        if merged:
            last = merged[-1].rstrip(".").split(" ")[-1]
            if merged[-1].endswith(".") and (last.lower() in _ABBREVIATIONS
                                             or (len(last) == 1 and last.isupper())):
                merged[-1] += " " + part
                continue
        merged.append(part)
    return [m.strip() for m in merged if m.strip()]


def _to_int(token):
    token = token.lower()
    return int(token) if token.isdigit() else NUMBER_WORDS.get(token)


# ---- votes ----------------------------------------------------------------------------

_UNANIMITY = re.compile(r"à l[’']unanimité", re.I)
_MAJORITY = re.compile(r"à la majorité", re.I)
_FOR = re.compile(_NUM + r"\s+voix\s+pour", re.I)
_AGAINST = re.compile(_NUM + r"\s+(?:voix\s+)?contre|contre\s*:\s*" + _NUM, re.I)
_ABSTAIN_N = re.compile(_NUM + r"\s+abstentions?|abstentions?\s*:\s*" + _NUM, re.I)
_ABSTAINS = re.compile(r"s[’']abstien(?:t|nent)", re.I)
_NO_PART = re.compile(r"ne prend(?:nent)? pas part au vote", re.I)
_REJECT = re.compile(r"(?:est|sont) rejet[ée]e?s?|le conseil (?:refuse|rejette)", re.I)
_VOTE_WORD = re.compile(r"\bvote|unanimit|majorité|voix|abstien|abstention|s’oppose|se prononce", re.I)


def _count(pattern, text):
    total = 0
    for m in pattern.finditer(text):
        token = next((g for g in m.groups() if g), None)
        total += _to_int(token) or 0
    return total


def parse_votes(text):
    """Vote sentences with what they state. Returns {"result", "votes": [...]}.

    result: "unanimous" (every vote unanimous), "majority" (any majority or a
    contrary/abstaining count), "rejected", or None when no vote was found.
    """
    votes = []
    for s in sentences(text):
        if not _VOTE_WORD.search(s):
            continue
        v = {"sentence": s}
        if _REJECT.search(s):
            v["kind"] = "rejected"
        elif _UNANIMITY.search(s):
            v["kind"] = "unanimous"
        elif _MAJORITY.search(s) or _FOR.search(s):
            v["kind"] = "majority"
        else:
            if not (_ABSTAINS.search(s) or _ABSTAIN_N.search(s) or _AGAINST.search(s) or _NO_PART.search(s)):
                continue
            v["kind"] = "majority"
        v["for"] = _count(_FOR, s) or None
        v["against"] = _count(_AGAINST, s) or None
        v["abstentions"] = (_count(_ABSTAIN_N, s) or len(_ABSTAINS.findall(s))) or None
        v["did_not_vote"] = len(_NO_PART.findall(s)) or None
        votes.append(v)
    if not votes:
        return {"result": None, "votes": []}
    kinds = {v["kind"] for v in votes}
    result = ("rejected" if "rejected" in kinds else "majority" if "majority" in kinds
              or any(v["against"] or v["abstentions"] for v in votes) else "unanimous")
    return {"result": result, "votes": votes}


# ---- amounts and rates -------------------------------------------------------------------

_EURO = re.compile(r"(?P<n>\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?\b|EUR\b)", re.I)
_PCT = re.compile(r"(?P<n>\d+(?:,\d+)?)\s*%")


def parse_number(raw):
    """French amount text to float: '12 000,50' -> 12000.5; '3 522.01' -> 3522.01."""
    s = raw.replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    return float(s)


def find_amounts(text):
    out = []
    for s in sentences(text):
        for m in _EURO.finditer(s):
            out.append({"kind": "eur", "value": parse_number(m.group("n")),
                        "raw": m.group(0).strip(), "sentence": s})
        for m in _PCT.finditer(s):
            out.append({"kind": "pct", "value": float(m.group("n").replace(",", ".")),
                        "raw": m.group(0).strip(), "sentence": s})
    return out


# ---- legal references --------------------------------------------------------------------

_CODES = [
    ("CGCT", r"code g[ée]n[ée]ral des collectivit[ée]s territoriales|\bCGCT\b"),
    ("Urbanisme", r"code de l[’']urbanisme"),
    ("CGI", r"code g[ée]n[ée]ral des imp[ôo]ts|\bCGI\b"),
    ("Commande publique", r"code de la commande publique"),
    ("Environnement", r"code de l[’']environnement"),
    ("Fonction publique", r"code g[ée]n[ée]ral de la fonction publique|\bCGFP\b"),
    ("Voirie routière", r"code de la voirie routi[èe]re"),
    ("Patrimoine", r"code du patrimoine"),
    ("Forestier", r"code forestier"),
]
_ARTICLE = re.compile(r"\barticles?\s+(?P<art>[LRD]\s?\.?\s?\d{1,4}(?:[-‑]\d+){0,3}(?:\s*(?:et|à)\s*[LRD]?\s?\d[\d\-‑]*)?)", re.I)
_TEXT_REF = re.compile(r"\b(?P<kind>loi|décret|ordonnance|arrêté)\s+(?:n°\s*)?(?P<num>\d{2,4}-\d+)", re.I)
_BUDGET_INSTR = re.compile(r"\bM\s?(?:14|57|4\d)\b")


def find_legal_refs(text):
    """Articles (with the code named nearby), laws, decrees and budget instructions."""
    refs = []
    flat = " ".join(text.split())
    for s in sentences(text):
        for m in _ARTICLE.finditer(s):
            window = s[m.end(): m.end() + 160] + " " + s[max(0, m.start() - 80): m.start()]
            code = next((name for name, pat in _CODES if re.search(pat, window, re.I)), None)
            art = re.sub(r"\s+", "", m.group("art")).replace("‑", "-").upper()
            refs.append({"kind": "article", "code": code, "ref": art,
                         "key": f"{code or '?'} {art}", "sentence": s})
        for m in _TEXT_REF.finditer(s):
            kind = m.group("kind").lower()
            refs.append({"kind": kind, "code": None, "ref": m.group("num"),
                         "key": f"{kind} {m.group('num')}", "sentence": s})
        for m in _BUDGET_INSTR.finditer(s):
            ref = re.sub(r"\s+", "", m.group(0))
            refs.append({"kind": "instruction", "code": None, "ref": ref,
                         "key": f"instruction {ref}", "sentence": s})
    del flat
    seen, unique = set(), []
    for r in refs:
        k = (r["key"], r["sentence"])
        if k not in seen:
            seen.add(k)
            unique.append(r)
    return unique


# ---- exceptions ----------------------------------------------------------------------------

_EXCEPTION = re.compile(
    r"\bd[ée]rog\w*|\bexception\w*|à titre (?:exceptionnel|dérogatoire)|par exception", re.I)


def find_exceptions(text):
    return [{"marker": m.group(0).lower(), "sentence": s}
            for s in sentences(text) for m in _EXCEPTION.finditer(s)][:12]


# ---- follow-up candidates ------------------------------------------------------------------

_FOLLOWUPS = [
    ("authorisation", re.compile(r"autorise\w*\s+(?:Monsieur\s+|M\.\s*|Madame\s+)?(?:le|la)\s+Maire\s+à|donne\s+(?:tout\s+)?pouvoir|mandate\w*", re.I)),
    ("deferred", re.compile(r"\breport[ée]e?s?\b|sera\s+(?:étudi|revu|reprogramm|soumis|inscrit|discut|reprécis)\w*|à l[’']ordre du jour d[’'e]\s*(?:une\s+)?prochaine?|prochain(?:e)?\s+(?:conseil|séance|réunion)|ultérieurement|en attente|à revoir|à l[’']étude|à étudier", re.I)),
    ("planned", re.compile(r"\b(?:sera|seront)\s+(?:contact|sollicit|demand|lanc|réalis|engag|mis|prévu|organis|présent)\w*|va être\s+\w+|à prévoir|\bun devis (?:sera|est à)", re.I)),
]


def find_followups(text):
    """Sentences that look like a commitment, a deferral or a plan. Candidates only."""
    out = []
    for s in sentences(text):
        for kind, pat in _FOLLOWUPS:
            if pat.search(s):
                out.append({"type": kind, "sentence": s})
                break
    return out


# ---- topics ---------------------------------------------------------------------------------

TOPICS = {
    "finances": r"budget|d[ée]cision modificative|compte (?:administratif|financier)|affectation|emprunt|tr[ée]sorerie|recettes|d[ée]penses|fiscalit|taux d.imposition|taxe",
    "subventions": r"subvention",
    "urbanisme": r"\bPLU\b|urbanisme|permis de (?:construire|démolir)|zonage|cadastr|parcelle|bien (?:présumé )?sans maître|alignement",
    "droit de préemption": r"pr[ée]emption|\bDIA\b|d[ée]claration d.intention d.ali[ée]ner",
    "voirie et travaux": r"voirie|travaux|r[ée]fection|chaussée|\broute\b|\bchemin\b|toiture|r[ée]novation|assainissement|\beau\b|r[ée]seau",
    "patrimoine, culture, tourisme": r"patrimoine|culture|tourisme|mus[ée]e|manufacture|village du livre|ateliers? d.art|église",
    "personnel": r"\bagents?\b|\bposte\b|adjoint|indemnit|centre de gestion|recrutement|contractuel|prévoyance|compl[ée]mentaire sant[ée]",
    "intercommunalité": r"communauté d.agglom|grand carcassonne|syndicat|intercommunal|\bSYADEN\b|\bSMMAR\b|\bSDIS\b|\bPETR\b",
    "environnement et risques": r"for[êe]t|incendie|d[ée]broussaill|inondation|risque|environnement|biodiversit",
    "école et enfance": r"[ée]cole|\bALSH\b|cantine|p[ée]riscolaire|scolaire|enfance|jeunesse",
    "vie institutionnelle": r"commission|d[ée]l[ée]gu[ée]|procès[- ]verbal|\bPV\b|règlement int[ée]rieur|secr[ée]tariat de séance|élection|démission|représentant",
    "associations et vie locale": r"association|f[êe]te|manifestation|march[ée]|salle des f[êe]tes|location de salle",
}
_TOPIC_RES = {k: re.compile(v, re.I) for k, v in TOPICS.items()}


def find_topics(title, body):
    """Topics ranked by matches; the title counts three times. Returns [(topic, hits)]."""
    scored = []
    for topic, pat in _TOPIC_RES.items():
        hits = 3 * len(pat.findall(title)) + len(pat.findall(body))
        if hits:
            scored.append((topic, hits))
    return sorted(scored, key=lambda t: -t[1])


_SALE_MARKERS = re.compile(
    r"pr[ée]emption|\bDIA\b|intention d.ali[ée]ner|d[ée]signation du bien|bien vendu|prix de vente"
    r"|\b(?:vendeur|acqu[ée]reur)s?\s*(?:\(s\))?\s*:", re.I)


def is_property_transaction(title, body):
    """Items about private property sales: their places and amounts stay out of aggregates.

    Deliberately broad: one marker anywhere is enough, because a single notice (a
    place, a price, named sellers) is what identifies someone in a small village.
    """
    return bool(_SALE_MARKERS.search(title) or _SALE_MARKERS.search(body))


# ---- place candidates -----------------------------------------------------------------------

_PLACE_TYPES = r"rue|chemin|place|impasse|avenue|route|ruelle|quai|boulevard|passage|cours|allée|esplanade|côte|traverse|carrefour|faubourg|ancien chemin"
_STOP = {"cadastré", "cadastrée", "cadastrés", "pour", "où", "qui", "est", "sera", "et", "à", "au", "afin",
         "avec", "dans", "sur", "sous", "soit", "ainsi", "ce", "cette", "ces", "le", "la", "les", "un", "une",
         "ont", "a", "par", "vers", "lors", "dont", "que", "suite", "aux", "ou", "n"}
_STREET = re.compile(
    r"\b(?P<num>\d{1,3}\s*(?:bis|ter)?\s+)?(?P<type>" + _PLACE_TYPES + r")\s+"
    r"(?P<name>(?:(?:de la|de l[’']|du|des|de|d[’'])\s*)?[\wÀ-ÿ’'\-]+(?:\s+[\wÀ-ÿ’'\-]+){0,3})", re.I)
_LIEUDIT = re.compile(
    r"\blieux?[\s-]?dits?\s+(?:de la |de l[’']|du |des |de |d[’'])?[«“\"]?\s*(?P<name>[A-ZÀ-Ý][\wÀ-ÿ’'\-]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ’'\-]+){0,2})")


def _trim(name):
    words = []
    for w in name.split():
        if w.lower() in _STOP or re.fullmatch(r"n°?\d*|\d+", w, re.I):
            break
        words.append(w)
    return " ".join(words)


def find_place_candidates(text):
    """Street and lieu-dit mentions. Candidates: they are confirmed only by geocoding."""
    out, seen = [], set()
    flat = " ".join(text.split())
    for m in _STREET.finditer(flat):
        name = _trim(m.group("name"))
        if not name:
            continue
        label = f"{m.group('type').lower()} {name}"
        if label.lower() not in seen:
            seen.add(label.lower())
            out.append({"kind": "street", "label": label, "number": (m.group("num") or "").strip() or None})
    for m in _LIEUDIT.finditer(flat):
        label = _trim(m.group("name"))
        if label and label.lower() not in seen:
            seen.add(label.lower())
            out.append({"kind": "lieu-dit", "label": label, "number": None})
    return out
