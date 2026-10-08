"""Text extraction for minutes that were published as web pages (HTML) or RTF files rather than PDFs.

Returns the same shape as `extract.extract_pdf`, so the record, render and verify steps need no
special case. There is one "page" (the whole document); its method says how the text was obtained.
No OCR is involved: the text is what the document contains, with layout reduced to paragraphs.
"""
import hashlib
import re

from bs4 import BeautifulSoup

from .extract import find_meeting_date

_SKIP_GROUPS = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "generator",
                "listtable", "listoverridetable", "revtbl", "rsidtbl", "themedata", "colorschememapping",
                "latentstyles", "datastore", "xmlnstbl", "fldinst"}
_RTF_TOKEN = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([\\{}~_\-*])|([{}])|([^\\{}]+)", re.S)


def rtf_to_text(data):
    """Plain text from RTF bytes. Handles paragraphs, tabs, \\'hh (Windows-1252) and \\uN escapes."""
    src = data.decode("latin-1")
    out, stack, skip_depth, uc_skip = [], [], None, 0
    for m in _RTF_TOKEN.finditer(src):
        word, num, hexa, sym, brace, text = m.groups()
        if brace == "{":
            stack.append(skip_depth)
        elif brace == "}":
            if stack:
                prev = stack.pop()
                if skip_depth is not None and prev is None:
                    skip_depth = None
        elif sym is not None:
            if sym == "*" and skip_depth is None:
                skip_depth = len(stack)
            elif skip_depth is None:
                out.append({"~": "\u00a0", "_": "-", "-": ""}.get(sym, sym))
        elif hexa is not None:
            if skip_depth is None:
                if uc_skip:
                    uc_skip -= 1
                else:
                    out.append(bytes([int(hexa, 16)]).decode("cp1252", "replace"))
        elif word is not None:
            if word in _SKIP_GROUPS and skip_depth is None:
                skip_depth = len(stack)
            elif skip_depth is not None:
                continue
            elif word in ("par", "line", "sect", "page"):
                out.append("\n")
            elif word == "tab":
                out.append("\t")
            elif word == "u" and num is not None:
                code = int(num)
                out.append(chr(code + 65536 if code < 0 else code))
                uc_skip = 1
            elif word == "emdash":
                out.append("\u2014")
            elif word == "endash":
                out.append("\u2013")
            elif word in ("lquote", "rquote"):
                out.append("\u2019")
        elif text is not None and skip_depth is None:
            if uc_skip:
                text, uc_skip = text[uc_skip:], max(0, uc_skip - len(text))
            out.append(text.replace("\r", "").replace("\n", ""))
    return _tidy("".join(out))


def _tidy(text):
    # Word exported some right single quotes as the control character U+0019; that is what it stands for.
    text = text.replace("\x19", "\u2019")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"(?<=\bL)\n(?=\u2019)", "", text)      # a line break inside "L’an"
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")]
    out, blank = [], False
    for l in lines:
        if l:
            out.append(l)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip() + "\n"


def html_to_text(data):
    """Visible text of an HTML page as paragraphs; scripts, styles and navigation images are dropped."""
    try:
        data = data.decode("utf-8")
    except UnicodeDecodeError:
        data = data.decode("cp1252", "replace")   # 2003 pages are Windows-1252; the curly apostrophe is 0x92
    soup = BeautifulSoup(data, "lxml")
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table", "ul", "ol", "blockquote"]):
        block.insert_before("\n")
        block.insert_after("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.insert_after(" ")
    return _tidy(soup.get_text())


def _extract(raw, source_url, retrieved_at, method, text):
    return {
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "page_count": 1,
        "extractor": {"method": method, "note": "text taken from the document itself; no OCR"},
        "meeting_date": find_meeting_date(text),
        "pages": [{"page": 1, "page_url": source_url, "method": method, "status": "machine_extracted",
                   "text": text, "note": "Layout is reduced to paragraphs; check the original for tables."}],
    }


def extract_html(path, source_url, retrieved_at, tessdata_dir=None):
    raw = open(path, "rb").read()
    return _extract(raw, source_url, retrieved_at, "html_text", html_to_text(raw))


def extract_rtf(path, source_url, retrieved_at, tessdata_dir=None):
    raw = open(path, "rb").read()
    return _extract(raw, source_url, retrieved_at, "rtf_text", rtf_to_text(raw))
