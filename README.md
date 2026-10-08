---
title: L'Écho de Montolieu
emoji: 📰
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: true
license: agpl-3.0
---

# L'Écho de Montolieu

A community project that helps people find out what is happening in the village of
**Montolieu** (Aude, Occitanie, France), known as the *Village du Livre et des Arts*.
It **points to** the pages of the Mairie and other local sites and does not replace them.
When information lives somewhere else, the aim is to send you there.

Live pages:
[GitHub Pages](https://mgifford.github.io/EchoDeMontolieu/) (always on) ·
[Hugging Face Space](https://huggingface.co/spaces/mgifford/EchoDeMontolieu) (read API; can sleep after
48 hours without visitors) ·
[urgent alerts from the Mairie on PanneauPocket](https://app.panneaupocket.com/ville/922810321-montolieu-11170)

> **AI disclosure.** This project and its software were written with AI assistance (Claude, an AI
> assistant from Anthropic, used through Claude Code), and this README was written by that assistant.
> Most generated pages are produced by programmed rules; French summaries and the English and Dutch
> versions are written or translated by AI models, named in each file. No person has checked any
> generated page. Everything a machine produced can be wrong, and says so. The original document is
> always the authority, and every page links to it. See [AI.md](AI.md) for who produced what.

## What exists today

- **The council minutes, as published.** All 25 PDFs on
  [montolieu.fr](https://www.montolieu.fr/mairie/comptes-rendus-cm/) (as of 2026-10-08), as page text
  with a link to the original page. Names are kept, because the minutes are public. The PDFs
  themselves are not copied. Each record carries the SHA-256 of the PDF it came from.
- **Version history.** If the Mairie replaces a PDF, the old version is kept and a page-by-page
  diff is published. The replaced PDF is archived privately by hash.
- **Verification.** `python -m echo_montolieu verify DOCUMENT_ID` checks that the text you have
  came from the file on the site (one polite request, or offline against a local PDF).
- **A read-only API** and a landing page ([`app.py`](app.py)), with rate limiting.
- **A list of where to find things** in [`data/where_to_find_mairie.json`](data/where_to_find_mairie.json).

In progress (see the open pull requests): readable Markdown for every meeting (full text, a
summary, and follow-ups), topics over time, finance and regulation links, places and a map,
and French, English and Dutch versions.

Not built yet, despite earlier plans: a business directory, parcel and zoning lookups, an MCP
server, a vector search.

## How the data is handled

- **The record is faithful.** [`public/minutes/`](public/minutes) reproduces the text as extracted,
  including its OCR errors, with a label saying so and how confident the OCR was.
- **Summaries and aggregates are derived by rules** and carry their sentence and page. They
  name elected officials on the council's attendance list, and replace other personal names.
  Items about private property sales keep only a count: no place, price or text, because in a
  village of about 800 people a place and a price identify a seller.
- **Uncertain things are labelled** (a date found by pattern, OCR with low confidence, a
  heuristic follow-up). If you find one that is not, that is a bug.
- **Politeness.** The Mairie runs a small server. The fetcher respects `robots.txt`, waits at least
  10 seconds between requests, checks for changes with header-only requests, and stops on
  any error. See [`echo_montolieu/fetch.py`](echo_montolieu/fetch.py).
- Private working data (unredacted extractions, a name registry, archived PDFs) is never
  committed; it lives in a git-ignored `private/` folder.

## Run it

```bash
pip install -r requirements.txt            # also needs Tesseract with French data for OCR
python -m echo_montolieu sync --dry-run    # what would be fetched (two requests)
python -m echo_montolieu sync              # fetch new minutes politely and extract them
python -m echo_montolieu publish-record    # write the faithful record to public/
python -m pytest                           # the tests
uvicorn app:app --port 7860                # the read API and landing page
```

## Accessibility

The target is WCAG 2.2 AA. The rules, the measured contrast ratios, the testing steps and an
honest list of what is **not** yet tested are in [ACCESSIBILITY.md](ACCESSIBILITY.md). No testing
with a screen reader or with disabled people has been done yet.

## Data sources

| Source | Used for |
|---|---|
| [Mairie de Montolieu](https://www.montolieu.fr/) | Council minutes (PDF); pointers to its pages |
| [Base Adresse Nationale](https://adresse.data.gouv.fr/api-doc/adresse) | Planned: confirming street and place names |
| [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/index) | Planned: summaries and translations |

## Contributing

Contributions are welcome. Read [ACCESSIBILITY.md](ACCESSIBILITY.md) first: every change to a
page must meet it and report how it was checked. Run the tests before opening a pull request.

## License

[AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html) (declared in the header above; a
`LICENSE` file has not been added yet). The text of the council minutes belongs to the Mairie;
whether it may be republished is a question for the project owner and has not been reviewed.
