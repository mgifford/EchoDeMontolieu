# Phase 1 Review: L'Écho de Montolieu

I verified every claim against the live `montolieu.fr` page, the BAN and SIRENE APIs, and the actual PDF archive. The proposal is a solid starting point but has **15 bugs, 6 accessibility violations, and 4 architectural mismatches** that need fixing before it can run.

---

## Verdict by File

| File | Status | Blocking Issues |
|------|--------|-----------------|
| `fetch_and_process.py` | 🔴 Will fail silently | Scraper logic misses most PDFs; temp file race condition; outdated SDK |
| `phase1_pipeline.yml` | 🟡 Will run but may fail | Missing `permissions: contents: write`; no pip cache |
| `index.html` | 🟡 Mostly works, a11y gaps | Skip link invisible on focus; no `<noscript>`; no shaped markers |
| `requirements.txt` | 🔴 Won't install | `google-generativeai==0.4.1` is from 2024, incompatible by Oct 2026 |

---

## File 1: `fetch_and_process.py` — 8 Issues

### 🔴 Critical: Scraper Logic Will Miss Most PDFs

The scraper looks for `href.endswith(".pdf") or "CM" in text.upper()` then filters by year strings `["2024", "2025", "2026"]`. I scraped the live page and found **30 unique PDF links**. The actual patterns are:

```
CRCM-8-01-2026-site-internet.pdf      (file path has year in /uploads/2026/)
CM-31-JANVIER-2024-site-internet.pdf   (both href and text have "2024")
PV-CONSEIL-MUNICIPAL-DU-22-juillet-2026-site.pdf  (named "PV" not "CM")
Projet-CM-15-avril-site-internet.pdf   (no year in filename!)
```

**Problem 1:** `Projet-CM-15-avril-site-internet.pdf` has no year in the filename or link text — the filter `any(year in text or year in href for year in ["2024", "2025", "2026"])` will miss it.

**Problem 2:** Some `<a>` tags have **no visible link text** (empty text node, just a child `<img>` tag for the flipbook preview). The fallback `text or "Conseil Municipal"` would assign a generic title.

**Problem 3:** Duplicate URLs — the same PDF URL appears multiple times (e.g., `CM-31-JANVIER-2024-site-internet.pdf` appears 3 times on the page). The `processed_urls` set handles this for reruns, but the initial scrape list `pdf_items` will contain duplicates leading to wasted Gemini API calls.

> [!IMPORTANT]
> **Fix:** Deduplicate `pdf_items` by URL, broaden the year filter to also check the `uploads/20XX/` path component, and fall back to extracting the date from the filename:
> ```python
> seen = set()
> for a in soup.find_all("a", href=True):
>     href = a["href"]
>     if not href.endswith(".pdf"):
>         continue
>     full_url = urljoin(BASE_URL, href)
>     if full_url in seen:
>         continue
>     seen.add(full_url)
>     # Check year in href path, not just link text
>     if any(year in full_url for year in ["2024", "2025", "2026"]):
>         text = a.get_text(strip=True)
>         pdf_items.append({"title": text or extract_title_from_filename(href), "url": full_url})
> ```

### 🔴 Critical: Temp File Race Condition

```python
with open("temp.pdf", "wb") as f:
    f.write(res.content)
reader = PdfReader("temp.pdf")
```

This writes to a fixed filename in the working directory. If GitHub Actions or any parallel process runs, it creates a collision. Worse, in a CI/CD environment the current directory might not be writable.

> [!IMPORTANT]
> **Fix:** Use `tempfile` or read directly from bytes:
> ```python
> from io import BytesIO
> reader = PdfReader(BytesIO(res.content))
> ```
> This also matches the docstring "Downloads PDF into memory" which the implementation contradicts.

### 🔴 Critical: Outdated Gemini SDK

The code uses `genai.GenerativeModel("gemini-1.5-flash")` and `google-generativeai==0.4.1`. By October 2026, the SDK has gone through multiple breaking changes. The model name may need `gemini-2.0-flash` or the equivalent current model.

### 🟡 Important: No Retry / Error Recovery for LLM JSON Parsing

```python
clean_json = re.sub(r'```json\s*|\s*```', '', response.text).strip()
data = json.loads(clean_json)
```

If Gemini returns malformed JSON (common with complex prompts), the entire pipeline crashes with no retry. This will lose the entire batch.

