"""Machine translation of the minutes, with guardrails and checks.

A translation is a model's output, not a fact. Everything here exists to make
that visible and checkable:
  * personal names are masked before text leaves the machine and restored after;
  * a glossary pins municipal terms (a starter list: a native speaker should review it);
  * every output is checked: numbers, placeholders, legal references, preamble,
    length and language;
  * results are cached by (text, model, language, prompt version), so unchanged
    text is never translated twice.
The French original is always the authoritative text.
"""
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

PROMPT_VERSION = "1"
LANGUAGES = {"en": "English", "nl": "Dutch"}

# Starter glossary, French to preferred target wording. NOT reviewed by a native
# speaker; treat as a proposal. Terms keep the French in brackets where a literal
# translation could mislead.
GLOSSARY = {
    "en": {
        "droit de préemption": "right of pre-emption",
        "conseil municipal": "municipal council",
        "ordre du jour": "agenda",
        "procès-verbal": "minutes",
        "à l'unanimité": "unanimously",
        "à l’unanimité": "unanimously",
        "décision modificative": "budget amendment (décision modificative)",
        "compte administratif": "administrative account (compte administratif)",
        "lieu-dit": "locality (lieu-dit)",
        "commune": "municipality",
        "le maire": "the Mayor",
    },
    "nl": {
        "droit de préemption": "voorkooprecht (droit de préemption)",
        "conseil municipal": "gemeenteraad",
        "ordre du jour": "agenda",
        "procès-verbal": "notulen",
        "à l'unanimité": "unaniem",
        "à l’unanimité": "unaniem",
        "décision modificative": "begrotingswijziging (décision modificative)",
        "compte administratif": "jaarrekening (compte administratif)",
        "lieu-dit": "buurtschap (lieu-dit)",
        "commune": "gemeente",
        "le maire": "de burgemeester",
    },
}
# Words the checker accepts as evidence a glossary term was honoured.
GLOSSARY_EVIDENCE = {
    "en": {"droit de préemption": ["pre-emption", "preemption"], "à l'unanimité": ["unanimous"],
           "à l’unanimité": ["unanimous"], "conseil municipal": ["municipal council", "town council"],
           "procès-verbal": ["minutes"]},
    "nl": {"droit de préemption": ["voorkoop", "voorkeursrecht"], "à l'unanimité": ["unaniem", "unanimiteit", "eenstemmig"],
           "à l’unanimité": ["unaniem", "unanimiteit", "eenstemmig"], "conseil municipal": ["gemeenteraad"],
           "procès-verbal": ["notulen", "verslag"]},
}

MASK_OPEN, MASK_CLOSE = "⟦", "⟧"


def mask_names(text, names):
    """Replace names with ⟦N1⟧-style tokens. Returns (masked, mapping token -> original text)."""
    from .privacy import _fold, _patterns

    folded = _fold(text)
    spans = []
    for name in sorted(set(names), key=len, reverse=True):
        if len(name.split()) >= 2:
            for pat in _patterns(name):
                spans += [(m.start(), m.end()) for m in pat.finditer(folded)]
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept, last = [], -1
    for start, end in spans:
        if start >= last:
            kept.append((start, end))
            last = end
    mapping = {}
    for index, (start, end) in reversed(list(enumerate(kept, start=1))):
        token = f"{MASK_OPEN}N{index}{MASK_CLOSE}"
        mapping[token] = text[start:end]
        text = text[:start] + token + text[end:]
    return text, mapping


def unmask(text, mapping):
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text


def glossary_for(text, lang):
    low = text.lower()
    return {fr: to for fr, to in GLOSSARY[lang].items() if fr in low}


def build_messages(text, lang):
    hits = glossary_for(text, lang)
    rules = [
        f"Translate the French text into {LANGUAGES[lang]}. It comes from official minutes of a French town council.",
        "Translate faithfully. Do not summarise, explain, correct, add or omit anything.",
        f"Keep every number, date, euro amount, percentage and legal reference exactly as written (for example 'article L2121-21 du CGCT').",
        f"Keep every token that looks like {MASK_OPEN}N1{MASK_CLOSE} exactly as it is.",
        "Keep markdown and punctuation structure. Output only the translation, with no preface.",
    ]
    if hits:
        rules.append("Use these terms: " + "; ".join(f"'{fr}' = '{to}'" for fr, to in hits.items()) + ".")
    return [{"role": "system", "content": " ".join(rules)}, {"role": "user", "content": text}]


