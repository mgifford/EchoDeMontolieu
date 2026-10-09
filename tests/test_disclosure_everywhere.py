"""Every file this project publishes, and every document it ships, must carry the AI disclosure."""
import json
from pathlib import Path

from echo_montolieu import disclosure

ROOT = Path(__file__).resolve().parent.parent


def _files(pattern):
    return sorted((ROOT / "public").rglob(pattern))


def test_every_published_markdown_has_front_matter_and_notice():
    files = _files("*.md")
    assert files, "no published Markdown to check"
    for f in files:
        t = f.read_text(encoding="utf-8")
        assert "human_reviewed: false" in t, f
        assert "produced_by:" in t, f
        assert disclosure.AI_PAGE_URL in t, f
        assert "AI disclosure." in t or "Information sur l’IA." in t or "Informatie over AI." in t, f


def test_every_published_json_carries_the_disclosure_fields():
    files = _files("*.json")
    assert files
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        # per-document records keep the fields in `labels`; index and places files keep them at the top level
        holder = data.get("labels") if isinstance(data.get("labels"), dict) else data
        assert holder.get("human_reviewed") is False, f
        assert holder.get("ai_disclosure") == disclosure.AI_PAGE_URL, f
        assert holder.get("disclaimer"), f


def test_published_html_names_ai():
    for f in _files("*.html"):
        t = f.read_text(encoding="utf-8")
        headings = [disclosure._TEXT[lang]["heading"] for lang in ("en", "fr", "nl")]       # the map pages exist in all three languages
        assert any(h in t for h in headings) and disclosure.AI_PAGE_URL in t, f


def test_documents_carry_a_disclosure():
    for name in ("README.md", "ACCESSIBILITY.md", "jobs/README.md"):
        assert "AI disclosure" in (ROOT / name).read_text(encoding="utf-8"), name
    meta = json.loads((ROOT / "data" / "where_to_find_mairie.json").read_text(encoding="utf-8"))["_meta"]
    assert meta["human_reviewed"] is False and "AI.md" in meta["ai_disclosure"]
    assert (ROOT / "AI.md").exists()
