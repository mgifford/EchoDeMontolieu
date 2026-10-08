"""Command line: python -m echo_montolieu
{list,sync,wayback,history,extract,publish-record,render,translate-trial,generate,verify,keygen,redact,status,approve,publish,unpublish,whois} ..."""
import argparse
import json
import sys
from datetime import datetime, timezone

from .extract import extract_pdf
from .fetch import PoliteFetcher, StopFetching
from pathlib import Path

from . import publish as pub
from . import verify
from .minutes import INDEX_URL, parse_minutes_index
from .privacy import PublicFigures, Pseudonymiser, redact_extraction
from .record import publish_record
from .render import render_all
from .sync import sync


def main(argv=None):
    ap = argparse.ArgumentParser(prog="echo_montolieu")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list minutes PDFs (one polite request)")
    p_list.add_argument("--cache", default=".cache")

    p_wb = sub.add_parser(
        "wayback", help="recover minutes missing from the live site from the Internet Archive")
    p_wb.add_argument("--cache", default=".cache")
    p_wb.add_argument("--private", default="private")
    p_wb.add_argument("--archive", default="archive", help="folder for the mirrored originals")
    p_wb.add_argument("--captures", default="data/wayback_captures.json",
                      help="saved CDX listing; fetched (one request) if missing or with --refresh")
    p_wb.add_argument("--refresh", action="store_true")
    p_wb.add_argument("--tessdata", default=None)
    p_wb.add_argument("--limit", type=int, default=None)
    p_wb.add_argument("--delay", type=float, default=10.0)
    p_wb.add_argument("--dry-run", action="store_true", help="list what would be downloaded")

    p_hist = sub.add_parser(
        "history", help="machine-readable history across all minutes (private folder unless --public-out)")
    p_hist.add_argument("--public", default="public")
    p_hist.add_argument("--out", default="private/history")

    p_sync = sub.add_parser(
        "sync", help="fetch new minutes politely and extract them to the private folder")
    p_sync.add_argument("--cache", default=".cache")
    p_sync.add_argument("--private", default="private")
    p_sync.add_argument("--tessdata", default=None)
    p_sync.add_argument("--limit", type=int, default=None, help="max new PDFs this run")
    p_sync.add_argument("--delay", type=float, default=10.0, help="seconds between requests")
    p_sync.add_argument("--dry-run", action="store_true", help="list new PDFs, download none")
    p_sync.add_argument("--no-check-changes", action="store_true",
                        help="do not re-check known PDFs for new versions (saves one request each)")

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
    p_ver.add_argument("--version", type=int, default=None,
                       help="check an older version (use with --file)")
    p_ver.add_argument("--public", default="public")
    p_ver.add_argument("--cache", default=".cache")

    p_ren = sub.add_parser(
        "render", help="write readable Markdown: minutes, summary and follow-ups per meeting")
    p_ren.add_argument("--public", default="public")

    p_tr = sub.add_parser(
        "translate-trial", help="compare translation models on real minutes (use --dry-run first)")
    p_tr.add_argument("--models", nargs="+", default=[
        "google/gemma-3-27b-it", "Qwen/Qwen3-235B-A22B-Instruct-2507"])
    p_tr.add_argument("--langs", nargs="+", default=["en", "nl"])
    p_tr.add_argument("--per-category", type=int, default=4)
    p_tr.add_argument("--max-usd", type=float, default=0.25)
    p_tr.add_argument("--public", default="public")
    p_tr.add_argument("--out", default="trials/translation")
    p_tr.add_argument("--dry-run", action="store_true", help="show the sample and estimated cost, send nothing")

    p_gen = sub.add_parser(
        "generate", help="French summary of each meeting, then English and Dutch of summary and minutes")
    p_gen.add_argument("--summary-model", required=True, help="model that writes the French summary")
    p_gen.add_argument("--translation-model", required=True, help="model that translates")
    p_gen.add_argument("--langs", nargs="+", default=["en", "nl"])
    p_gen.add_argument("--only", nargs="+", default=None, help="meeting folders such as 2026-07-22")
    p_gen.add_argument("--max-usd", type=float, default=1.0, help="hard spending cap")
    p_gen.add_argument("--force", action="store_true", help="rewrite files even if their inputs are unchanged")
    p_gen.add_argument("--public", default="public")
    p_gen.add_argument("--cache", default=".cache/model_cache.json")
    p_gen.add_argument("--dry-run", action="store_true", help="estimate cost, send nothing")

    p_geo = sub.add_parser(
        "geocode", help="look up place names in the national address database (polite; one request per new name)")
    p_geo.add_argument("--public", default="public")
    p_geo.add_argument("--cache", default="data/geocode_cache.json")
    p_geo.add_argument("--delay", type=float, default=1.0)

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
        record = verify.load_record(args.public, args.document_id, args.version)
        if args.file:
            result = verify.verify_local(record, args.file)
        else:
            result = verify.verify_online(record, PoliteFetcher(args.cache))
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["match"] else 1)
    elif args.cmd == "render":
        from . import threads as th
        meetings = th.load_meetings(args.public)
        result = th.build_threads(meetings)
        report, _ = render_all(args.public, th.todo_status(result))
        pages = th.write_topics(args.public, result, meetings)
        from .finance import write_finance
        finance = write_finance(args.public, meetings, result)
        from . import places as pl
        cache = pl.BanGeocoder("data/geocode_cache.json")
        place_info = pl.write_places(args.public, meetings, cache.cached)
        print(json.dumps({"meetings": report["meetings"], "topic_pages": pages, "finance": finance, "places": place_info,
                          "issues_in_several_meetings": sum(1 for t in result["threads"] if t["status"] != "one-off"),
                          "possibly_dropped": sum(1 for t in result["threads"] if t["possibly_dropped"])}, indent=2))
    elif args.cmd == "translate-trial":
        from . import trial
        from .translate import ChatTranslator
        index = json.loads((Path(args.public) / "index.json").read_text(encoding="utf-8"))
        records = [json.loads((Path(args.public) / d["file"]).read_text(encoding="utf-8"))
                   for d in index["documents"]]
        sample = trial.pick_sample(records, args.per_category)
        listing = None
        prices, specs = {}, {}
        for model in args.models:
            price = trial.price_per_million(model, listing)
            prices[model] = price
            # Pin the cheapest live provider so the estimate matches what is billed.
            specs[model] = f"{model}:{price[0]}" if price and ":" not in model else model
        est = trial.estimate(sample, args.langs, prices)
        print(json.dumps({"segments": len(sample), "categories": sorted({s["category"] for s in sample}),
                          "estimate": est, "max_usd": args.max_usd}, indent=2))
        if args.dry_run:
            return
        translators = {m: ChatTranslator(specs[m], cache_path=Path(args.out) / "cache.json") for m in args.models}
        try:
            _, spent = trial.run_trial(sample, args.models, args.langs, translators, prices, args.max_usd, args.out)
        except trial.BudgetExceeded as exc:
            print(f"stopped: {exc}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps({"written": args.out, "spent_usd": round(spent, 5)}, indent=2))
    elif args.cmd == "generate":
        from . import trial
        from .generate import Budget, estimate_generation, generate
        from .translate import ChatModel, ChatTranslator

        def resolve(model):
            price = trial.price_per_million(model)
            return (f"{model}:{price[0]}" if price and ":" not in model else model), price

        summary_spec, summary_price = resolve(args.summary_model)
        translate_spec, translate_price = resolve(args.translation_model)
        est = estimate_generation(args.public, args.langs, summary_price, translate_price)
        est["max_usd"] = args.max_usd
        est["models"] = {"summary": summary_spec, "translation": translate_spec}
        print(json.dumps(est, indent=2))
        if args.dry_run:
            return
        budget = Budget(args.max_usd)
        summarizer = ChatModel(summary_spec, cache_path=Path(args.cache), max_tokens=2500,
                               on_usage=budget.hook(summary_price))
        translator = ChatTranslator(translate_spec, cache_path=Path(args.cache),
                                    on_usage=budget.hook(translate_price))
        report = generate(args.public, summarizer, translator, args.langs, only=args.only, force=args.force)
        report["spent_usd"] = round(budget.spent, 5)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        sys.exit(2 if report["stopped"] else (1 if report["needs_review"] else 0))
    elif args.cmd == "geocode":
        from . import places, threads as th
        meetings = th.load_meetings(args.public)
        found, held_back = places.collect_candidates(meetings)
        geocoder = places.BanGeocoder(args.cache, min_delay=args.delay)
        todo = [q for q in found if geocoder.cached(q) is None]
        print(json.dumps({"candidates": len(found), "to_look_up": len(todo), "held_back_items": held_back}))
        try:
            for query in todo:
                geocoder.lookup(query)
        except StopFetching as exc:
            print(f"stopped: {exc}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps({"requests_made": geocoder.requests_made, "pruned": geocoder.prune(found)}))
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
    elif args.cmd == "history":
        from . import history
        h = history.write(args.public, args.out)
        print(json.dumps(h["coverage"], ensure_ascii=False, indent=2))
    elif args.cmd == "wayback":
        from . import wayback
        cap_path = Path(args.captures)
        if args.refresh or not cap_path.exists():
            captures = wayback.fetch_captures()
            cap_path.parent.mkdir(parents=True, exist_ok=True)
            cap_path.write_text(json.dumps(captures, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            captures = json.loads(cap_path.read_text(encoding="utf-8"))
        items = wayback.choose_minutes(captures)
        if args.dry_run:
            json.dump({"meetings": len(items), "items": [
                {k: i[k] for k in ("name", "date_hint", "mimetype", "wayback_url")} for i in items]},
                sys.stdout, ensure_ascii=False, indent=2)
            print()
            return
        fetcher = PoliteFetcher(args.cache, min_delay=args.delay)
        report = wayback.sync_wayback(fetcher, args.private, args.archive, items,
                                      tessdata_dir=args.tessdata, limit=args.limit)
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
        sys.exit(report["exit_code"])
    elif args.cmd == "sync":
        fetcher = PoliteFetcher(args.cache, min_delay=args.delay,
                                archive_dir=Path(args.private) / "archive")
        report = sync(fetcher, args.private, tessdata_dir=args.tessdata, limit=args.limit,
                      dry_run=args.dry_run, check_changes=not args.no_check_changes)
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
