"""Write the French summary and the English and Dutch versions of each meeting.

Per meeting folder (names in French unless marked):
  summary.md                French summary written by a model from the scrubbed text
  summary.en.md, .nl.md     machine translations of that summary
  minutes.en.md, .nl.md     machine translations of the full minutes

Safety, all enforced here:
  * a spending cap that stops the run (BudgetExceeded);
  * names are masked before text is sent; sale notices are never sent;
  * a translated passage that fails the number or reference checks is replaced by the
    French original with a visible note;
  * reruns are free: results are cached, and a file whose inputs are unchanged is skipped.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .meeting import known_names, parse_meeting
from .render import LABELS, meeting_folder, render_all, render_minutes
from .summarise import SUMMARY_PROMPT_VERSION, summarise, summary_input
from .translate import PROMPT_VERSION, BudgetExceeded

SUMMARY_NOTICE = {
    "en": "> **Machine translation** of a French summary that was itself written by an AI model. It may contain "
          "errors or omissions. The French minutes and the original PDF are authoritative.",
    "nl": "> **Automatische vertaling** van een Franse samenvatting die zelf door een AI-model is geschreven. Ze kan "
          "fouten of weglatingen bevatten. De Franse notulen en de originele pdf zijn leidend.",
}


class Budget:
    """Running spend across models; `hook(price)` makes the on_usage callback for one model."""

    def __init__(self, cap_usd):
        self.cap, self.spent = cap_usd, 0.0

    def hook(self, price):
        def on_usage(result):
            if price:
                self.spent += (result.prompt_tokens * price[1] + result.completion_tokens * price[2]) / 1_000_000
            if self.spent > self.cap:
                raise BudgetExceeded(f"spent ${self.spent:.4f} > cap ${self.cap}")
        return on_usage


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _front_value(path, key):
    if not path.exists():
        return None
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.+)$", path.read_text(encoding="utf-8").split("\n---\n", 1)[0])
    return m.group(1).strip() if m else None


def _split_front_matter(md):
    if md.startswith("---\n") and "\n---\n" in md[4:]:
        head, body = md[4:].split("\n---\n", 1)
        return head, body
    return "", md


def _sensitive_pages(meeting):
    return {n for it in meeting["items"] if it["sensitive"] for n in range(it["pages"][0], it["pages"][1] + 1)}


def translate_segments(segments, lang, translator, names):
    """{segment: (text_to_show, ok)}; failures keep the French and say so."""
    unique = list(dict.fromkeys(segments))
    results = translator.translate_many(unique, lang, names) if unique else []
    return {seg: (text if ok else seg, ok) for seg, (text, ok, _) in zip(unique, results)}


def translate_minutes(rec, meeting, lang, translator, names):
    """Markdown of the full minutes in `lang`. Returns (markdown, failed_count, translated_count)."""
    sensitive = _sensitive_pages(meeting)
    seen = []

    def collect(text, page=None):
        if page not in sensitive:
            seen.append(text)
        return text

    render_minutes(rec, lang=lang, tr=collect)                       # pass 1: find the prose
    done = translate_segments(seen, lang, translator, names)
    note = LABELS[lang]["untranslated"]

    def tr(text, page=None):
        if page in sensitive or text not in done:
            return text
        shown, ok = done[text]
        return shown if ok else f"{text} _[{note}]_"

    failed = sum(1 for _, ok in done.values() if not ok)
    extra = {"translated_from": "fr", "machine_translated": "true", "labels_reviewed": "false",
             "translation_prompt_version": PROMPT_VERSION, "segments_translated": len(done) - failed,
             "segments_kept_in_french": failed,
             "source_sha256_of_minutes": rec["source_sha256"]}
    return render_minutes(rec, lang=lang, tr=tr, extra=extra), failed, len(done)


def translate_summary(summary_md, lang, translator, names, model_name):
    """Translate summary.md line by line, keeping structure, front matter and page citations."""
    head, body = _split_front_matter(summary_md)
    lines = body.split("\n")
    kinds, segments = [], []
    for line in lines:
        if not line.strip():
            kinds.append(("blank", line, ""))
        elif line.startswith("> "):
            kinds.append(("drop", line, ""))                       # the French notice is replaced below
        else:
            m = re.match(r"^(#{1,6} |- |\* )?(.*)$", line)
            kinds.append(("text", m.group(1) or "", m.group(2)))
            segments.append(m.group(2))
    done = translate_segments(segments, lang, translator, names)
    note = LABELS[lang]["untranslated"]
    out = []
    for kind, prefix, text in kinds:
        if kind == "blank":
            out.append("")
        elif kind == "text":
            shown, ok = done[text]
            out.append(prefix + (shown if ok else f"{text} _[{note}]_"))
    body_out = "\n".join(out)
    body_out = re.sub(r"^(# .*)$", lambda m: m.group(1) + "\n\n" + SUMMARY_NOTICE[lang], body_out, count=1, flags=re.M)
    failed = sum(1 for _, ok in done.values() if not ok)
    front = [l for l in head.split("\n") if l and not re.match(r"(language|summary_model|status|checks_failed|kind|title):", l)]
    front += [f"language: {lang}", "kind: summary", "translated_from: fr", "machine_translated: true",
              f"translation_model: {model_name}", f"summary_source_sha256: {_sha(summary_md)}",
              f"segments_kept_in_french: {failed}", "labels_reviewed: false"]
    return "---\n" + "\n".join(front) + "\n---\n" + body_out.rstrip() + "\n", failed, len(done)


def generate(public_dir, summary_model, translator, langs, only=None, force=False, now=None):
    """Write the files for every meeting (or those in `only`). Returns a report."""
    public = Path(public_dir)
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    report = {"meetings": [], "summaries": 0, "translations": 0, "skipped": 0, "needs_review": [], "stopped": None}
    taken = set()
    entries = sorted(index["documents"], key=lambda d: ((d["meeting_date"] or {}).get("value") or "", d["filename"] or ""))
    try:
        for entry in entries:
            rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
            folder = meeting_folder(rec, taken)
            if only and folder not in only:
                continue
            target = public / "meetings" / folder
            target.mkdir(parents=True, exist_ok=True)
            meeting = parse_meeting(rec)
            names = known_names(rec)
            row = {"folder": folder}

            source_hash = _sha(summary_input(meeting))
            summary_path = target / "summary.md"
            fresh = (_front_value(summary_path, "input_sha256") == source_hash
                     and _front_value(summary_path, "summary_model") == summary_model.model
                     and _front_value(summary_path, "prompt_version") == SUMMARY_PROMPT_VERSION)
            if force or not fresh:
                md, checks, status = summarise(meeting, summary_model, now)
                summary_path.write_text(md, encoding="utf-8")
                report["summaries"] += 1
                row["summary"] = status
                if status != "ok":
                    report["needs_review"].append(f"{folder}/summary.md")
            else:
                row["summary"] = "unchanged"
                report["skipped"] += 1
            summary_md = summary_path.read_text(encoding="utf-8")

            for lang in langs:
                s_path, m_path = target / f"summary.{lang}.md", target / f"minutes.{lang}.md"
                if force or _front_value(s_path, "summary_source_sha256") != _sha(summary_md) \
                        or _front_value(s_path, "translation_model") != translator.model:
                    text, failed, total = translate_summary(summary_md, lang, translator, names, translator.model)
                    s_path.write_text(text, encoding="utf-8")
                    report["translations"] += 1
                    if failed:
                        report["needs_review"].append(f"{folder}/summary.{lang}.md: {failed}/{total} segments kept in French")
                else:
                    report["skipped"] += 1
                if force or _front_value(m_path, "source_sha256_of_minutes") != rec["source_sha256"] \
                        or not m_path.exists():
                    text, failed, total = translate_minutes(rec, meeting, lang, translator, names)
                    text = text.replace("machine_translated: true", f"machine_translated: true\ntranslation_model: {translator.model}", 1)
                    m_path.write_text(text, encoding="utf-8")
                    report["translations"] += 1
                    if failed:
                        report["needs_review"].append(f"{folder}/minutes.{lang}.md: {failed}/{total} segments kept in French")
                else:
                    report["skipped"] += 1
            report["meetings"].append(row)
    except BudgetExceeded as exc:
        report["stopped"] = str(exc)
    render_all(public)                                               # refresh index.md with the new links
    return report


def estimate_generation(public_dir, langs, summary_price, translate_price):
    """Rough tokens and USD before any call (about 3.2 characters per token). Sends nothing."""
    public = Path(public_dir)
    index = json.loads((public / "index.json").read_text(encoding="utf-8"))
    summary_in = minutes_chars = meetings = 0
    for entry in index["documents"]:
        rec = json.loads((public / entry["file"]).read_text(encoding="utf-8"))
        meeting = parse_meeting(rec)
        sensitive, seen = _sensitive_pages(meeting), []
        render_minutes(rec, lang="en", tr=lambda t, page=None: (seen.append(t) if page not in sensitive else None) or t)
        summary_in += len(summary_input(meeting))
        minutes_chars += sum(len(t) for t in dict.fromkeys(seen))
        meetings += 1
    summary_tokens_in, summary_tokens_out = int(summary_in / 3.2) + 500 * meetings, 900 * meetings
    per_lang_chars = minutes_chars + 2800 * meetings          # the minutes plus a ~2,800-character summary
    tr_in = int(per_lang_chars / 3.2) * len(langs) + 40 * meetings * len(langs)
    tr_out = int(per_lang_chars / 3.2 * 1.25) * len(langs)

    def usd(tokens_in, tokens_out, price):
        return None if price is None else (tokens_in * price[1] + tokens_out * price[2]) / 1_000_000

    return {"meetings": meetings, "summary": {"tokens_in": summary_tokens_in, "tokens_out": summary_tokens_out,
                                              "usd": usd(summary_tokens_in, summary_tokens_out, summary_price)},
            "translation": {"tokens_in": tr_in, "tokens_out": tr_out, "usd": usd(tr_in, tr_out, translate_price)}}
