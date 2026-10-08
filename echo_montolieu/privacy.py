"""Pseudonymisation of private individuals named in the minutes.

Design (see README / handoff for the reasoning):
  * master id  M-xxxx: HMAC of the normalised name under a secret key. Stable
    across all documents. Private: only the maintainer can use it.
  * public id  P-xxxx: by default also keyed on the document, so the same person
    gets a different public id in each document and readers cannot link them
    across meetings. scope="global" makes the public id equal across documents.
  * registry (private/people.json): master id -> names seen and every place the
    person appears, with the public id used there. This is how the maintainer
    resolves an id back to a person.

Pseudonymised data is still personal data under the GDPR. This reduces
exposure; it does not make the data anonymous. Name detection is HEURISTIC and
covers only labelled fields (Vendeur / Acquereur / Proprietaire) plus names
already in the registry, so every document still needs maintainer review
before publication.

Two different people with the same name share one master id. An id means "same
normalised name", not "same person".
"""
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from pathlib import Path

KEY_ENV = "ECHO_PSEUDONYM_KEY"
KEY_FILE = "pseudonym.key"
MIN_KEY_CHARS = 32

# Words that mark an organisation, not a private individual (not exhaustive).
ORG_WORDS = {"safer", "sci", "sarl", "sas", "sa", "eurl", "earl", "gaec", "scea",
             "commune", "mairie", "departement", "etat", "region", "syndicat",
             "association", "societe", "indivision", "consorts", "ccas"}

PUBLIC_ID_RE = re.compile(r"P-[0-9a-f]{10}")

_LABEL_RE = re.compile(
    r"(?:Vendeur|Acqu[eé]reur|Propri[eé]taire)s?(?:\(s\))?\s*:\s*(.*)", re.IGNORECASE)


def _fold(s):
    """Lower-case and strip accents, keeping the string length unchanged."""
    return "".join(unicodedata.normalize("NFD", c)[0].lower() for c in s)


def _tokens(name):
    return [t for t in re.split(r"[^0-9a-z]+", _fold(name)) if t]


def normalize_name(name):
    """Order-insensitive, accent-insensitive form used for hashing."""
    return " ".join(sorted(_tokens(name)))


def find_private_names(text):
    """Names in labelled fields. Heuristic: returns [{"name", "field"}]."""
    lines = text.splitlines()
    found = []
    for i, line in enumerate(lines):
        m = _LABEL_RE.search(line)
        if not m:
            continue
        value, j = m.group(1).strip(), i
        # A list that ends in a comma or "et" continues on the next non-empty line.
        while re.search(r"(,|\bet)\s*$", value, re.IGNORECASE):
            nxt = next((k for k in range(j + 1, len(lines)) if lines[k].strip()), None)
            if nxt is None:
                break
            j = nxt
            value += " " + lines[j].strip()
        field = re.match(r"\w+", line.strip()).group(0) if re.match(r"\w+", line.strip()) else ""
        for part in re.split(r",|;|\bet\b", value):
            name = part.strip(" .:-\t")
            toks = _tokens(name)
            if PUBLIC_ID_RE.fullmatch(name):
                continue  # already a pseudonym (text was redacted before)
            if len(toks) >= 2 and not (set(toks) & ORG_WORDS):
                found.append({"name": name, "field": m.group(0).split(":")[0].strip()})
    return found


def _patterns(name):
    toks = _tokens(name)
    rotations = {tuple(toks[i:] + toks[:i]) for i in range(len(toks))}
    return [re.compile(r"(?<![0-9a-z])" + r"[\s\-]+".join(map(re.escape, r)) + r"(?![0-9a-z])")
            for r in rotations]


