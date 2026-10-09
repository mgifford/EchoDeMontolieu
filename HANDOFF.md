# Handoff note

> **AI disclosure.** Written by an AI assistant (Claude, from Anthropic) at the maintainer's direction, to let a new session or the maintainer continue. Not independently reviewed. See [AI.md](AI.md).

Date of this note: 2026-10-09 (end of the long build session). Owner: Mike Gifford.

## What this is

L'Écho de Montolieu: a trilingual (fr/en/nl) civic signpost and record of the council minutes of Montolieu (Aude, France).

- Site: https://mgifford.github.io/EchoDeMontolieu/ (GitHub Pages, built by `build_site.py` / `echo_montolieu/site.py`).
- API, MCP server and landing: Hugging Face Space `mgifford/EchoDeMontolieu` (`app.py`, Docker).
- Conventions: `AI.md` (who produced what), `ACCESSIBILITY.md` (WCAG 2.2 AA, 44 px targets), `README.md`. No em dashes or emojis in prose. Ask before removing functionality. Code is AGPL-3.0; the derived data in `public/data/` is under the Licence Ouverte 2.0 (Etalab).

## State right now

- Everything built so far is merged to `main`, except the pull request that carries this note (#33, a fix for the map pages' accessibility audit plus this handoff). **Merge #33.** After that nothing is open.
- Workflows on `main`: *Deploy GitHub Pages*, *Sync to Hugging Face Space* (on every push), *Accessibility audit* (axe, on push and pull requests; was red from #28 until #33), *Generate summaries and translations* (manual), *Watch for new minutes* (weekly, opens an issue).
- Tests: 354 pass, 1 skipped. The accessibility audit passed on #33 (run 38); locally `tools/a11y_check.cjs` reports 0 axe violations on the three map pages and the open-data page.
- Content: 57 meetings in the record (25 current, 32 recovered from the Internet Archive for 2003-2008; none found for 2009-2023, the maintainer is asking the Mairie). Model summaries exist for 13 of the 25 current meetings. 13 places are confirmed on the map.

## What the maintainer must do (nobody else can)

1. **Merge #33.**
2. **Fix the Hugging Face token for the workflow.** The repository secret `HF_TOKEN` is a Space-write token. The *Generate summaries and translations* run on 2026-10-09 stopped at its preflight with `403 ... not sufficient permissions to call Inference Providers`; nothing was spent. Create a fine-grained token with "Make calls to Inference Providers" and save it as the secret `HF_TOKEN` (or add the permission to the existing one).
3. **Turn on** Settings > Actions > General > "Allow GitHub Actions to create and approve pull requests" (the generate workflow opens a PR).
4. **Run the workflow** (Actions tab > Generate summaries and translations > Run workflow; works from the phone app; defaults are fine, cap 2 USD; tick geocode and zoning). It writes the 12 missing summaries, English and Dutch translations, English and Dutch for the 2003-2008 decisions pages, the "In short" paragraph on What's new, new map pins and the zoning snapshot, then opens a PR. **Read a sample before merging.** Estimated cost: well under 1 USD.
5. **Read a sample of `public/meetings/200[3-8]*/facts.md`** (the 2003-2008 decisions pages): names are masked by rules and over-masked on purpose, but a lowercase third-party surname that is on no attendance list could get through.
6. **Native-speaker review** of the French and Dutch wording (interface text, map text, What's new, open-data page, glossary in `echo_montolieu/translate.py`).
7. **Licence check on model output:** the summaries are written by AI models (Qwen, Gemma) under their own terms; read them for any limit on reusing output, and consider a quick legal look at the Etalab choice.
8. **Confirm the MCP server works** once the Space has rebuilt: connect a client to `https://mgifford-echodemontolieu.hf.space/mcp`. If the host check refuses it, set the Space variable `ECHO_MCP_HOSTS`.
9. Ask the Mairie for the 2009-2023 minutes (the maintainer said they will).

## Laptop checklist (things a cloud session or GitHub cannot do)

What lives only on the laptop (git-ignored on purpose): `private/` (unredacted extractions, version history of every document, name registry), `.cache/` (downloaded PDFs, model cache), Tesseract language data (`tessdata/`, pass `--tessdata`), `trials/`, the `hf auth login` credential.

Setup: `git pull`, `pip install -r requirements.txt`, Tesseract with French data. Work on a branch and open a PR; never push to `main`.

In this order:

1. **New minutes** (the weekly watch opens an issue labelled `new-minutes` when there are some; or run `python -m echo_montolieu.watch`):
   `python -m echo_montolieu sync` (polite, 10 s apart, extracts to `private/`), then `python -m echo_montolieu publish-record`, then `python -m echo_montolieu render`. Then run the generate workflow for the new meeting. Do the import on the laptop, not in CI: the version history is in `private/`.
2. **Retry the two 2003 meetings** the Internet Archive could not serve (22 March and 27 February 2003): `python -m echo_montolieu wayback`.
3. **Places and zoning** if the workflow's lookups were not used: `python -m echo_montolieu geocode`, `python -m echo_montolieu zoning`, then `render`. The zoning endpoints and field names were written from memory of the IGN APICarto docs and have **never run against the live portal**: read the "Gaps" section of `public/zoning/index.md` and fix names that do not match. Servitudes d'utilité publique (monument perimeters) are not fetched yet.
4. **Private tier** (never published, never in CI): `python -m echo_montolieu build-db --private` writes `private/echo-private.db` (faithful text with names, FTS5, and a `parcels` table: 42 references found so far); `python -m echo_montolieu search --private "query"`; `python -m echo_montolieu parcel-map` asks the IGN cadastre API for each parcel (one request each, 2 s apart, cached) and writes `private/parcels.html`. **Not yet run against the real IGN API.** Check a few parcels against the original pages (OCR can misread a reference); confirm that one-letter sections are padded as the cadastre does ("C" becomes "0C").
5. Before any PR from the laptop: `python -m pytest -q`, grep the generated pages for sale details (parcel, street, notary terms), and check `git status` shows nothing from `private/` or `.cache/`.

## Decisions already made (do not re-ask)

- Faithful record publishes names (public record). Derived summaries may name elected officials on the attendance list; other private names are replaced; property sales are counts only.
- Search, the MCP server and the open data read the **derived** layer only. Never the faithful text.
- The maintainer wants faithful detail available **privately** (faithful-text search, and the map of sale parcels) without making it more public or searchable. Output only to `private/`.
- PDFs of recovered minutes stay on GitHub in `archive/originals/`; the Internet Archive capture is the official `source_url`. Binary files must never go to the Space.
- Be polite to small servers: at least 10 s between requests, robots.txt, hard stop on 429/5xx or network errors.
- Open data licence: Licence Ouverte 2.0 (Etalab), credit the source and the date. Code stays AGPL-3.0.
- Models write only summaries, translations and the "In short" paragraph; facts come from rules. Everything model-written is labelled and marked unreviewed. Full 2003-2008 minutes are never sent to a model (only the scrubbed decision sentences).
- The home page lists only the last 12 months of meetings; the Meetings page has all of them.

## Where things are

- **Pipeline:** `sync.py`, `extract.py`, `record.py`/`publish.py` (faithful record into `public/minutes/`), `render.py` (meeting pages), `threads.py` (issues over time), `finance.py`, `places.py` (BAN geocoding, the map in three languages), `zoning.py`, `whats_new.py` (What's new data and the model paragraph), `export.py` (open data), `archive_digest.py` / `archive_translate.py` (2003-2008), `generate.py` (summaries and translations), `watch.py` (new-minutes check), `private_db.py` / `parcel_map.py` (private tier), `mcp_server.py`, `db.py` (public search database), `site.py` (static site in fr/en/nl).
- **Commands:** `python -m echo_montolieu --help`.
- **Workflows:** `.github/workflows/` (see above). `tests/test_workflows.py` checks that none uses `pull_request_target`, none prints a secret, and that the generate and watch workflows keep inputs out of shell scripts.
- **Site builder dependency rule:** `build_site.py` must import only `markdown-it-py` and the standard library (the Pages and audit workflows install nothing else). `tests/test_build_site.py` enforces it; breaking it silently stopped the deploy once (#21 to #25).

## Known issues and risks

- Translations are not rated by a human; automatic checks catch changed numbers, lost name tokens, wrong language and implausible length only.
- The model result cache (`.cache/model_cache.json`) is kept between workflow runs by the Actions cache, and is not committed.
- A model's provider is chosen by Hugging Face; one provider returned 500 errors during the trial and another was used.
- The weekly watch may be refused by the Mairie's site from GitHub's servers (the job then fails and GitHub tells you); it uses one request.
- GitHub pauses scheduled workflows after 60 days without repository activity.
- Old versions of `facts.md` in git history contain one parcel reference from a sale title (fixed going forward in #14).
- GitHub's own view of the minutes' contents lists has broken anchors (the website fixes this).
- Automated accessibility checks cover part of WCAG; screen readers and zoom are untested by a person.
- A pull request opened by a workflow does not start other workflows (a GitHub rule); run Pages and the audit by hand if wanted.

## Working agreements for the next session

- Pull request habits that went wrong once: do not push more commits to a branch after the maintainer says it is merged (they are lost; the branch is deleted on merge); start each piece of work from a fresh `origin/main`; run the full tests and read the result before committing.
- Check the Actions tab after a merge: a red audit or deploy is work, not noise.
- Build the site in a clean environment with only `markdown-it-py` before claiming the site builds.
- Hugging Face, the Mairie's site, the Internet Archive, the BAN, IGN and unpkg.com are not reachable from a cloud session; anything that depends on them is untested until run on the laptop or in a workflow.

## Suggested start of the next session

Read this file, `AI.md` and `README.md`; list the open pull requests and the latest workflow runs; then ask which of "What the maintainer must do" is done. Suggested tier: the same model for anything privacy-sensitive (private tier, scrubbing rules); a smaller model is enough for workflow and documentation edits.

## AI assistance and provenance

AI-assisted: yes (Claude through Claude Code). External code copied: no. Sources consulted: the Mairie's site, the Internet Archive (CDX API and captures), the national address database (BAN), the Hugging Face and IGN API documentation, Tesseract tessdata_best, the Etalab licence page (from memory, not checked).
