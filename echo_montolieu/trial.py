"""Compare translation models on real minutes: automatic checks, cost, and a blind rating sheet.

Run with --dry-run to see the sample and the estimated cost first; nothing is sent.
Output goes to trials/<name>/ (git-ignored): results.json, report.md, rating_sheet.csv
(blind A/B) and key.json (which model was A). The spending cap stops the run, it is
not a suggestion.
"""
import csv
import json
import random
import re
import urllib.request
from pathlib import Path

from .meeting import attendance_names
from .text import clean_page_lines, paragraphs
from .translate import (LANGUAGES, BudgetExceeded, ChatTranslator, check_translation,  # noqa: F401
                        mask_names, unmask)
from .signals import is_property_transaction

ROUTER_MODELS = "https://router.huggingface.co/v1/models"
CATEGORIES = {
    "vote": re.compile(r"unanimit|majorit|abstention|voix pour|s’abstient", re.I),
    "amounts": re.compile(r"\d[\d  .]*(?:,\d+)?\s*(?:€|euros?)", re.I),
    "legal": re.compile(r"article\s+[LRD]\s?\d|\bdécret\b|\bloi\s+n", re.I),
    "followup": re.compile(r"sera\s+\w+|prochain|à prévoir|report", re.I),
    "plain": re.compile(r"."),
}


def pick_sample(records, per_category=4, seed=7):
    """Deterministic, varied sample of paragraphs. Private property sales are never sampled."""
    rng = random.Random(seed)
    pool = {c: [] for c in CATEGORIES}
    for rec in records:
        full = "\n".join(p.get("text") or "" for p in rec["pages"])
        present, absent, holders = attendance_names(full)
        names = present + absent + holders
        lines = [(l, p["page"]) for p in rec["pages"] if p["method"] != "tesseract" and p.get("text")
                 for l in clean_page_lines(p["text"], p["page"])]
        for b in paragraphs(lines):
            text = b["text"].strip()
            if b["kind"] not in ("paragraph", "bullet") or not (60 <= len(text) <= 600):
                continue
            if is_property_transaction("", text):
                continue
            for category, pattern in CATEGORIES.items():
                if pattern.search(text):
                    pool[category].append({"category": category, "source_url": rec["source_url"],
                                           "page": b["page"], "date": (rec.get("meeting_date") or {}).get("value"),
                                           "text": text, "names": names})
                    break
    sample = []
    for category, rows in pool.items():
        rng.shuffle(rows)
        sample += rows[:per_category]
    for i, row in enumerate(sample, start=1):
        row["id"] = f"s{i:02d}"
    return sample


def price_per_million(model_spec, listing=None):
    """(provider, input USD, output USD) at the cheapest live provider, or None if unknown."""
    model_id = model_spec.split(":")[0]
    if listing is None:
        with urllib.request.urlopen(ROUTER_MODELS, timeout=30) as resp:
            listing = json.load(resp)["data"]
    for m in listing:
        if m["id"] == model_id:
            live = [p for p in m["providers"] if p.get("status") == "live" and p.get("pricing")]
            if live:
                best = min(live, key=lambda p: p["pricing"]["input"] + p["pricing"]["output"])
                return best["provider"], best["pricing"]["input"], best["pricing"]["output"]
    return None


def estimate(sample, langs, prices):
    """Rough tokens and USD per model, before any call. Text is ~3.2 characters per token."""
    chars = sum(len(s["text"]) for s in sample)
    out = {}
    for model, price in prices.items():
        calls = len(sample) * len(langs)
        tokens_in = int(chars / 3.2) * len(langs) + 220 * calls
        tokens_out = int(chars / 3.2 * 1.25) * len(langs)
        usd = None if price is None else (tokens_in * price[1] + tokens_out * price[2]) / 1_000_000
        out[model] = {"calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": usd}
    return out


