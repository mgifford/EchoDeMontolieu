"""Has the Mairie published new council minutes? A read-only check.

One request for the Mairie's minutes page (with the project's polite fetcher: descriptive User-Agent, robots.txt,
hard stop on 429 or a server error), compared with the minutes already published here. Nothing is downloaded,
extracted or published: the version history of each document lives in `private/` on the maintainer's computer,
so importing a new PDF is still done there (`sync`, then `publish-record`, then `render`). This check only says
that there is something to import, and which files are no longer on the Mairie's page.

Run by hand, `python -m echo_montolieu.watch`, or by the weekly workflow `watch_minutes.yml`, which opens an issue.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from .fetch import PoliteFetcher, StopFetching
from .minutes import INDEX_URL, parse_minutes_index

TRUSTED_HOST = "www.montolieu.fr"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


def _safe_url(url):
    """The address with only characters that cannot break out of a Markdown link; no query or fragment."""
    p = urlparse(url)
    return urlunparse(("https", p.netloc, quote(p.path, safe="/%._-~+"), "", "", ""))


def known_urls(public_dir):
    """Source addresses of the minutes published here that came from the Mairie's own site (not the Internet Archive)."""
    index = json.loads((Path(public_dir) / "index.json").read_text(encoding="utf-8"))
    return {d["source_url"] for d in index.get("documents", []) if (d.get("source_url") or "").startswith("https://")
            and urlparse(d["source_url"]).netloc == TRUSTED_HOST}


def check(public_dir, fetcher):
    """{checked_at, on_site, known, new: [...], no_longer_listed: [...]}."""
    page = fetcher.get(INDEX_URL)
    items = parse_minutes_index(page.path.read_text(encoding="utf-8"))
    on_site = {i["url"] for i in items}
    known = known_urls(public_dir)
    new = [i for i in items if i["url"] not in known and urlparse(i["url"]).netloc == TRUSTED_HOST]
    return {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "index_url": INDEX_URL,
            "on_site": len(on_site), "known": len(known),
            "new": [{"url": _safe_url(i["url"]), "filename": _SAFE_NAME.sub("", i["filename"])[:120], "draft_suspected": i["draft_suspected"]} for i in new],
            "no_longer_listed": sorted(known - on_site)}


def issue_title(report):
    names = ", ".join(n["filename"] for n in report["new"][:3])
    return f"New minutes on the Mairie's site: {names}{' and more' if len(report['new']) > 3 else ''}"


def issue_markdown(report):
    """The text of the issue. File names and addresses come from the Mairie's page, so they are filtered before they are written."""
    lines = [f"The weekly check of the Mairie's minutes page ({report['index_url']}) on {report['checked_at'][:10]} found "
             f"**{len(report['new'])} file(s) not published here yet**:", ""]
    lines += [f"- [{n['filename'] or 'file'}]({n['url']}){' (looks like a draft)' if n['draft_suspected'] else ''}" for n in report["new"]]
    lines += ["", "Nothing was downloaded or published. To add them, on the maintainer's computer (the version history lives in `private/`):", "",
              "```", "python -m echo_montolieu sync", "python -m echo_montolieu publish-record", "python -m echo_montolieu render", "```", "",
              "Then run the *Generate summaries and translations* workflow for the new meeting(s) and read the result before merging."]
    if report["no_longer_listed"]:
        lines += ["", f"{len(report['no_longer_listed'])} published file(s) are no longer listed on the Mairie's page (moved, renamed or removed); "
                  "the copies already published here are unaffected."]
    lines += ["", "_Written by software; no person has checked it._"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m echo_montolieu.watch", description=__doc__.split("\n\n")[0])
    ap.add_argument("--public", default="public")
    ap.add_argument("--cache", default=".cache/watch")
    ap.add_argument("--delay", type=float, default=10.0)
    ap.add_argument("--report", default=None, help="write the JSON report here")
    ap.add_argument("--issue", default=None, help="write the issue text (and `<path>.title`) here when there is something new")
    args = ap.parse_args(argv)
    try:
        report = check(args.public, PoliteFetcher(args.cache, min_delay=args.delay))
    except (StopFetching, PermissionError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.issue and report["new"]:
        Path(args.issue).write_text(issue_markdown(report), encoding="utf-8")
        Path(args.issue + ".title").write_text(issue_title(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
