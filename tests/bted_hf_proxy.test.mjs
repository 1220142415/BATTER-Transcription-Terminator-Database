import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../prototype/accession-range/src/worker.js';

const revision = 'a'.repeat(40), sha = 'b'.repeat(64);
const origin = `https://huggingface.co/datasets/liurulong/terminator/resolve/${revision}/v0.5.0/batter/batches/000/genomes/2228664028/reference.fa.gz`;
const manifest = { releaseVersion: 'v0.5.0', publicationStatus: 'hf_preview', releaseRevision: null,
  releaseManifestSha256: 'c'.repeat(64), batchRevisions: { '000': revision }, assets: {}, experimentalAvailable: false };
const publication = { publication_status: 'hf_preview', metadata_json: JSON.stringify({ batch: '000',
  files: { 'reference.fa.gz': { url: origin, sha256: sha, byte_size: 128 } } }) };
function env(row = publication, data = manifest) {
  return { BTED_RELEASE_VERSION: 'v0.5.0', ASSETS: { fetch: async () => Response.json(data) },
    BTED_DB: { prepare: (sql) => ({ bind: () => ({ first: async () => sql.includes('release_versions') ? { release_version: 'v0.5.0' } : row }) }) } };
}
const route = `/api/genomes/2228664028/files/reference.fa.gz?revision=${revision}`;
async function request(path = route, options = {}, configuration = env()) {
  return worker.fetch(new Request('http://127.0.0.1' + path, options), configuration);
}

test('pinned Range and HEAD stream HF and expose immutable identity', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (url, init) => {
      assert.equal(url, origin);
      const range = init.headers.get('range');
      assert.equal(range, 'bytes=32-63');
      return new Response(init.method === 'HEAD' ? null : new Uint8Array(32), { status: 206,
        headers: { 'content-range': 'bytes 32-63/128', 'content-length': '32' } });
    };
    const response = await request(route, { headers: { range: 'bytes=32-63' } });
    assert.equal(response.status, 206);
    assert.equal((await response.arrayBuffer()).byteLength, 32);
    assert.equal(response.headers.get('x-bted-hf-revision'), revision);
    assert.match(response.headers.get('cache-control'), /immutable/);
    const head = await request(route, { method: 'HEAD', headers: { range: 'bytes=32-63' } });
    assert.equal(head.status, 206);
    assert.equal((await head.arrayBuffer()).byteLength, 0);
  } finally { globalThis.fetch = original; }
});

test('unknown files, pending batches, wrong commits and malformed proofs never fetch', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = () => { throw new Error('Must not fetch'); };
    assert.equal((await request(route.replace('reference.fa.gz', 'secret'))).status, 404);
    assert.equal((await request(route, {}, env(null))).status, 503);
    assert.equal((await request(route.replace(revision, 'd'.repeat(40)))).status, 409);
    assert.equal((await request(route, {}, env(publication, { ...manifest, batchRevisions: { '000': 'main' } }))).status, 503);
    assert.equal((await request(route, { headers: { range: 'bytes=999-1000' } })).status, 416);
    assert.equal((await request(route, { headers: { range: 'bytes=0-1,4-5' } })).status, 416);
  } finally { globalThis.fetch = original; }
});

test('HF failures and wrong Range responses never receive successful cache headers', async () => {
  const original = globalThis.fetch;
  try {
    for (const upstream of [() => { throw new Error('Offline'); }, () => new Response(null, { status: 429 }),
      () => new Response(new Uint8Array(16), { status: 206, headers: { 'content-range': 'bytes 0-15/999', 'content-length': '16' } }),
      () => new Response(new Uint8Array(128), { status: 200, headers: { 'content-length': '128' } })]) {
      globalThis.fetch = upstream;
      const response = await request(route, { headers: { range: 'bytes=0-15' } });
      assert.ok(response.status >= 500);
      assert.equal(response.headers.get('cache-control'), 'no-store');
    }
  } finally { globalThis.fetch = original; }
});

test('unstamped URLs are not immutable; suffix ranges are normalized', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_, init) => {
      assert.equal(init.headers.get('range'), 'bytes=112-127');
      return new Response(new Uint8Array(16), { status: 206,
        headers: { 'content-range': 'bytes 112-127/128', 'content-length': '16' } });
    };
    const response = await request(route.split('?')[0], { headers: { range: 'bytes=-16' } });
    assert.equal(response.status, 206);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  } finally { globalThis.fetch = original; }
});

test('preview gateway cannot expose local resources through a public request', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = () => { throw new Error('Must not fetch'); };
    for (const gateway of ['http://example.com/', 'http://127.0.0.1:17998/private/', 'http://user:secret@127.0.0.1:17998/']) {
      const response = await request(route, {}, { ...env(), HF_PREVIEW_GATEWAY: gateway });
      assert.equal(response.status, 403);
      assert.equal(response.headers.get('cache-control'), 'no-store');
    }
    const response = await worker.fetch(new Request('https://bted.example' + route), { ...env(), HF_PREVIEW_GATEWAY: 'http://127.0.0.1:17998/' });
    assert.equal(response.status, 503); // Partial releases are rejected before proxy access on public hosts.
  } finally { globalThis.fetch = original; }
});

test('migrated genome assets require the exact fixed revision, group, genome and category path', async () => {
  const original = globalThis.fetch;
  const data = { ...manifest, publicationStatus: 'public_download', releaseRevision: revision, layout: 'genome-first-v1' };
  const url = origin.replace('batter/batches/000/genomes/2228664028/', 'genomes/batter-000/2228664028/reference/');
  const row = { publication_status: 'public_download', metadata_json: JSON.stringify({ batch: '000',
    files: { 'reference.fa.gz': { url, sha256: sha, byte_size: 128 } } }) };
  try {
    globalThis.fetch = async (target) => {
      assert.equal(target, url);
      return new Response(new Uint8Array(128), { headers: { 'content-length': '128' } });
    };
    assert.equal((await request(route, {}, env(row, data))).status, 200);
    for (const bad of [url.replace('batter-000', 'batter-001'), url.replace('2228664028', 'other'),
      url.replace('/reference/', '/training/'), url.replace(revision, 'c'.repeat(40))]) {
      const changed = { ...row, metadata_json: JSON.stringify({ batch:'000', files:{'reference.fa.gz':{url:bad,sha256:sha,byte_size:128}} }) };
      assert.equal((await request(route, {}, env(changed, data))).status, 503);
    }
  } finally { globalThis.fetch = original; }
});