def run_trial(sample, models, langs, translators, prices, max_usd, out_dir, seed=7):
    """translators: {model: translator}. Stops with BudgetExceeded past max_usd."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    rows = []
    for model in models:
        price = prices.get(model)
        for lang in langs:
            for s in sample:
                masked, mapping = mask_names(s["text"], s["names"])
                result = translators[model].translate(masked, lang)
                if price and not result.cached:
                    spent += (result.prompt_tokens * price[1] + result.completion_tokens * price[2]) / 1_000_000
                    if spent > max_usd:
                        raise BudgetExceeded(f"spent ${spent:.4f} > cap ${max_usd}")
                text = unmask(result.text, mapping)
                rows.append({"id": s["id"], "category": s["category"], "model": model, "lang": lang,
                             "source": s["text"], "translation": text,
                             "checks": check_translation(masked, result.text, lang, mapping),
                             "seconds": round(result.seconds, 2), "tokens": [result.prompt_tokens, result.completion_tokens],
                             "cached": result.cached})
    (out_dir / "results.json").write_text(json.dumps({"rows": rows, "spent_usd": round(spent, 5)}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_blind_sheet(rows, models, langs, out_dir, seed)
    (out_dir / "report.md").write_text(render_report(rows, models, langs, spent, max_usd), encoding="utf-8")
    return rows, spent


def write_blind_sheet(rows, models, langs, out_dir, seed=7):
    """CSV with the two models shuffled per segment, so a rater cannot tell which is which."""
    rng = random.Random(seed)
    by = {(r["id"], r["model"], r["lang"]): r for r in rows}
    key, lines = {}, []
    for lang in langs:
        for sid in sorted({r["id"] for r in rows}):
            if len(models) < 2:
                continue
            order = list(models[:2])
            rng.shuffle(order)
            key[f"{sid}-{lang}"] = {"A": order[0], "B": order[1]}
            a, b = by[(sid, order[0], lang)], by[(sid, order[1], lang)]
            lines.append({"id": f"{sid}-{lang}", "language": lang, "category": a["category"], "french": a["source"],
                          "A": a["translation"], "B": b["translation"],
                          "accuracy_A_1to5": "", "accuracy_B_1to5": "", "fluency_A_1to5": "", "fluency_B_1to5": "",
                          "better (A/B/same)": "", "notes": ""})
    with open(out_dir / "rating_sheet.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(lines[0].keys())) if lines else None
        if writer:
            writer.writeheader()
            writer.writerows(lines)
    (out_dir / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")


def render_report(rows, models, langs, spent, max_usd):
    out = ["# Translation trial", "",
           "Automatic checks only catch some failures (changed numbers, lost placeholders, a model "
           "that explains instead of translating, the wrong language). They cannot judge accuracy or "
           "fluency: use `rating_sheet.csv`, where the models are hidden as A and B.", "",
           f"Spent ${spent:.4f} of a ${max_usd} cap.", ""]
    for lang in langs:
        out += [f"## {LANGUAGES[lang]}", "", "| Model | Segments | All checks pass | Numbers kept | Language ok | Median s | Tokens in/out |", "|---|---|---|---|---|---|---|"]
        for model in models:
            rs = [r for r in rows if r["model"] == model and r["lang"] == lang]
            if not rs:
                continue
            n = len(rs)
            allpass = sum(all(r["checks"].values()) for r in rs)
            nums = sum(r["checks"]["numbers_preserved"] for r in rs)
            lang_rs = [r for r in rs if "is_target_language" in r["checks"]]
            langok = sum(r["checks"]["is_target_language"] for r in lang_rs)
            secs = sorted(r["seconds"] for r in rs)
            out.append(f"| {model} | {n} | {allpass}/{n} | {nums}/{n} | {langok}/{len(lang_rs)} | {secs[len(secs) // 2]} "
                       f"| {sum(r['tokens'][0] for r in rs)}/{sum(r['tokens'][1] for r in rs)} |")
        failing = [r for r in rows if r["lang"] == lang and not all(r["checks"].values())]
        if failing:
            out += ["", "Segments with a failed check:", ""]
            for r in failing[:12]:
                bad = ", ".join(k for k, v in r["checks"].items() if not v)
                out.append(f"- {r['id']} ({r['model']}): {bad}")
        out.append("")
    return "\n".join(out)
