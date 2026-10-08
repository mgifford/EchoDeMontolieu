# Archive of originals no longer on the Mairie's site

> **AI disclosure.** This note was written by an AI assistant (Claude, from Anthropic) at the maintainer's direction and has not been independently reviewed. See [AI.md](../AI.md).

`originals/` holds copies of council minutes from 2004 to 2008 that the Mairie's current site no longer
serves. They were recovered from the Internet Archive (Wayback Machine).

- **The Wayback capture is the official copy.** Each record in `public/minutes/` has `source_url` set to the
  timestamped web.archive.org address and `origin.mirror_url` pointing to the copy here.
- **These copies are for convenience**: the Archive is slow and hard to browse. Check one with
  `shasum -a 256 FILE.pdf` and compare it with `source_sha256` in the record.
- **Only what the Archive captured.** Nothing was found for 2009 to 2023; absence here does not mean no meeting took place.
- **Dates come from the text** of each document (tentative). File names were typed by hand and sometimes
  disagree (`origin.date_hint_from_filename` records the difference).
- **Digests are not produced yet** for these files (facts, follow-ups, issues, finance, places): the rules were built for the
  current layout and have not been checked on 2004 to 2008 minutes.

Regenerate with `python -m echo_montolieu wayback`; the listing used is `data/wayback_captures.json`.
