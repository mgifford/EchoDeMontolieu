import io
import os

import pymupdf
import pytest
import pytesseract
from PIL import Image, ImageDraw, ImageFont

from echo_montolieu.extract import (extract_pdf, find_meeting_date,
                                    page_needs_ocr)
from echo_montolieu.minutes import parse_minutes_index

TESSDATA = os.environ.get("ECHO_TESSDATA")


def test_page_needs_ocr_rules():
    assert page_needs_ocr("", 0.0)
    assert page_needs_ocr("ETAT DES TAXES POUR 2024", 0.62)  # the real page 9
    assert not page_needs_ocr("x" * 2000, 0.9)               # scan with good text layer
    assert not page_needs_ocr("x" * 100, 0.05)               # short but no image


def test_find_meeting_date_is_tentative_and_sourced():
    d = find_meeting_date("CONSEIL MUNICIPAL DU 18 SEPTEMBRE 2024 à 20 h 00")
    assert d["value"] == "2024-09-18"
    assert d["status"] == "tentative"
    assert "page 1" in d["source"]
    assert find_meeting_date("1er mars 2026")["value"] == "2026-03-01"
    assert find_meeting_date("aucune date ici") is None


def test_parse_minutes_index_dedupes_and_flags_drafts():
    html = """
      <a href="/wp-content/uploads/2024/12/Projet-CM-15-avril-site-internet.pdf"><img></a>
      <a href="https://www.montolieu.fr/wp-content/uploads/2024/12/Projet-CM-15-avril-site-internet.pdf">Projet</a>
      <a href="/wp-content/uploads/2025/01/CRCM-27-11-2024-site-internet.PDF">CR</a>
      <a href="/contact/">Contact</a>"""
    items = parse_minutes_index(html, "https://www.montolieu.fr/mairie/comptes-rendus-cm/")
    assert [i["filename"] for i in items] == [
        "Projet-CM-15-avril-site-internet.pdf", "CRCM-27-11-2024-site-internet.PDF"]
    assert items[0]["draft_suspected"] and not items[1]["draft_suspected"]
    assert items[0]["link_text"] is None  # image-only link keeps no invented title


def _have_french_ocr():
    try:
        if TESSDATA:
            os.environ["TESSDATA_PREFIX"] = TESSDATA
        return "fra" in pytesseract.get_languages()
    except Exception:
        return False


@pytest.mark.skipif(not _have_french_ocr(),
                    reason="needs Tesseract with fra data (set ECHO_TESSDATA)")
def test_extract_pdf_uses_text_layer_and_ocrs_image_pages(tmp_path):
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 100), "Conseil municipal du 18 septembre 2024. " * 12, fontsize=9)

    img = Image.new("RGB", (1100, 300), "white")
    ImageDraw.Draw(img).text((40, 100), "Taxe fonciere 2024",
                             fill="black", font=ImageFont.load_default(size=56))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    p2 = doc.new_page()
    p2.insert_image(pymupdf.Rect(30, 30, 565, 300), stream=buf.getvalue())
    pdf = tmp_path / "t.pdf"
    doc.save(pdf)

    out = extract_pdf(pdf, "https://example.test/t.pdf", "2026-10-08T00:00:00+00:00",
                      tessdata_dir=TESSDATA)
    first, second = out["pages"]
    assert first["method"] == "text_layer" and first["status"] == "machine_extracted"
    assert second["method"] == "tesseract"
    assert second["status"] in {"machine_read", "needs_review"}
    assert "OCR" in second["note"]
    assert "Taxe" in second["text"]
    assert second["page_url"] == "https://example.test/t.pdf#page=2"
    assert out["meeting_date"]["value"] == "2024-09-18"
    assert len(out["sha256"]) == 64