class Pseudonymiser:
    def __init__(self, key, private_dir):
        if len(key) < MIN_KEY_CHARS:
            raise ValueError(f"pseudonym key must be at least {MIN_KEY_CHARS} characters")
        self._key = key.encode("utf-8")
        self.private = Path(private_dir)
        self.private.mkdir(parents=True, exist_ok=True)
        self._path = self.private / "people.json"
        self.registry = (json.loads(self._path.read_text(encoding="utf-8"))
                         if self._path.exists() else {})

    @classmethod
    def from_environment(cls, private_dir):
        key = os.environ.get(KEY_ENV)
        if not key:
            keyfile = Path(private_dir) / KEY_FILE
            if not keyfile.exists():
                raise RuntimeError(f"no key: set {KEY_ENV} or run 'keygen'")
            key = keyfile.read_text(encoding="utf-8").strip()
        return cls(key, private_dir)

    @staticmethod
    def generate_key_file(private_dir):
        """Create private/pseudonym.key (0600). Never prints or overwrites."""
        private = Path(private_dir)
        private.mkdir(parents=True, exist_ok=True)
        path = private / KEY_FILE
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(32) + "\n")
        return path

    def _mac(self, label, value):
        return hmac.new(self._key, f"{label}|{value}".encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def master_id(self, name):
        return "M-" + self._mac("master", normalize_name(name))[:12]

    def public_id(self, name, doc_id, scope="document"):
        if scope == "global":
            return "P-" + self._mac("public", normalize_name(name))[:10]
        return "P-" + self._mac(f"public|{doc_id}", normalize_name(name))[:10]

    def register(self, name, doc_id, page, field, scope="document"):
        mid, pid = self.master_id(name), self.public_id(name, doc_id, scope)
        person = self.registry.setdefault(
            mid, {"normalized": normalize_name(name), "names_seen": [], "appearances": []})
        if name not in person["names_seen"]:
            person["names_seen"].append(name)
        entry = {"document": doc_id, "page": page, "field": field, "public_id": pid}
        if entry not in person["appearances"]:
            person["appearances"].append(entry)
        return pid

    def known_names(self):
        return [n for p in self.registry.values() for n in p["names_seen"]]

    def redact(self, text, doc_id, page, names, scope="document"):
        """Replace each name (any order) with its public id. Returns (text, count)."""
        folded = _fold(text)
        spans = []
        for name in names:
            pid = self.public_id(name, doc_id, scope)
            for pat in _patterns(name):
                spans += [(m.start(), m.end(), pid) for m in pat.finditer(folded)]
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        kept, last = [], -1
        for s in spans:  # drop overlaps, longest match first
            if s[0] >= last:
                kept.append(s)
                last = s[1]
        for start, end, pid in reversed(kept):
            text = text[:start] + pid + text[end:]
        return text, len(kept)

    def save(self):
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.registry, fh, ensure_ascii=False, indent=2)
        os.chmod(self._path, 0o600)

    def whois(self, identifier):
        """Resolve an M- or P- id. Maintainer use only."""
        out = []
        for mid, person in self.registry.items():
            hits = [a for a in person["appearances"] if a["public_id"] == identifier]
            if identifier == mid or hits:
                out.append({"master_id": mid, "names_seen": person["names_seen"],
                            "appearances": hits or person["appearances"]})
        return out


FIGURE_CATEGORIES = {"elected_official", "business_owner", "other_public_figure"}


class PublicFigures:
    """Maintainer-approved allow-list of people who may be named.

    Every entry must say WHY the name is already public (`basis`, ideally a URL).
    A listed person is exempt from redaction in their public role, but is still
    pseudonymised on any page where they appear in a private-transaction field
    (Vendeur / Acquereur / Proprietaire). Entries may carry valid_from/valid_to
    (ISO dates): outside that window, or when the document date is unknown, the
    exemption does not apply. An empty or missing list means nobody is exempt.
    """

    def __init__(self, entries):
        self.entries = []
        for e in entries:
            name = (e.get("name") or "").strip()
            if len(_tokens(name)) < 2:
                raise ValueError(f"public figure needs a full name: {e!r}")
            if e.get("category") not in FIGURE_CATEGORIES:
                raise ValueError(f"{name}: category must be one of {sorted(FIGURE_CATEGORIES)}")
            if not (e.get("basis") or "").strip():
                raise ValueError(f"{name}: 'basis' (why this is already public) is required")
            if e["category"] == "business_owner" and not e.get("diffusion_checked"):
                # Sole traders can opt out of publication of their name in the
                # SIRENE register; confirm they have not before listing them.
                raise ValueError(f"{name}: business_owner needs diffusion_checked=true")
            self.entries.append({**e, "_norm": normalize_name(name)})

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls([])
        return cls(json.loads(path.read_text(encoding="utf-8")).get("entries", []))

    def allows(self, name, doc_date=None):
        norm = normalize_name(name)
        for e in self.entries:
            if e["_norm"] != norm:
                continue
            lo, hi = e.get("valid_from"), e.get("valid_to")
            if (lo or hi) and not doc_date:
                continue  # unknown document date: fail closed
            if lo and doc_date < lo or hi and doc_date > hi:
                continue
            return True
        return False


def redact_extraction(extraction, pseud, scope="document", figures=None):
    """Redacted copy of an extraction. Contains no names; stays withheld."""
    figures = figures or PublicFigures([])
    doc_id = extraction["sha256"][:12]
    doc_date = (extraction.get("meeting_date") or {}).get("value")
    result = copy.deepcopy(extraction)
    total = 0
    for page in result["pages"]:
        found = find_private_names(page["text"])
        for f in found:
            pseud.register(f["name"], doc_id, page["page"], f["field"], scope)
        private_here = {f["name"] for f in found}
        # Allow-listed people stay visible, except where named in a private
        # transaction field on this page.
        names = sorted(n for n in set(pseud.known_names()) | private_here
                       if n in private_here or not figures.allows(n, doc_date))
        page_count = 0
        for key in ("text", "text_sparse"):
            if key in page:
                page[key], n = pseud.redact(page[key], doc_id, page["page"], names, scope)
                page_count = max(page_count, n)
        page["privacy"] = {"redactions": page_count, "detection": "heuristic"}
        total += page_count
    result["privacy"] = {
        "document_id": doc_id,
        "scope": scope,
        "detection": "heuristic: labelled fields (Vendeur/Acquereur/Proprietaire) and "
                     "names already in the registry; other names may remain",
        "redactions": total,
        "public_figures_list_entries": len(figures.entries),
        "public_release": "withheld",
        "needs": "maintainer review before publication",
    }
    pseud.save()
    return result