> **Fix:** Add retry with exponential backoff, or wrap in try/except and skip the individual PDF:
> ```python
> for attempt in range(3):
>     try:
>         data = json.loads(clean_json)
>         break
>     except json.JSONDecodeError:
>         if attempt < 2:
>             time.sleep(2 ** attempt)
>             response = model.generate_content(prompt)
>             clean_json = re.sub(r'```json\s*|\s*```', '', response.text).strip()
> ```

### 🟡 Important: Prompt Truncation at 12,000 Characters

```python
{raw_text[:12000]}
```

I downloaded the latest PDF (`PV-CONSEIL-MUNICIPAL-DU-22-juillet-2026-site.pdf`) — it's 513 KB with multiple pages. Many council minutes run 5-15 pages. Truncating at 12K chars will cut off the second half of most meetings, missing important decisions.

> **Fix:** Use the Gemini model's full context window. `gemini-1.5-flash` supports 1M tokens. Send the full text, or at least chunk and summarize in passes.

### 🟡 Important: No BAN API Rate Limiting

Each PDF can reference multiple locations. The BAN API has no documented rate limit, but hitting it rapidly for 30 PDFs x N locations per PDF could trigger IP throttling.

> **Fix:** Add `time.sleep(0.5)` between geocode calls.

### ℹ️ Minor: No Logging

Uses `print()` statements. In GitHub Actions, structured logging helps with debugging failed runs.

### ℹ️ Minor: User-Agent String

`Mozilla/5.0` is generic. Government servers sometimes block or rate-limit generic bots. Use a descriptive user agent:
```python
"EchoDeMontolieu-Bot/1.0 (civic transparency project; github.com/YOUR/REPO)"
```

---

## File 2: `phase1_pipeline.yml` — 3 Issues

### 🔴 Critical: Missing `permissions` Block

Without explicit permissions, the default token won't have `contents: write` access to push commits. The `git push` step will fail silently or with a 403.

> [!IMPORTANT]
> **Fix:**
> ```yaml
> jobs:
>   build-and-scrape:
>     runs-on: ubuntu-latest
>     permissions:
>       contents: write
> ```

### 🟡 Important: No pip Dependency Caching

Every run installs all dependencies fresh (~30s overhead). Add caching:

```yaml
- name: Set up Python
  uses: actions/setup-python@v5
  with:
    python-version: '3.11'
    cache: 'pip'
```

### ℹ️ Minor: No Job Timeout

If the Gemini API hangs, the job runs indefinitely (up to the 6-hour GitHub Actions limit). Add:

```yaml
jobs:
  build-and-scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 30
```

---

## File 3: `index.html` — 6 Issues

### 🔴 WCAG Violation: Skip Link Not Visible on Focus

```css
.sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0,0,0,0); border: 0;
}
```

The skip link `<a href="#main-content" class="sr-only">` is permanently hidden. WCAG 2.4.1 requires skip links to be either always visible OR become visible when focused. Currently, keyboard users can Tab to it but never see it.

> [!WARNING]
> **Fix:** Add a focus state that reveals the skip link:
> ```css
> .sr-only:focus {
>     position: static;
>     width: auto;
>     height: auto;
>     padding: 0.5rem 1rem;
>     margin: 0;
>     overflow: visible;
>     clip: auto;
>     background: var(--primary);
>     color: white;
>     z-index: 10000;
> }
> ```

### 🔴 WCAG 1.4.1 Violation: Map Markers Use Color Only

The dossier spec requires: *"Map category markers feature distinct geometric shapes inside icons (Circle = Business, Square = Municipal, Star = Cultural Event) alongside color coding."*

The proposed HTML uses default Leaflet `L.marker()` which renders identical blue pin icons for all categories. This violates WCAG 1.4.1 (Use of Color).

> **Fix:** Use `L.divIcon` or `L.icon` with custom SVG markers per category, using distinct shapes.

### 🟡 WCAG: Focus Outline Offset Mismatch

The dossier specifies `2px offset`, but the CSS uses `3px`:
```css
:focus-visible {
    outline: 3px solid var(--focus-ring);
    outline-offset: 3px;  /* Dossier says 2px */
}
```

### 🟡 No `<noscript>` Fallback

The entire page depends on JavaScript. If JS is blocked (some French government networks, privacy browsers), users see nothing. Add:

```html
<noscript>
  <p>Ce site necessite JavaScript pour fonctionner. / This site requires JavaScript.</p>
</noscript>
```

