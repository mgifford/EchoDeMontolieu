// Automated accessibility check: axe-core at two widths, the real CSP, reflow and keyboard.
// Usage: node tools/a11y_check.cjs URL
// Needs `playwright` (with a browser installed) and `axe-core`, found in ./node_modules or in
// the folder named by A11Y_NODE_MODULES. This is automation only: it does not replace
// testing with a screen reader, zoom, or people (see ACCESSIBILITY.md).
const URL = process.argv[2];
if (!URL) { console.error('usage: node tools/a11y_check.cjs URL'); process.exit(2); }
const { createRequire } = require('module');
const path = require('path');
const fs = require('fs');
const modules = path.resolve(process.env.A11Y_NODE_MODULES || 'node_modules') + path.sep;
const req = createRequire(modules);
const { chromium } = req('playwright');
const axeSource = fs.readFileSync(path.join(modules, 'axe-core', 'axe.min.js'), 'utf8');

let failures = 0;       // violations, missing focus outlines, CSP errors: the exit code is non-zero if any
(async () => {
  const browser = await chromium.launch();

  // 1. Under the real CSP (no bypass): is the page styled, and does the CSP hash work?
  {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const violations = [];
    page.on('console', m => { if (/Content Security Policy/i.test(m.text())) violations.push(m.text()); });
    await page.goto(URL);
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    console.log('real CSP: body background =', bg, '| CSP console errors:', violations.length);
    failures += violations.length;
    await ctx.close();
  }

  // 2. axe at two viewport widths; bypassCSP only so the test can inject axe.
  for (const [label, vp] of [['desktop 1280x800', { width: 1280, height: 800 }],
                             ['phone 320x640', { width: 320, height: 640 }]]) {
    const ctx = await browser.newContext({ viewport: vp, bypassCSP: true });
    const page = await ctx.newPage();
    await page.goto(URL);
    await page.evaluate(axeSource);
    const res = await page.evaluate(async () => await axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] },
    }));
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    console.log(`\n[${label}] axe ${res.testEngine.version}: violations=${res.violations.length} passes=${res.passes.length} incomplete=${res.incomplete.length} inapplicable=${res.inapplicable.length}`);
    failures += res.violations.length;
    for (const v of res.violations) console.log('  VIOLATION', v.id, v.impact, '-', v.help, '|', v.nodes.length, 'node(s)');
    for (const v of res.incomplete) console.log('  needs manual check:', v.id, '-', v.help, '|', v.nodes.length, 'node(s)');
    console.log('  horizontal overflow (px):', overflow);
    await ctx.close();
  }

  // 3. Keyboard: every link reachable by Tab, and focus is visibly styled.
  {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto(URL);
    const total = await page.evaluate(() => document.querySelectorAll('a[href]').length);
    // Tab also visits buttons and other focusable controls (map markers, zoom buttons), so allow for them.
    const stops = await page.evaluate(() => document.querySelectorAll('a[href], button, [tabindex="0"]').length);
    const seen = new Set();            // distinct links reached; Tab can pass the same one twice
    let noOutline = 0;
    for (let i = 0; i < stops + 2; i++) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el.tagName !== 'A') return null;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return { key: el.href + '|' + Math.round(r.x) + ',' + Math.round(r.y), w: parseFloat(s.outlineWidth), st: s.outlineStyle };
      });
      if (info && !seen.has(info.key)) {
        seen.add(info.key);
        if (!(info.w >= 3 && info.st !== 'none')) noOutline++;
      }
    }
    const reached = seen.size;
    console.log(`\nkeyboard: links=${total}, reached by Tab=${reached}, without a 3px outline=${noOutline}`);
    failures += noOutline;
    await ctx.close();
  }
  await browser.close();
  if (failures) { console.error(`FAILED: ${failures} problem(s)`); process.exit(1); }
})().catch(e => { console.error('ERROR', e.message); process.exit(1); });
