// Browser regressions against a separate candidate, before activating its preview.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';

const runtime = process.env.BTED_NODE_MODULES || 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { chromium } = createRequire(path.join(runtime, '_catalog_acceptance.cjs'))('playwright');
const candidate = path.resolve(process.env.BTED_CATALOG_CANDIDATE || 'dist/v05-hf-preview/snapshots/catalog-english-filters-20261003');
const origin = process.env.BTED_PREVIEW_ORIGIN || readFileSync(path.join(candidate, 'backend.txt'), 'utf8').trim();
const uiOnly = process.argv.includes('--ui-only');
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 940 } });
const page = await context.newPage();
page.setDefaultTimeout(30000);
const report = { status: 'running', origin, cases: [], pageErrors: [] };
page.on('pageerror', error => report.pageErrors.push(String(error)));
const han = /[\u3400-\u4dbf\u4e00-\u9fff]/;
async function api(route) {
  const response = await context.request.get(origin + route);
  assert.ok(response.ok(), route + ' ' + response.status());
  return response.json();
}
async function ready() {
  await page.waitForFunction(() => document.getElementById('batter-directory').getAttribute('aria-busy') === 'false');
  assert.ok(await page.locator('#batter-request-error').isHidden(), await page.locator('#batter-error-message').textContent());
}
async function english() {
  const copy = await page.evaluate(() => [document.title, document.body.innerText,
    ...[...document.querySelectorAll('[aria-label], [title], [placeholder], option')].flatMap(element =>
      [element.getAttribute('aria-label'), element.getAttribute('title'), element.getAttribute('placeholder'), element.tagName === 'OPTION' ? element.textContent : '']),
  ].join('\n'));
  assert.ok(!han.test(copy), 'Visible copy and accessible labels must be English');
}
async function matchesApi() {
  const payload = await api('/api/genomes' + new URL(page.url()).search);
  assert.deepEqual(await page.locator('#batter-results .genome-link').allTextContents(), payload.data.map(row => row.genome_id));
  return payload;
}
function passed(name) { report.cases.push(name); console.log('PASS ' + name); }

