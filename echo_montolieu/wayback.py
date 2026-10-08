"""Minutes that are no longer on the Mairie's site, recovered from the Internet Archive.

The Wayback Machine's own CDX index lists the document files captured under montolieu.fr
(one request). The council minutes among them are downloaded politely (the project's usual
fetcher: spaced requests, hard stop on errors), kept as originals in `archive/originals/`
so they are easy to open, and extracted like any other minutes. The *official* copy is the
Wayback capture: each record's `source_url` is the timestamped web.archive.org address, and
the local copy is a convenience whose SHA-256 can be checked against the record.
"""
import json
import re
import shutil
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import requests

from .extract import extract_pdf
from .fetch import USER_AGENT, StopFetching
from .sync import _first_version, _load

CDX_URL = "https://web.archive.org/cdx/search/cdx"
DOMAIN = "montolieu.fr"
MIRROR_BASE = "https://github.com/mgifford/EchoDeMontolieu/blob/main/archive/originals/"
# Minutes of the old site were named CRCM<date>.pdf (compte rendu du conseil municipal).
_MINUTES = re.compile(r"/docs/CRCM[^/]*\.(pdf|doc)$", re.I)


def fetch_captures(session=None):
    """One request to the documented CDX API: document files captured under the domain."""
    s = session or requests.Session()
    resp = s.get(CDX_URL, headers={"User-Agent": USER_AGENT, "Connection": "close"}, timeout=90, params=[
        ("url", DOMAIN), ("matchType", "domain"), ("filter", "statuscode:200"),
        ("filter", "mimetype:application/(pdf|msword)"), ("collapse", "urlkey"),
        ("fl", "timestamp,original,mimetype,length"), ("output", "json")])
    if resp.status_code == 429 or resp.status_code >= 500:
        raise StopFetching(f"{resp.status_code} from the Wayback CDX API")
    resp.raise_for_status()
    rows = resp.json()[1:]
    return [{"timestamp": t, "original": o, "mimetype": m, "length": l} for t, o, m, l in rows]


def date_hint(filename):
    """A guess at the meeting date from the file name, as ISO text, or None.

    Only a hint to cross-check against the document: names were typed by hand (CRCM02032004,
    CRCM140504, CRCM 20060505) and the text of the minutes stays the authority.
    """
    digits = re.sub(r"\D", "", Path(unquote(filename)).stem)
    try:
        if len(digits) == 8 and digits[:2] in ("19", "20"):
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
        if len(digits) == 8:
            return date(int(digits[4:]), int(digits[2:4]), int(digits[:2])).isoformat()
        if len(digits) == 6:
            return date(2000 + int(digits[4:]), int(digits[2:4]), int(digits[:2])).isoformat()
    except ValueError:
        return None
    return None


def choose_minutes(captures):
    """One entry per meeting: the minutes files, PDF preferred over Word, earliest capture."""
    best = {}
    for c in captures:
        if not _MINUTES.search(c["original"]):
            continue
        name = unquote(c["original"].rsplit("/", 1)[-1])
        key = re.sub(r"\.(pdf|doc)$", "", name, flags=re.I).replace(" ", "").lower()
        is_pdf = c["mimetype"] == "application/pdf"
        old = best.get(key)
        if old is None or (is_pdf and old["mimetype"] != "application/pdf"):
            best[key] = c
    out = []
    for key, c in sorted(best.items()):
        name = unquote(c["original"].rsplit("/", 1)[-1]).replace(" ", "")
        out.append({**c, "name": name, "date_hint": date_hint(name),
                    "wayback_url": f"https://web.archive.org/web/{c['timestamp']}/{c['original']}",
                    "raw_url": f"https://web.archive.org/web/{c['timestamp']}id_/{c['original']}"})
    return out


def sync_wayback(fetcher, private_dir, archive_dir, items, tessdata_dir=None, limit=None, extract=extract_pdf):
    """Download, mirror and extract the PDF items not yet in the private index."""
    private, originals = Path(private_dir), Path(archive_dir) / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    (private / "extractions").mkdir(parents=True, exist_ok=True)
    index_path = private / "index.json"
    index = _load(index_path, {})
    report = {"new": [], "skipped": [], "failed": [], "word_only": [], "stopped": None}
    todo = []
    for it in items:
        if it["mimetype"] != "application/pdf":
            report["word_only"].append(it["wayback_url"])
        elif it["wayback_url"] in index and "error" not in index[it["wayback_url"]]:
            report["skipped"].append(it["wayback_url"])
        else:
            todo.append(it)
    for it in todo[:limit]:
        key = it["wayback_url"]
        try:
            fetched = fetcher.get(it["raw_url"], revalidate=False)
            head = fetched.path.read_bytes()[:5]
            if head != b"%PDF-":
                raise ValueError(f"not a PDF (starts {head!r})")
            mirror = originals / it["name"]
            shutil.copyfile(fetched.path, mirror)
            result = extract(fetched.path, key, fetched.retrieved_at, tessdata_dir=tessdata_dir)
            out = private / "extractions" / (Path(it["name"]).stem + ".json")
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            entry = _first_version({"filename": it["name"], "draft_suspected": False}, result, fetched,
                                   str(out.relative_to(private)))
            entry["origin"] = {
                "kind": "wayback", "original_url": it["original"], "wayback_timestamp": it["timestamp"],
                "official_copy": key, "mirror_path": f"archive/originals/{it['name']}",
                "mirror_url": MIRROR_BASE + it["name"], "date_hint_from_filename": it["date_hint"]}
            index[key] = entry
            report["new"].append(key)
        except StopFetching as exc:
            report["stopped"] = repr(exc)
            break
        except Exception as exc:  # recorded and surfaced, never silent
            index[key] = {"filename": it["name"], "error": repr(exc)}
            report["failed"].append({"url": key, "error": repr(exc)})
        finally:
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    report["exit_code"] = 2 if report["stopped"] else 1 if report["failed"] else 0
    return report