# ---- checks ---------------------------------------------------------------------------------

_NUM = re.compile(r"\d[\d\s .,]*\d|\d")
_STOP = {
    "fr": {"le", "la", "les", "des", "du", "est", "une", "dans", "pour", "sur", "au", "aux", "que", "qui", "et", "au"},
    "en": {"the", "of", "and", "to", "is", "in", "for", "on", "with", "that", "by", "are", "was"},
    "nl": {"de", "het", "een", "van", "en", "dat", "is", "voor", "op", "met", "te", "niet", "zijn", "wordt"},
}
_PREAMBLE = re.compile(r"^\s*(?:here is|here's|voici|translation\s*:|de vertaling|hier is|sure|certainly)", re.I)


def number_cores(text):
    """Digit strings of every number, ignoring separators: '12 000,50' and '12,000.50' match."""
    return sorted(re.sub(r"\D", "", m.group(0)) for m in _NUM.finditer(text))


def _stop_ratio(text, lang):
    words = re.findall(r"[a-zà-ÿ’']+", text.lower())
    return sum(w in _STOP[lang] for w in words) / len(words) if words else 0.0


def check_translation(source, output, lang, mapping=None):
    """Automatic checks. Returns {check: bool}; a failure means "look at this one"."""
    mapping = mapping or {}
    checks = {
        "numbers_preserved": number_cores(source) == number_cores(output),
        "placeholders_preserved": all(output.count(t) == 1 for t in mapping),
        "no_preamble": not _PREAMBLE.search(output),
        "not_empty": bool(output.strip()),
    }
    ratio = len(output) / max(len(source), 1)
    checks["length_plausible"] = 0.5 <= ratio <= 2.0
    refs = re.findall(r"[LRD]\s?\d{3,4}(?:-\d+)+", source)
    checks["legal_refs_preserved"] = all(r.replace(" ", "") in output.replace(" ", "") for r in refs)
    long_enough = len(re.findall(r"[a-zà-ÿ]+", source.lower())) >= 8
    if long_enough:
        checks["is_target_language"] = (_stop_ratio(output, lang) > _stop_ratio(output, "fr")
                                         and _stop_ratio(output, "fr") < 0.12)
    low = source.lower()
    wanted = [fr for fr in GLOSSARY_EVIDENCE[lang] if fr in low]
    if wanted:
        checks["glossary_honoured"] = all(any(e in output.lower() for e in GLOSSARY_EVIDENCE[lang][fr]) for fr in wanted)
    return checks


# ---- translators ------------------------------------------------------------------------------


@dataclass
class Result:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    cached: bool = False


@dataclass
class ChatTranslator:
    """Translates through an OpenAI-style chat client (Hugging Face Inference Providers)."""
    model: str
    client: object = None
    cache_path: Path = None
    max_tokens: int = 1500
    _cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if self.cache_path and Path(self.cache_path).exists():
            self._cache = json.loads(Path(self.cache_path).read_text(encoding="utf-8"))

    def _key(self, text, lang):
        raw = json.dumps([text, self.model, lang, PROMPT_VERSION], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _client(self):
        if self.client is None:
            from huggingface_hub import InferenceClient  # reads the `hf auth login` token itself
            self.client = InferenceClient()
        return self.client

    def translate(self, text, lang):
        key = self._key(text, lang)
        if key in self._cache:
            hit = self._cache[key]
            return Result(hit["text"], hit["prompt_tokens"], hit["completion_tokens"], hit["seconds"], cached=True)
        started = time.monotonic()
        resp = self._client().chat.completions.create(
            model=self.model, messages=build_messages(text, lang), temperature=0, max_tokens=self.max_tokens)
        seconds = time.monotonic() - started
        usage = getattr(resp, "usage", None)
        result = Result(resp.choices[0].message.content.strip(),
                        getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0, seconds)
        self._cache[key] = {"text": result.text, "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens, "seconds": seconds}
        if self.cache_path:
            Path(self.cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.cache_path).write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        return result
