# AI in this project

This project was built with AI assistance, and some of what it publishes is written by AI models.
This page says which parts, what checks exist, and what nobody has checked. It was itself written by
the AI assistant, at the maintainer's direction.

## In one paragraph

Everything published here comes from the Mairie's council minutes. Software turns those PDFs into
readable pages. That software was written by an AI assistant (Claude, from Anthropic, used through
Claude Code). Most pages are produced by programmed rules, with no AI model writing their words.
French summaries and the English and Dutch versions are written or translated by AI models, and each
such file names its model. **No person has checked any generated page.** Anything here can be wrong.
The original documents are authoritative, and every page links to them.

## Who produced what

| What | Produced by | Checked by a person? |
|---|---|---|
| The software: Python code, tests, workflows, the web pages | An AI assistant (Claude Sonnet 5.5, Anthropic, through Claude Code) at the maintainer's direction. Every commit and pull request carries a disclosure. | The maintainer merges each pull request. There are automated tests. No independent code audit has been done. |
| This file, `README.md`, `ACCESSIBILITY.md`, `jobs/README.md` | The AI assistant | Merged by the maintainer. Not independently reviewed. |
| The text of the council minutes | The Mairie. Software copies it from the PDF; pages that are images are read by OCR (Tesseract, a machine-learning program), which can misread. | No. OCR pages are marked and carry a confidence figure. |
| `minutes.md` files (French) | Software that tidies the Mairie's text. No AI model rewrites it. | No |
| `facts.md`, `todo.md`, issues over time, finance, places, the map | Programmed rules (written by the AI assistant), plus the national address database for place positions. No AI model writes the words. | No |
| `summary.md` (French summaries) | An AI model, named in the file | No |
| `*.en.md`, `*.nl.md` (English and Dutch) | An AI model, named in the file, translating the French | No. No native speaker has reviewed them. |
| `data/where_to_find_mairie.json` | The AI assistant, from link labels on the Mairie's website. The English labels and descriptions are the assistant's. | No |
| The wording of every AI notice and of the site interface (navigation, headings, notices), in French, English and Dutch | The AI assistant | No. The maintainer plans to have the glossary and labels reviewed by native speakers. |

Each Markdown file records this in its front matter (`produced_by`, `human_reviewed`,
`ai_disclosure`), and each JSON file in its `labels`. A file without `produced_by: "AI model (…)"`
contains no text written by an AI model.

**Status on 2026-10-08:** no AI model has yet written or translated any text in this repository. That
begins when the French summaries and the translations are generated.

## What this means for you

- It can be wrong. A summary can leave things out or invent a detail; a translation can change a
  nuance; rules can miss or mislink an item; OCR can misread a figure.
- Do not rely on any of it for a legal, financial, planning or other decision. Read the original PDF,
  which every page links to, and ask the Mairie.
- "Possibly dropped", "recurring issue" and similar labels are heuristics, not findings.
- Machine-generated pages say so at the top.

## Checks that exist, and what they do not prove

- Summaries must pass automatic checks: every figure of three digits or more must appear in the
  source, cited pages must exist, the text must be French. A summary that fails is kept but marked
  "À relire". Passing proves little about whether the summary is fair or complete.
- A translated passage that changes a number or a legal reference is replaced by the French original,
  with a visible note.
- Names are masked before any text is sent to a model, and notices about private property sales are
  never sent. Text that is sent goes to the model providers reached through Hugging Face Inference
  Providers; their terms have not been reviewed by this project.
- Elected officials on a meeting's attendance list may be named in derived pages (the maintainer's
  decision). Other private people are replaced, and property sales are reduced to counts.

None of this replaces a person reading the output.

## Résumé en français

Ce site et le logiciel qui le produit ont été écrits avec l’aide d’une IA (Claude, d’Anthropic). La
plupart des pages sont produites par des règles programmées, sans modèle d’IA pour rédiger les
textes. Les résumés français et les versions anglaise et néerlandaise sont écrits ou traduits par des
modèles d’IA, nommés dans chaque fichier. Personne n’a vérifié les pages produites : elles peuvent
contenir des erreurs. Les documents originaux font foi. (Ce résumé a lui aussi été écrit par l’IA et
n’a pas été relu par un locuteur natif.)

## Samenvatting in het Nederlands

Deze website en de software erachter zijn met hulp van AI geschreven (Claude, van Anthropic). De
meeste pagina’s worden met geprogrammeerde regels gemaakt, zonder dat een AI-model de teksten
schrijft. De Franse samenvattingen en de Engelse en Nederlandse versies worden door AI-modellen
geschreven of vertaald, met vermelding van het model in elk bestand. Niemand heeft de gemaakte
pagina’s gecontroleerd: ze kunnen fouten bevatten. De originele documenten zijn leidend. (Ook deze
samenvatting is door AI geschreven en niet door een moedertaalspreker nagelezen.)

## Report a mistake

Open an issue at https://github.com/mgifford/EchoDeMontolieu/issues and name the page and the line.
