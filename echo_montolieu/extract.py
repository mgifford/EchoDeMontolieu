"""Page-level text extraction from council-minutes PDFs, with provenance.

Every page records how its text was obtained and how far to trust it. Pages
with a real text layer are used as-is. Pages that are mostly an image (a scanned
table, for example) are OCR'd with Tesseract and labelled for review.

The thresholds below are TENTATIVE: they were tuned by hand on five PDFs from
montolieu.fr and one OCR test page, not on a measured sample. See README.
"""
import hashlib
import io
import os
import re
import subprocess

import pymupdf
import pytesseract
from PIL import Image

MIN_TEXT_CHARS = 50          # below this a page has effectively no text layer
IMAGE_HEAVY_FRACTION = 0.25  # share of the page covered by images
IMAGE_HEAVY_MAX_CHARS = 300  # an image-heavy page with less text than this is OCR'd
REVIEW_MEAN_CONF = 85        # OCR mean word confidence below this -> needs_review
REVIEW_LOW_WORD_FRACTION = 0.15
LOW_WORD_CONF = 60

OCR_NOTE = ("Text recovered by OCR from an image. Figures and table structure "
            "may be wrong or missing; check the original page.")
IMAGE_TEXT_LAYER_NOTE = ("Page is largely an image with a text layer; the text "
                         "layer was not independently verified.")

MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}
_DATE_RE = re.compile(
    r"\b(\d{1,2})(?:er)?\s+(" + "|".join(MONTHS) + r")\s+(20\d{2})\b",
    re.IGNORECASE)


def page_needs_ocr(text, image_fraction):
    chars = len(text.strip())
    return chars < MIN_TEXT_CHARS or (
        image_fraction >= IMAGE_HEAVY_FRACTION and chars < IMAGE_HEAVY_MAX_CHARS)


def find_meeting_date(page_text, page_number=1):
    """First French long-form date on the page, labelled tentative."""
    m = _DATE_RE.search(page_text)
    if not m:
        return None
    day, month, year = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
    return {
        "value": f"{year:04d}-{month:02d}-{day:02d}",
        "source": f"text layer, page {page_number}: '{m.group(0)}'",
        "status": "tentative",
    }


def _image_fraction(page):
    area = abs(page.rect)
    covered = 0.0
    for info in page.get_image_info():
        covered += abs(pymupdf.Rect(info["bbox"]) & page.rect)
    return min(covered / area, 1.0) if area else 0.0


def ocr_page(page, tessdata_dir=None, lang="fra", dpi=300):
    """OCR one page. Returns text, a sparse-mode variant, and confidence stats."""
    if tessdata_dir:
        os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    data = pytesseract.image_to_data(
        img, lang=lang, config="--psm 3", output_type=pytesseract.Output.DICT)
    confs = [int(float(c)) for w, c in zip(data["text"], data["conf"])
             if w.strip() and float(c) >= 0]
    return {
        "text": pytesseract.image_to_string(img, lang=lang, config="--psm 3"),
        # Sparse mode (psm 11) found far more figures on a table image in our
        # one test, but it does not keep rows and columns together.
        "text_sparse": pytesseract.image_to_string(img, lang=lang, config="--psm 11"),
        "mean_conf": round(sum(confs) / len(confs), 1) if confs else None,
        "min_conf": min(confs) if confs else None,
        "low_word_fraction": (round(sum(c < LOW_WORD_CONF for c in confs) / len(confs), 3)
                              if confs else None),
        "words": len(confs),
    }


def _tesseract_version():
    try:
        out = subprocess.run(["tesseract", "--version"], capture_output=True,
                             text=True).stdout
        return out.splitlines()[0] if out else None
    except OSError:
        return None


def extract_pdf(path, source_url, retrieved_at, tessdata_dir=None, lang="fra"):
    with open(path, "rb") as fh:
        raw = fh.read()
    doc = pymupdf.open(stream=raw, filetype="pdf")
    pages, first_text = [], ""
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        fraction = round(_image_fraction(page), 3)
        entry = {
            "page": i,
            "page_url": f"{source_url}#page={i}",
            "image_area_fraction": fraction,
        }
        if page_needs_ocr(text, fraction):
            ocr = ocr_page(page, tessdata_dir, lang)
            weak = (ocr["mean_conf"] is None or ocr["mean_conf"] < REVIEW_MEAN_CONF
                    or (ocr["low_word_fraction"] or 0) > REVIEW_LOW_WORD_FRACTION)
            entry.update({
                "method": "tesseract",
                "status": "needs_review" if weak else "machine_read",
                "text": ocr["text"],
                "text_sparse": ocr["text_sparse"],
                "ocr": {k: ocr[k] for k in
                        ("mean_conf", "min_conf", "low_word_fraction", "words")},
                "note": OCR_NOTE,
            })
        else:
            entry.update({
                "method": "text_layer",
                "status": "machine_extracted",
                "text": text,
                "note": IMAGE_TEXT_LAYER_NOTE if fraction >= IMAGE_HEAVY_FRACTION else None,
            })
        if i == 1:
            first_text = entry["text"]
        pages.append(entry)
    return {
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "page_count": len(pages),
        "extractor": {
            "pymupdf": pymupdf.__version__,
            "tesseract": _tesseract_version(),
            "ocr_model": f"{lang} (tessdata_best)",
        },
        "meeting_date": find_meeting_date(first_text),
        "pages": pages,
    }