try {
  const manifest = await api('/assets/data-release.json');
  assert.equal(manifest.releaseDisplayName, 'Latest · v5');
  await page.goto(origin + '/index.html');
  await ready();
  await english();
  assert.equal(await page.locator('[data-batter-sort]').count(), 4);
  assert.equal(await page.locator('#batter-sort').count(), 0);
  assert.ok(await page.locator('#batter-class').isDisabled());
  await matchesApi();
  passed('English directory and default filters');

  await page.selectOption('#batter-page-size', '25');
  await ready();
  await page.click('#batter-next');
  await ready();
  assert.equal(new URL(page.url()).searchParams.get('page'), '2');
  await page.reload();
  await ready();
  assert.equal(await page.locator('#batter-page-size').inputValue(), '25');
  const secondPage = await matchesApi();
  assert.equal(secondPage.pagination.page, 2);
  await page.locator('#batter-results .genome-link').first().click();
  await page.waitForSelector('.batter-detail-heading');
  await english();
  await page.click('#batter-back');
  await ready();
  assert.equal(new URL(page.url()).searchParams.get('page'), '2');
  await matchesApi();
  passed('Pagination, reload, and detail return preserve URL state');

  for (const field of ['genome_id', 'predictions', 'otu_augmentation', 'rfam_training']) {
    const button = page.locator(`[data-batter-sort="${field}"]`);
    await button.click();
    await ready();
    const first = new URL(page.url()).searchParams.get('sort');
    assert.equal(new URL(page.url()).searchParams.get('page'), '1');
    await matchesApi();
    await button.click();
    await ready();
    assert.notEqual(new URL(page.url()).searchParams.get('sort'), first);
    assert.ok(['ascending', 'descending'].includes(await button.locator('..').getAttribute('aria-sort')));
    await matchesApi();
  }
  passed('All four table headers sort in both directions');

  await page.selectOption('#batter-evidence', 'experimental');
  await ready();
  assert.ok((await matchesApi()).data.every(row => row.has_experimental));
  await page.selectOption('#batter-evidence', 'both');
  await ready();
  assert.ok((await matchesApi()).data.every(row => row.has_experimental && row.has_batter));
  await page.selectOption('#batter-bigwig', 'true');
  await ready();
  assert.ok((await matchesApi()).data.every(row => row.has_bigwig));
  await page.selectOption('#batter-evidence', 'all');
  await ready();
  await page.selectOption('#batter-bigwig', 'false');
  await ready();
  assert.ok((await matchesApi()).data.every(row => !row.has_bigwig));
  await page.click('#batter-clear');
  await ready();
  passed('Inclusive evidence and BigWig filters combine correctly');

  const phyla = await page.locator('#batter-phylum option').evaluateAll(options => options.map(option => option.value).filter(Boolean));
  assert.ok(phyla.length > 1);
  await page.route('**/api/genomes/facets?**', async route => {
    if (new URL(route.request().url()).searchParams.get('rank') === 'class') await new Promise(resolve => setTimeout(resolve, 500));
    await route.continue().catch(() => {});
  });
  await page.selectOption('#batter-phylum', phyla[0]);
  assert.ok(await page.locator('#batter-class').isDisabled());
  assert.ok(await page.locator('#batter-class-loading').isVisible());
  await ready();
  const classes = await page.locator('#batter-class option').evaluateAll(options => options.map(option => option.value).filter(Boolean));
  assert.ok(classes.length);
  await page.selectOption('#batter-class', classes[0]);
  await ready();
  await page.selectOption('#batter-phylum', phyla[1]);
  assert.equal(await page.locator('#batter-class').inputValue(), '');
  assert.ok(await page.locator('#batter-class').isDisabled());
  assert.ok(!new URL(page.url()).searchParams.has('class'));
  await ready();
  const independentClasses = await page.locator('#batter-class option').allTextContents();
  await page.fill('#batter-search', 'no-matching-genome-acceptance');
  await page.waitForFunction(() => location.search.includes('no-matching-genome-acceptance'));
  await ready();
  assert.equal(await page.locator('#batter-results .genome-link').count(), 0);
  assert.deepEqual(await page.locator('#batter-class option').allTextContents(), independentClasses);
  await english();
  await page.unroute('**/api/genomes/facets?**');
  passed('Parent changes clear children; options load safely and ignore text filters');

  // A late taxonomy response must not replace the newer parent's options.
  await page.evaluate(oldPhylum => {
    const original = window.fetch.bind(window);
    window.__staleFacetStarted = false;
    window.fetch = (url, options) => {
      const parsed = new URL(url, location.href);
      if (parsed.pathname === '/api/genomes/facets' && parsed.searchParams.get('rank') === 'class' && parsed.searchParams.get('phylum') === oldPhylum) {
        window.__staleFacetStarted = true;
        return new Promise(resolve => setTimeout(() => resolve(new Response(JSON.stringify({options:[{value:'OBSOLETE CLASS',count:1}]}), {headers:{'Content-Type':'application/json'}})), 1000));
      }
      return original(url, options);
    };
  }, phyla[0]);
  await page.selectOption('#batter-phylum', phyla[0]);
  await page.waitForFunction(() => window.__staleFacetStarted && !document.querySelector('#batter-phylum').disabled);
  await page.selectOption('#batter-phylum', phyla[1]);
  await ready();
  await page.waitForTimeout(1100);
  assert.deepEqual(await page.locator('#batter-class option').allTextContents(), independentClasses);
  passed('Stale taxonomy responses cannot overwrite the newer parent');

  let navigations = 0;
  page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations += 1; });
  await page.click('#batter-clear');
  await ready();
  assert.equal(navigations, 0);
  assert.equal(await page.locator('#batter-search').inputValue(), '');
  assert.equal(await page.locator('#batter-page-size').inputValue(), '50');
  assert.deepEqual([...new URL(page.url()).searchParams.entries()].sort(), [['page', '1'], ['page_size', '50'], ['sort', 'genome_id_asc']]);
  passed('Clear filters resets in place to the agreed defaults');

  const example = (await api('/api/genomes?page_size=25&evidence=prediction')).data[0].genome_id;
  // Resolve/reject after abort to verify stale guards even when transport ignores cancellation.
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.__catalogueRequests = [];
    window.fetch = (url, options) => {
      const parsed = new URL(url, location.href);
      if (parsed.pathname === '/api/genomes') {
        const q = parsed.searchParams.get('q');
        window.__catalogueRequests.push(q);
        if (q === 'stale-success' || q === 'stale-error') {
          options.signal.addEventListener('abort', () => { window.__catalogueAborted = true; });
          return new Promise((resolve, reject) => setTimeout(() => q === 'stale-error'
            ? reject(new Error('Obsolete request error'))
            : resolve(new Response(JSON.stringify({ data: [{genome_id:'OBSOLETE'}], pagination:{page:1,page_size:50,total:1,returned:1} }), {headers:{'Content-Type':'application/json'}})), 1000));
        }
      }
      return original(url, options);
    };
  });
  for (const stale of ['stale-success', 'stale-error']) {
    await page.fill('#batter-search', stale);
    await page.waitForFunction(value => window.__catalogueRequests.includes(value), stale);
    await page.fill('#batter-search', example);
    await page.waitForFunction(value => location.search.includes(value), example);
    await ready();
    await page.waitForTimeout(1100);
    await ready();
    assert.equal(await page.locator('#batter-search').inputValue(), example);
    assert.ok(!(await page.locator('#batter-results').innerText()).includes('OBSOLETE'));
    await matchesApi();
  }
  assert.ok(await page.evaluate(() => window.__catalogueAborted));
  await page.evaluate(() => { window.__catalogueRequests = []; });
  await page.fill('#batter-search', 'short-lived-input');
  await page.waitForTimeout(100);
  await page.fill('#batter-search', example);
  await page.waitForTimeout(450);
  await ready();
  assert.deepEqual(await page.evaluate(() => window.__catalogueRequests), [example]);
  passed('300 ms debounce, cancellation, and stale success/error protection');

  let failOnce = true;
  await page.route('**/api/genomes?**', async route => {
    if (failOnce) {
      failOnce = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'Catalogue temporarily unavailable' }) });
    } else await route.continue();
  });
  await page.locator('[data-batter-sort="predictions"]').click();
  await page.waitForSelector('#batter-request-error:not([hidden])');
  const failedQuery = new URL(page.url()).search;
  await english();
  await page.click('#batter-retry');
  await ready();
  assert.equal(new URL(page.url()).search, failedQuery);
  await matchesApi();
  await page.unroute('**/api/genomes?**');
  passed('English error and Retry retain the exact query');

  await page.goto(origin + '/batter-genomes.html?page=999999&page_size=25');
  await ready();
  const last = await matchesApi();
  assert.equal(last.pagination.page, Math.ceil(last.pagination.total / 25));
  passed('Out-of-range page is clamped to the final page');

  const db = new DatabaseSync(path.join(candidate, 'catalog.sqlite'), { readOnly: true });
  const pending = db.prepare('SELECT b.genome_id FROM batter_genomes b WHERE NOT EXISTS (SELECT 1 FROM batter_release_assets a WHERE a.genome_id=b.genome_id) LIMIT 1').get();
  if (pending) {
    await page.goto(origin + '/batter-genomes.html?genome=' + pending.genome_id);
    await page.waitForSelector('.batter-detail-heading');
    await english();
    assert.ok((await page.locator('body').innerText()).includes('Data preparing'));
    assert.equal(await page.locator('.batter-open-browser').count(), 0);
  }
  const experimental = (await api('/api/genomes?evidence=experimental&page_size=25')).data.find(row => !row.has_batter);
  assert.ok(experimental);
  await page.goto(origin + '/genomes/' + experimental.genome_id + '.html?has_bigwig=true&page_size=25');
  await page.waitForSelector('.batter-detail-heading');
  assert.equal(new URL(page.url()).searchParams.get('has_bigwig'), 'true');
  await english();
  passed('Pending and experimental-only details; legacy links preserve filters');

  const prepared = manifest.batterBrowser.preparedGenomeIds[0];
  await page.goto(origin + '/batter-genomes.html?genome=' + prepared);
  await page.waitForSelector('.batter-detail-heading');
  await english();
  const detail = (await api('/api/genomes/' + prepared)).data;
  const index = detail.batter.downloads.find(file => file.filename === 'reference.fa.gz.fai');
  assert.ok(index);
  if (!uiOnly) {
    const head = await context.request.head(index.url);
    assert.equal(head.status(), 200);
    assert.equal(Number(head.headers()['content-length']), index.byte_size);
  }
  const config = await api('/api/genomes/' + prepared + '/jbrowse-config');
  const popupPromise = context.waitForEvent('page');
  await page.click('.batter-open-browser');
  const genomeBrowser = await popupPromise;
  await genomeBrowser.waitForURL(url => /^\/jbrowse\/(?:index\.html)?$/.test(url.pathname) && url.searchParams.get('config') === origin + '/api/genomes/' + prepared + '/jbrowse-config');
  await genomeBrowser.waitForLoadState('domcontentloaded');
  if (!uiOnly) {
    await genomeBrowser.waitForFunction(name => document.body.textContent.includes(name), config.tracks[0].name, {timeout:60000});
    await genomeBrowser.waitForTimeout(5000);
    assert.ok(!/Error: HTTP|Failed to fetch|HTTP 50[23]/.test(await genomeBrowser.locator('body').innerText()));
  }
  await genomeBrowser.screenshot({path:path.join(candidate,'catalog-jbrowse.png'),fullPage:true});
  await genomeBrowser.close();
  db.close();
  passed(uiOnly ? 'Prepared download links and JBrowse entry (asset transport not retested)' : 'Prepared downloads and real JBrowse entry load');
  report.assetTransport = uiOnly ? 'not_retested_existing_service_unavailable' : 'head_verified_and_jbrowse_entry_opened';

  await page.goto(origin + '/batter-genomes.html');
  await ready();
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.locator('[data-batter-sort="predictions"]').isVisible());
  await page.locator('[data-batter-sort="predictions"]').click();
  await ready();
  await english();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  await page.screenshot({path:path.join(candidate,'catalog-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1280,height:940});
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({path:path.join(candidate,'catalog-desktop.png'),fullPage:true});
  passed('Mobile sorting and responsive layout');
  assert.deepEqual(report.pageErrors, []);
  report.status = uiOnly ? 'passed_ui_only' : 'passed';
} catch (error) {
  report.status = 'failed';
  report.error = String(error);
  await page.screenshot({path:path.join(candidate,'catalog-failed.png'),fullPage:true}).catch(() => {});
  throw error;
} finally {
  writeFileSync(path.join(candidate,'catalog-interactions.acceptance.json'),JSON.stringify(report,null,2));
  await browser.close();
}