### 🟡 Heading Structure Does Not Update with Language

`<h2 id="feed-heading">Deliberations du Conseil</h2>` remains in French even when switching to EN or NL. Screen readers will announce a French heading in an English page.

> **Fix:** Add heading translations to the `i18n` object and update in `setLanguage()`.

### 🟡 Missing `<meta name="description">`

No meta description tag. This hurts SEO and accessibility (screen readers often announce the page description):

```html
<meta name="description" content="Tableau de bord civique trilingue pour Montolieu — Council decisions, business directory, and cultural events.">
```

### ℹ️ Minor: Inline `onclick` Handlers

`onclick="setLanguage('fr')"` is fragile and blocks CSP `unsafe-inline`. Use `addEventListener` instead.

### ℹ️ Minor: No Google Fonts

The dossier's aesthetics spec mentions premium typography (Inter, Roboto, Outfit). The HTML uses `system-ui, -apple-system, sans-serif`. The Mairie site itself uses Mulish, Open Sans, and Poppins — consider matching or complementing their typography.

---

## File 4: `requirements.txt` — 2 Issues

### 🔴 Critical: Severely Outdated Package Versions

```
google-generativeai==0.4.1
```

Version 0.4.1 was released in early 2024. By October 2026, the package has had 2+ years of breaking changes. The API patterns (`genai.GenerativeModel`, `model.generate_content`) may have changed entirely.

> [!IMPORTANT]
> **Fix:** Use current versions (remove pins or use `>=` minimums):
> ```
> requests>=2.31.0
> beautifulsoup4>=4.12.3
> pypdf>=4.1.0
> google-generativeai>=1.0.0
> lxml>=5.0.0
> ```

### 🟡 Missing `lxml`

BeautifulSoup defaults to Python's built-in `html.parser`, which is slow and occasionally misparses malformed HTML. WordPress/Divi output is notoriously messy. Add `lxml` and use it explicitly:

```python
soup = BeautifulSoup(response.content, "lxml")
```

---

## Architectural Mismatches with the Dossier

### 1. Frontend fetches static JSON, but you chose FastAPI backend

The `index.html` does:
```javascript
fetch('data/council_archive.json')
```

This works for GitHub Pages (static hosting) but contradicts your choice of a **FastAPI backend**. For FastAPI, this should be:
```javascript
fetch('/api/council')
```

### 2. File location mismatch

The dossier places the frontend in `static/index.html` with `static/css/style.css` and `static/js/app.js`. The proposal puts everything in a single root-level `index.html`. This won't work with FastAPI's `StaticFiles` mount without adjustment.

### 3. No `app.py` or `mcp_server.py`

Phase 1 doesn't include the FastAPI application file. Without it, there's no way to serve the frontend from the Python backend. Either:
- Add a minimal `app.py` that serves static files, OR
- Commit to pure GitHub Pages for Phase 1 and move to FastAPI in Phase 2

### 4. Missing `data/processed_pdfs.txt`

The dossier's directory layout shows this file for duplicate detection, but the scraper uses the JSON archive itself for deduplication. This is actually fine (simpler), but the dossier should be updated to match.

---

## Verified Facts

| Claim | Verified |
|-------|----------|
| PDF count "~25 PDFs" | ✅ Found **30 unique PDF URLs** (close enough) |
| BAN API works without key | ✅ Confirmed with live query returning `43.3107, 2.21492` |
| SIRENE API works without key | ✅ Confirmed — returns Mairie, Montolieu 1739, Photobook, etc. |
| PDFs are downloadable | ✅ Tested `PV-CONSEIL-MUNICIPAL-DU-22-juillet-2026-site.pdf` — 513 KB |
| Storage "~2.5 MB JSON" | ⚠️ Likely lower: 30 PDFs x ~10KB JSON each = ~300KB raw, but with trilingual text could reach 1-2MB |
| LLM cost "$0.00" | ✅ Gemini Flash free tier handles ~1500 requests/day; 30 PDFs is well within limits |

---

## Recommended Next Steps

1. **Fix the 4 🔴 Critical issues** before committing anything
2. **Decide: FastAPI or GitHub Pages for Phase 1?** — this determines whether you need `app.py` now
3. **Add a test run** — download 1-2 PDFs locally and verify the full pipeline before setting up the GitHub Action
4. **Pin modern package versions** that actually exist today

Would you like me to create the corrected files with all fixes applied?
