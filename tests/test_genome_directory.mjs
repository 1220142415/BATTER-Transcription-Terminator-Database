import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import test from 'node:test';

const source = readFileSync(new URL('../prototype/accession-range/src/worker.js', import.meta.url), 'utf8');
const { default: worker } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const fixture = fileURLToPath(new URL('./genome_directory_sqlite.py', import.meta.url));
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../tmp/', import.meta.url));
mkdirSync(root, { recursive: true });
const dir = mkdtempSync(join(root, 'directory-test-'));
const databasePath = join(dir, 'directory.sqlite');
const python = process.platform === 'win32' ? 'py' : 'python3';
const pythonArgs = process.platform === 'win32' ? ['-3.13'] : [];
execFileSync(python, [...pythonArgs, fixture, databasePath, 'init']);
const queries = [];
const env = {
  BTED_METADATA_REVISION: 'a'.repeat(40), BTED_ANNOTATION_REVISION: 'b'.repeat(40),
  ASSETS: { fetch: async () => Response.json({ version: 'a'.repeat(24), reference_revision: 'a'.repeat(40), annotation_revision: 'b'.repeat(40) }) },
  BTED_DB: { prepare: sql => ({ bind: (...binds) => {
    const execute = () => {
      queries.push({ sql, binds });
      return JSON.parse(execFileSync(python, [...pythonArgs, fixture, databasePath, 'query'], { input: JSON.stringify({ sql, binds }), encoding: 'utf8' }));
    };
    return { all: async () => ({ results: execute() }), first: async () => execute()[0] };
  } }) },
};
const request = query => new Request(`https://bted.example/api/genome-directory?v=${'a'.repeat(24)}${query}`);
const ids = data => data.rows.map(row => row.batter[0]);

test('D1 directory returns only the requested page, keeps totals and uses a bounded indexed SELECT', async () => {
  const first = await worker.fetch(request(''), env);
  assert.equal(first.status, 200);
  const data = await first.json();
  assert.equal(data.rows.length, 25); assert.equal(data.total, 60);
  assert.deepEqual(ids(data).slice(0, 6), ['GCF_0', 'GCF_1', 'GCF_2', 'GCF_3', 'GCF_4', 'GCF_5']);
  assert.equal(queries.length, 3);
  assert.match(queries[1].sql, /LIMIT 25 OFFSET \?/);
  assert.ok(!queries[1].sql.includes('metadata_json'));
  const second = await (await worker.fetch(request('&page=2'), env)).json();
  assert.equal(second.rows.length, 25); assert.equal(second.total, 60); assert.equal(second.page, 2);
  assert.deepEqual(ids(second).slice(0, 2), ['GCF_25', 'GCF_26']);
  assert.equal(queries.length, 5);
  assert.equal(queries[3].binds.at(-1), 25);
});

test('substring search, combined filters and all sort fields work through actual SQLite indexes', async () => {
  const searched = await (await worker.fetch(request('&q=GCF_12'), env)).json();
  assert.equal(searched.total, 1); assert.deepEqual(ids(searched), ['GCF_12']);
  const partial = await (await worker.fetch(request('&q=GCF_1&annotation=Available'), env)).json();
  assert.deepEqual(ids(partial), ['GCF_1', 'GCF_10', 'GCF_12', 'GCF_14', 'GCF_16', 'GCF_18']);
  assert.equal(partial.rows[0].recoveredAnnotation.coverage, 'partial');
  const p2 = await (await worker.fetch(request('&phylum=P2&class=C2&annotation=Missing'), env)).json();
  assert.equal(p2.total, 29); assert.deepEqual(p2.facets.class, ['C2']);
  const before = queries.filter(query => query.sql.includes('COUNT(*)')).length;
  await worker.fetch(request('&phylum=P2&class=C2&annotation=Missing&page=2'), env);
  assert.equal(queries.filter(query => query.sql.includes('COUNT(*)')).length, before);
  for (const sort of ['accession', 'organism', 'size', 'endpoints', 'predictions', 'training']) {
    const result = await (await worker.fetch(request(`&sort=${sort}&direction=asc`), env)).json();
    assert.equal(result.total, 60); assert.equal(result.rows.length, 25);
  }
  const available = await (await worker.fetch(request('&annotation=Available'), env)).json();
  assert.equal(available.total, 31);
});

test('page responses are cached independently, normalized queries hit and invalid requests stay uncached', async () => {
  const original = globalThis.caches;
  const entries = new Map();
  globalThis.caches = { default: { match: async key => entries.get(key.url)?.clone(), put: async (key, response) => entries.set(key.url, response.clone()) } };
  try {
    const before = queries.length;
    const first = await worker.fetch(request(''), env);
    assert.equal(first.headers.get('x-bted-cache'), 'MISS');
    assert.equal((await worker.fetch(request('&page=1&sort=endpoints&direction=desc&ignored=x'), env)).headers.get('x-bted-cache'), 'HIT');
    assert.equal(queries.length, before + 2);
    assert.equal((await worker.fetch(request('&page=2'), env)).headers.get('x-bted-cache'), 'MISS');
    assert.equal(queries.length, before + 4);
    for (const query of ['&page=0', '&page=1.2', '&page=2001', '&sort=bad', '&direction=bad', '&q=xx', '&annotation=bad', '&page_size=1000']) {
      assert.equal((await worker.fetch(request(query), env)).status, 400);
    }
    const wrong = new Request(`https://bted.example/api/genome-directory?v=${'c'.repeat(24)}`);
    assert.equal((await worker.fetch(wrong, env)).status, 409);
    assert.equal(queries.length, before + 4);
  } finally { globalThis.caches = original; }
});

test.after(() => { assert.ok(dir.startsWith(root)); rmSync(dir, { recursive: true, force: true }); });
