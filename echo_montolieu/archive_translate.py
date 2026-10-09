"""English and Dutch for the decisions pages of the 2003-2008 minutes.

The full archived minutes are never sent to a model (their names are unchecked). What is sent here is only the
scrubbed decision sentences of `archive_digest`: every name is already replaced by "[name withheld]", which
is turned into a protected token for the model and restored in the target language afterwards. A sentence
whose automatic checks fail (numbers, the token, language, length) stays French with a visible note. The
translation is shown with the French under it, so a reader can compare.
"""
import hashlib
import json
import re
from pathlib import Path

from . import archive_digest as ad
from . import disclosure
from .render import LABELS, meeting_folder
from .translate import PROMPT_VERSION

TOKEN = "⟦W⟧"
PLACEHOLDER_IN = {"en": "[name withheld]", "nl": "[naam achtergehouden]"}


def _front(path):
    if not path.exists():
        return {}
    head = path.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    return {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in head.splitlines()) if k.strip()}


def is_current_translation(path, fr_sha):
    """True when `path` is a model translation of exactly this French page (render keeps such files)."""
    meta = _front(path)
    return meta.get("facts_source_sha256") == fr_sha and bool(meta.get("translation_model"))


def archived_digests(public):
    """[(folder, date, rec, digest)] for every recovered meeting, built the same way `render` builds them."""
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    entries = sorted(index["documents"], key=lambda d: ((d["meeting_date"] or {}).get("value") or "", d["filename"] or ""))
    taken, found = set(), []
    for entry in entries:
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        folder = meeting_folder(rec, taken)
        if rec.get("origin"):
            found.append((folder, (rec.get("meeting_date") or {}).get("value") or "undated", rec))
    vocab = ad.Vocabulary([r for _, _, r in found])
    return [(folder, date, rec, ad.digest(rec, vocab)) for folder, date, rec in found]


def translate_decisions(texts, lang, translator):
    """{index: (text, ok)} for the decision sentences. The name placeholder is protected and checked."""
    protected = [t.replace(ad.PLACEHOLDER, TOKEN) for t in texts]
    results = translator.translate_many(protected, lang, ()) if protected else []
    out = {}
    for i, (src, (text, ok, _)) in enumerate(zip(protected, results)):
        if ok and text.count(TOKEN) != src.count(TOKEN):
            ok = False
        out[i] = (text.replace(TOKEN, PLACEHOLDER_IN[lang]), ok)
    return out


def translate_archive_facts(public_dir, translator, langs, only=None, force=False):
    """Write facts.<lang>.md with translated quotes. Returns {"written", "skipped", "needs_review"}."""
    public = Path(public_dir)
    report = {"written": 0, "skipped": 0, "needs_review": []}
    for folder, date, rec, d in archived_digests(public):
        if (only and folder not in only) or not d["decisions"]:
            continue
        fr_sha = ad.facts_sha(rec, d, date)
        for lang in langs:
            path = public / "meetings" / folder / f"facts.{lang}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not force and is_current_translation(path, fr_sha) and _front(path).get("translation_model") == translator.model:
                report["skipped"] += 1
                continue
            translated = translate_decisions([x["text"] for x in d["decisions"]], lang, translator)
            failed = sum(1 for _, ok in translated.values() if not ok)
            body = ad.render_facts(rec, d, date, lang, translated=translated, model=translator.model)
            note = LABELS[lang]["untranslated"]
            if failed:
                body += f"\n> {note}: {failed}/{len(translated)}\n"
                report["needs_review"].append(f"{folder}/facts.{lang}.md: {failed}/{len(translated)} sentences kept in French")
            head = [f'title: "{ad.LABELS[lang]["title"].format(date=date)}"', "machine_generated: true", f"language: {lang}",
                    "translated_from: fr", "machine_translated: true", f"translation_model: {translator.model}",
                    f"translation_prompt_version: {PROMPT_VERSION}", f"facts_source_sha256: {fr_sha}",
                    f"segments_kept_in_french: {failed}", "labels_reviewed: false",
                    *[f"{k}: {v}" for k, v in disclosure.front_matter("translation", translator.model).items()]]
            path.write_text("---\n" + "\n".join(head) + "\n---\n" + body, encoding="utf-8")
            report["written"] += 1
    return report
