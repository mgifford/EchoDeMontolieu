"""Turn extracted PDF page text into clean lines, headings and paragraphs.

Nothing here rewrites content. It removes page-number lines, tidies whitespace,
joins hard-wrapped lines into paragraphs, and recognises headings and
number-heavy table lines. The extracted JSON stays the untouched record.
"""
import re

BULLET_RE = re.compile(r"^\s*(?:[-–—•➢►▪>*]|\d{1,2}[.)])\s+")
SENTENCE_END = (".", ":", ";", "!", "?", ")", "»", "”", '"')


def clean_page_lines(text, page):
    """Lines of one page without blank noise and without its own page number."""
    lines = [re.sub(r"[ \t ]+", " ", l).strip() for l in (text or "").splitlines()]
    out, seen_content = [], 0
    for l in lines:
        if not l:
            out.append("")
            continue
        seen_content += 1
        if seen_content <= 3 and l == str(page):
            continue  # the page number printed at the top of the page
        out.append(l)
    return out


def is_heading(line):
    """ALL-CAPS line with at least two words and mostly letters (not a number row)."""
    s = line.strip()
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 8 or len(s) > 140:
        return False
    if sum(c.isupper() for c in letters) / len(letters) < 0.85:
        return False
    if len(re.findall(r"[A-Za-zÀ-ÿ]{2,}", s)) < 2:
        return False
    return sum(c.isdigit() for c in s) <= len(letters)


AMOUNT_RE = re.compile(r"-?\d{1,3}(?: \d{3})+(?:,\d+)?|-?\d+,\d+")


def is_table_line(line):
    """Number-heavy line (a row of a budget table), not prose.

    Dates, times and "n° 12" do not count: only thousands-grouped or decimal
    amounts do, so "La séance est ouverte à 19h04" stays prose.
    """
    s = line.strip()
    if not s:
        return False
    ratio = sum(c.isdigit() for c in s) / len(s)
    has_word = any(len(w) >= 4 for w in re.findall(r"[A-Za-zÀ-ÿ]+", s))
    return (ratio > 0.5 or (ratio > 0.3 and not has_word)
            or (len(AMOUNT_RE.findall(s)) >= 2 and len(s) < 100))


def sentence_case(heading):
    """ALL CAPS heading to sentence case, for reading only."""
    s = heading.strip().lower()
    s = re.sub(r"(^|[:–-]\s+)([a-zà-ÿ])", lambda m: m.group(1) + m.group(2).upper(), s)
    return s[:1].upper() + s[1:]


def _starts_bullet(line):
    return bool(BULLET_RE.match(line))


def _is_caps_word_line(line):
    letters = [c for c in line if c.isalpha()]
    return (len(letters) >= 4 and len(line.split()) <= 3 and not any(c.islower() for c in letters)
            and not any(c.isdigit() for c in line))


def _is_title_like(buf):
    return (len(buf) == 1 and len(buf[0]) < 50 and not buf[0].endswith(SENTENCE_END + (",",))
            and buf[0][:1].isupper() and 1 <= len(buf[0].split()) <= 6)


def paragraphs(lines_with_pages):
    """Group (line, page) pairs into blocks.

    Returns a list of dicts:
    {"kind": "paragraph"|"bullet"|"heading"|"subheading"|"table", "text", "page"}.
    Hard-wrapped lines are joined; blank lines, bullets, headings and table rows
    start new blocks. Consecutive table rows become one table block.
    """
    blocks, buf, buf_page = [], [], None

    def flush():
        nonlocal buf, buf_page
        if buf:
            blocks.append({"kind": "paragraph", "text": " ".join(buf), "page": buf_page})
        buf, buf_page = [], None

    after_blank = True
    for line, page in lines_with_pages:
        if not line:
            flush()
            after_blank = True
            continue
        was_after_blank, after_blank = after_blank, False
        if (not was_after_blank and not buf and blocks and blocks[-1]["kind"] == "heading"
                and _is_caps_word_line(line)):
            blocks[-1]["text"] += " " + line  # a heading wrapped onto a second line
            continue
        if is_heading(line):
            flush()
            blocks.append({"kind": "heading", "text": line, "page": page})
        elif is_table_line(line):
            flush()
            if blocks and blocks[-1]["kind"] == "table":
                blocks[-1]["text"] += "\n" + line
            else:
                blocks.append({"kind": "table", "text": line, "page": page})
        elif _starts_bullet(line):
            if _is_title_like(buf):
                blocks.append({"kind": "subheading", "text": " ".join(buf), "page": buf_page})
                buf, buf_page = [], None
            flush()
            blocks.append({"kind": "bullet", "text": BULLET_RE.sub("", line, count=1), "page": page})
        else:
            if buf and line[:1].isupper() and _is_title_like(buf):
                # a short title with no end punctuation ("Secrétariat de séance")
                blocks.append({"kind": "subheading", "text": " ".join(buf), "page": buf_page})
                buf, buf_page = [], None
            elif buf and buf[-1].endswith(SENTENCE_END) and line[:1].isupper() and len(buf[-1]) < 70:
                flush()  # a short finished line followed by a capital starts a new paragraph
            if not buf:
                buf_page = page
            buf.append(line)
    flush()
    return blocks
