"""Command line: python -m echo_montolieu
{list,sync,extract,publish-record,verify,keygen,redact,status,approve,publish,unpublish,whois} ..."""
import argparse
import json
import sys
from datetime import datetime, timezone

from .extract import extract_pdf
from .fetch import PoliteFetcher
from pathlib import Path

from . import publish as pub
from . import verify
from .minutes import INDEX_URL, parse_minutes_index
from .privacy import PublicFigures, Pseudonymiser, redact_extraction
from .record import publish_record
from .sync import sync


def main(argv=None):
    ap = argparse.ArgumentParser(prog="echo_montolieu")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list minutes PDFs (one polite request)")
    p_list.add_argument("--cache", default=".cache")

    p_sync = sub.add_parser(
        "sync", help="fetch new minutes politely and extract them to the private folder")
    p_sync.add_argument("--cache", default=".cache")
    p_sync.add_argument("--private", default="private")
    p_sync.add_argument("--tessdata", default=None)
    p_sync.add_argument("--limit", type=int, default=None, help="max new PDFs this run")
    p_sync.add_argument("--delay", type=float, default=10.0, help="seconds between requests")
    p_sync.add_argument("--dry-run", action="store_true", help="list new PDFs, download none")

    p_key = sub.add_parser("keygen", help="create private/pseudonym.key (never printed)")
    p_key.add_argument("--private", default="private")

    p_red = sub.add_parser(
        "redact", help="pseudonymise names in a private extraction (stays withheld)")
    p_red.add_argument("extraction", help="a file from private/extractions/")
    p_red.add_argument("--private", default="private")
    p_red.add_argument("--scope", choices=["document", "global"], default="document")
    p_red.add_argument("--figures", default="data/public_figures.json",
                       help="allow-list of people who may be named (missing file = nobody)")

    p_rec = sub.add_parser(
        "publish-record",
        help="publish the faithful, unredacted record (page text and links) to public/minutes")
    p_rec.add_argument("--private", default="private")
    p_rec.add_argument("--public", default="public")
    p_rec.add_argument("--no-text", action="store_true",
                       help="metadata and page links only")

    p_ver = sub.add_parser(
        "verify", help="check a record's PDF hash, against a local file or the site")
    p_ver.add_argument("document_id")
    p_ver.add_argument("--file", default=None, help="local PDF to compare (offline)")
    p_ver.add_argument("--public", default="public")
    p_ver.add_argument("--cache", default=".cache")

    p_st = sub.add_parser("status", help="state of each redacted document")
    p_st.add_argument("--private", default="private")
    p_st.add_argument("--public", default="public")

    p_app = sub.add_parser("approve", help="record your review of one redacted document")
    p_app.add_argument("stem", help="file name without .json, from private/redacted/")
    p_app.add_argument("--reviewer", required=True)
    p_app.add_argument("--withhold-pages", default="", help="comma-separated page numbers")
    p_app.add_argument("--accept-pages", default="",
                       help="comma-separated needs_review pages you accept as they are")
    p_app.add_argument("--note", default="")
    p_app.add_argument("--private", default="private")

    p_pub = sub.add_parser("publish", help="publish approved, unchanged documents to public/")
    p_pub.add_argument("--private", default="private")
    p_pub.add_argument("--public", default="public")
    p_pub.add_argument("--figures", default="data/public_figures.json")
    p_pub.add_argument("--no-text", action="store_true",
                       help="publish metadata and page links only, without page text")

    p_unp = sub.add_parser("unpublish", help="remove a document from public/ and revoke approval")
    p_unp.add_argument("stem")
    p_unp.add_argument("--private", default="private")
    p_unp.add_argument("--public", default="public")

    p_who = sub.add_parser("whois", help="maintainer only: resolve an M- or P- id")
    p_who.add_argument("identifier")
    p_who.add_argument("--private", default="private")

    p_ext = sub.add_parser("extract", help="extract a local PDF with provenance")
    p_ext.add_argument("pdf")
    p_ext.add_argument("--url", required=True, help="the PDF's original URL")
    p_ext.add_argument("--retrieved-at", default=None)
    p_ext.add_argument("--tessdata", default=None)
    p_ext.add_argument("--out", default="-")

    args = ap.parse_args(argv)
    if args.cmd == "list":
        fetched = PoliteFetcher(args.cache).get(INDEX_URL)
        items = parse_minutes_index(fetched.path.read_text(encoding="utf-8"))
        json.dump({"index_url": INDEX_URL, "retrieved_at": fetched.retrieved_at,
                   "count": len(items), "items": items},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    elif args.cmd == "keygen":
        path = Pseudonymiser.generate_key_file(args.private)
        print(f"Key written to {path} (mode 600). Back it up: without it, new documents "
              "get new ids for people already in the registry.")
    elif args.cmd == "redact":
        pseud = Pseudonymiser.from_environment(args.private)
        extraction = json.loads(Path(args.extraction).read_text(encoding="utf-8"))
        red = redact_extraction(extraction, pseud, args.scope,
                                PublicFigures.load(args.figures))
        out_dir = Path(args.private) / "redacted"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / Path(args.extraction).name
        out.write_text(json.dumps(red, ensure_ascii=False, indent=2), encoding="utf-8")
        # Counts only: never print names.
        print(json.dumps({"written": str(out), **red["privacy"]}, indent=2))
    elif args.cmd == "publish-record":
        report = publish_record(args.private, args.public, include_text=not args.no_text)
        print(json.dumps({"published": report["published"],
                          "skipped_failed": report["skipped_failed"]}, indent=2))
        sys.exit(1 if report["skipped_failed"] else 0)
    elif args.cmd == "verify":
        record = verify.load_record(args.public, args.document_id)
        if args.file:
            result = verify.verify_local(record, args.file)
        else:
            result = verify.verify_online(record, PoliteFetcher(args.cache))
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["match"] else 1)
    elif args.cmd == "status":
        print(json.dumps(pub.status(args.private, args.public), indent=2))
    elif args.cmd == "approve":
        ints = lambda s: [int(x) for x in s.split(",") if x.strip()]  # noqa: E731
        try:
            rec = pub.approve(args.private, args.stem, args.reviewer,
                              ints(args.withhold_pages), ints(args.accept_pages), args.note)
        except pub.PublishError as exc:
            print(f"not approved: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(rec, indent=2))
    elif args.cmd == "publish":
        report = pub.publish(args.private, args.public, PublicFigures.load(args.figures),
                             include_text=not args.no_text)
        print(json.dumps(report, indent=2))
        sys.exit(1 if report["blocked"] else 0)
    elif args.cmd == "unpublish":
        try:
            print(json.dumps(pub.unpublish(args.private, args.public, args.stem)))
        except pub.PublishError as exc:
            print(f"not unpublished: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.cmd == "whois":
        print(json.dumps(Pseudonymiser.from_environment(args.private).whois(args.identifier),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "sync":
        report = sync(PoliteFetcher(args.cache, min_delay=args.delay), args.private,
                      tessdata_dir=args.tessdata, limit=args.limit, dry_run=args.dry_run)
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
        sys.exit(report["exit_code"])
    else:
        when = args.retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        result = extract_pdf(args.pdf, args.url, when, tessdata_dir=args.tessdata)
        out = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
        json.dump(result, out, ensure_ascii=False, indent=2)
        out.write("\n")


if __name__ == "__main__":
    main()
