# Accessibility

> **AI disclosure.** This document was written by an AI assistant (Claude, from Anthropic) at the maintainer's direction and merged by the maintainer; it has not been independently reviewed. The test results it reports were produced by the tools named in it. See [AI.md](AI.md).

Rules for anyone, human or coding agent, who changes this project. The audience is
a village: people of every age and ability, in French, English and Dutch, on phones,
old computers and assistive technology. Accessibility is a requirement here, not a
polish step.

## Target

- **WCAG 2.2 Level AA** ([spec](https://www.w3.org/TR/WCAG22/)) for every page this project
  publishes, including generated pages.
- Where a rule below is stricter than AA it says so. Do not describe a stricter project
  rule as a legal requirement.
- A passing automated scan is not conformance. Automation finds a minority of problems;
  see [Testing](#testing) for what must also be done by hand.

## Rules for code

### Structure and semantics
- Use native HTML first: `header`, `nav`, `main`, `footer`, headings, lists, `button`, `a`,
  `table`. One `h1` per page, then headings in order without skipping levels.
- Every page has a descriptive `<title>`, `lang` on `<html>`, and a landmark structure a
  screen reader user can navigate. Give a landmark a label only when there are two of the
  same kind.
- A link goes somewhere; a button does something. Do not use one for the other.
- Link text must make sense out of context. Repeated links ("original PDF" in 25 rows) get
  visually hidden text naming what they belong to, as the landing page does.
- Data tables have a header row (`th` with `scope`) and a caption. Never use a table for layout.

### Keyboard and focus
- Everything works with the keyboard alone, in a logical order, with no traps.
- Focus is always visible. Project style: a 3px outline in `#005A9C` with a 2px offset.
  (WCAG 2.4.13 Focus Appearance is Level AAA; this is a project choice.)
- **In the header, use a white focus ring** (`#FFFFFF`). `#005A9C` on the header's `#004B87`
  is only 1.25:1, below the 3:1 that [1.4.11 Non-text Contrast](https://www.w3.org/TR/WCAG22/#non-text-contrast)
  requires. Nothing focusable is in the header yet, but the language switcher will be.
- Move focus on purpose when content changes (a dialog opens, a view switches), and return it
  afterwards. Never remove an outline without replacing it.
- Provide a skip link to `main` once a page has navigation before its content. It must be
  visible when focused.

### Targets and spacing
- **Minimum 44 by 44 CSS pixels** for buttons, language switches, filters and map controls.
  This is stricter than WCAG 2.2 AA, which requires 24 by 24
  ([2.5.8 Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html));
  44 is the AAA value of [2.5.5](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html).
  Links inside a sentence are exempt.

### Colour and contrast
- Text at least 4.5:1 (AA); aim far higher for body text. Interface parts and focus
  indicators at least 3:1 against what is next to them.
- Never use colour alone to carry meaning. Pair it with text or a shape. (On the map: a
  different marker shape per category, not only a different colour.)
- Measured with the WCAG formula for the current palette:

  | Pair | Ratio |
  |---|---|
  | Body text `#1A1A1A` on page `#FBF9F5` | 16.55:1 |
  | Links `#004B87` on page | 8.48:1 |
  | White on header `#004B87` | 8.91:1 |
  | Body text on alerts box `#EBF3FA` | 15.53:1 |
  | Links on alerts box | 7.95:1 |
  | Focus ring `#005A9C` on page | 6.79:1 |
  | Focus ring `#005A9C` on header `#004B87` | 1.25:1 (do not use there) |

  Recompute when a colour changes. Do not assume.

### ARIA
- First rule: do not use ARIA if a native element does the job. No ARIA is better than
  wrong ARIA ([WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)).
- Use `aria-labelledby` to name a region from its heading; use `aria-current` for the current
  item in a set. Do not add `role` to an element that already has it.
- Live regions announce status changes only (a language switched, a filter applied). Keep
  them polite, short, and in the language of the page. Do not use them for ordinary content.

### Language
- Set `lang` on `<html>`. Put `lang="fr"` (or `en`, `nl`) on any passage in another
  language: French document titles on an English page, a translated paragraph on a French
  page ([3.1.2](https://www.w3.org/WAI/WCAG22/Understanding/language-of-parts.html)). This is not
  decoration: it changes how a screen reader pronounces the text.
- A language switcher lists each language in its own language, with `lang` on each item, and
  marks the current one. Switching updates `<html lang>`, the title and the headings.

### Machine-generated and translated content
- Say it in text, near the top, not in colour or an icon: this was extracted or translated by
  a machine, it can be wrong, and the original is authoritative. Link the original.
- Uncertain content (OCR with low confidence, a tentative date) carries a visible text label.

### Maps
- A map is never the only way to reach information. Every map has an equivalent list or table
  with the same places and the same links, reachable without JavaScript.
- Map controls follow the 44px rule and are operable by keyboard. Markers differ by shape and
  by text label, not only by colour.

### Motion, zoom and preferences
- No autoplay or flashing. Respect `prefers-reduced-motion`.
- Content must reflow at 320 CSS pixels wide with no horizontal scrolling and no loss
  ([1.4.10](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)), and work at 200% zoom and
  with increased text spacing.
- Test in forced-colors (high contrast) mode. The pages are currently light only
  (`color-scheme: light`); a dark theme must meet the same contrast rules before it ships.

### Generated Markdown
- One `#` heading, headings in order, link text that makes sense alone, tables with a header
  row, and fenced blocks for number grids (they are not prose). Images need alternative text.

## Testing

### Automated (run on every change that touches a page)

```bash
npm install --no-save playwright axe-core
npx playwright install chromium
python build_site.py _site
python -m http.server 8000 --directory _site &
node tools/a11y_check.cjs http://127.0.0.1:8000/
```

It runs axe-core at 1280 and 320 pixels wide, loads the page under its real Content Security
Policy, checks for horizontal overflow at 320 pixels, and tabs through every link to confirm a
visible 3px outline. Report the result, including counts of `incomplete` items.

Last results (axe-core 4.13.0, 1280 and 320 pixels wide, no horizontal overflow at either):

| Page | Violations | Links reached by keyboard | Left for manual checking |
|---|---|---|---|
| Home page | 0 | 69 of 69, all with a 3px outline | none |
| Map and list of places | 0 | 38 of 38, all with a 3px outline | colour contrast of text drawn over map tiles |

On the map page: markers are 44 by 44 pixels, labelled, reachable with Tab and opened with Enter;
the table lists the same 13 places and works without JavaScript; the page loads under its own
Content Security Policy with no violations.

### By hand (automation cannot do these)
- [ ] Keyboard only: reach and operate everything; focus is visible and in a sensible order.
- [ ] A screen reader (VoiceOver, NVDA): headings, landmarks, link lists, language of French
      and Dutch passages, the hidden link context, and live-region announcements.
- [ ] 200% and 400% zoom; text spacing increased; forced-colors mode; reduced motion.
- [ ] Read the generated pages aloud in each language: do the labels make sense?
- [ ] Content quality: plain language, the machine-generated notice is understandable.

## Known gaps (kept honest)

- No testing with a screen reader or with disabled users has been done. This matters most for the map.
- The landing page is English only; French, English and Dutch versions of the minutes are planned,
  and the labels and glossary used for them are not yet reviewed by native speakers.
- There is no language switcher or skip link on the home page yet.
- Map: markers overlap when the map is zoomed out (places 100 m apart are about 14 pixels apart at
  the zoom that shows everything). It therefore opens at village scale, where the closest places are
  57 pixels apart, and the list is the complete, reliable way to read the places.
- Map: the contrast of the map's own text and attribution over tiles cannot be measured
  automatically. The tiles and Leaflet come from third parties (OpenStreetMap, unpkg), which see
  the visitor's address; the page says so, and the list does not depend on them.
- Contrast was measured by formula for the palette above, not on a real range of screens.
- Dark mode is not offered.
- The faithful minutes copy the Mairie's text; the PDFs themselves may not be accessible.

## Definition of done for a UI change

1. Uses semantic HTML and follows the rules above.
2. `tools/a11y_check.cjs` run, results reported, including what it does not cover.
3. The manual checklist items relevant to the change are done, or listed as not done.
4. New content is labelled as machine-generated or uncertain where it is.
5. Anything not verified is written down in this file's gaps.

## Trilingual static site (GitHub Pages)

Built by `echo_montolieu/site.py`: `/fr/`, `/en/`, `/nl/` trees with a skip link, a main navigation, a language switcher
(plain links, so it works without scripts; the choice is remembered in the browser), `lang` on the page and on any block shown in
another language, and a visible notice when a page is not yet translated. Tables sit in a focusable, uniquely named scroll region
with column headers. Checked on 2026-10-08 with axe-core 4.13.0 (`tools/a11y_check.cjs`) at 1280 and 320 px on the home page in
all three languages, the meetings index, a minutes page, the issues, finance and places pages: 0 violations, no horizontal
overflow, every link reachable by Tab. Language negotiation was checked in Chromium with Dutch, French, German and English
browser settings and with a saved override. Not covered: screen readers, zoom beyond 320 px width, and the quality of the French
and Dutch interface wording (not reviewed by a native speaker). The map page (`places/map.html`) is English only.

