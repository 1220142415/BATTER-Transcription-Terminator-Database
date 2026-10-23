import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const code = readFileSync(new URL('worker/src/worker.js', root), 'utf8')
  + '\nexport { applyConditionSignals, registeredConditionAsset };';
const { default: worker, applyConditionSignals, registeredConditionAsset } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const registry = JSON.parse(readFileSync(new URL('data/registry/s021-derived-signals.json', root)));

function fixture() {
  const endpoint = { trackId: 'endpoints', assemblyNames: ['B31'], metadata: { source_ids: [registry.source_id],
    btedAbout: { kind: 'endpoint', pmid: registry.pmid, record_count: 1905 } } };
  const config = { assemblies: [{ name: 'B31' }], tracks: [endpoint, { trackId: 'genes' }],
    defaultSession: { views: [{ tracks: [{ configuration: 'endpoints' }, { configuration: 'genes' }] }] } };
  const row = { source_id: registry.source_id, assembly_accession: registry.genome_id, pmid: registry.pmid, is_public: 1,
    metadata_json: JSON.stringify({ signal_conditions: registry.conditions }) };
  const assets = registry.conditions.flatMap(c => c.signals.map(s => ({ asset_key:s.asset_key, logical_path:s.path.slice(7),
    origin_url:s.url, asset_kind:'bigwig', source_id:registry.source_id, assembly_accession:registry.genome_id,
    sha256:s.sha256, byte_size:s.byte_size, is_public:1 })));
  const env = { BTED_DB: { prepare(sql) { return { bind() { return { all: async () => ({ results: sql.includes('FROM tracks') ? [row]
    : sql.includes('FROM publications') ? [{ pmid: registry.pmid, paper_title: 'Current D1 paper', citation_json: '{}' }]
    : sql.includes('FROM sources') ? [{ source_id: registry.source_id, publication_pmid: registry.pmid, assay_family: '3′ RNA-seq (modified from Term-seq)', record_count: 1905, metadata_json: '{}' }]
    : assets }) }; } }; } },
    ASSETS: { fetch: async () => new Response(JSON.stringify(config), { headers: { 'content-type':'application/json' } }) } };
  const request = new Request(`https://bted.test/jbrowse/assemblies/${registry.genome_id}.config.json`);
  return { config, row, assets, env, request };
}

test('existing browser URL loads two conditions from D1 with all 22 aliases and both strand files', async () => {
  const { env, request } = fixture();
  const response = await worker.fetch(request, env);
  assert.equal(response.status, 200);
  const config = await response.json();
  const signals = config.tracks.filter(t => t.metadata?.btedConditionSignal);
  assert.deepEqual(signals.map(t => t.metadata.condition_id), ['log', 'TS-stationary']);
  assert.deepEqual(config.tracks.map(t => t.trackId), ['endpoints', ...signals.map(t => t.trackId), 'genes']);
  assert.deepEqual(config.defaultSession.views[0].tracks.map(t => t.configuration), config.tracks.map(t => t.trackId));
  const aliases = decodeURIComponent(config.assemblies[0].refNameAliases.adapter.location.uri.slice(16)).trim().split('\n');
  assert.equal(aliases.length, 22);
  assert.ok(aliases.includes('NC_001318.1\tchr'));
  for (const signal of signals) {
    assert.equal(signal.metadata.btedAbout.sample_id, undefined);
    assert.equal(signal.name, `PMID 37402717 · 3′ RNA-seq · ${registry.conditions.find(c => c.condition_id === signal.metadata.condition_id).label}`);
    assert.equal(signal.metadata.btedDownloads.length, 2);
    assert.deepEqual(signal.adapter.subadapters.map(s => s.source), ['plus', 'minus']);
    assert.ok(signal.adapter.subadapters.every(s => s.bigWigLocation.uri.includes('/' + registry.revision + '/')));
    assert.equal(signal.displays[0].scaleType, 'linear');
    assert.equal(signal.displays[0].autoscale, 'local');
  }
});

test('changing D1 conditions changes visible tracks without rebuilding static config', async () => {
  const { env, row, request } = fixture();
  row.metadata_json = JSON.stringify({ signal_conditions: registry.conditions.slice(0, 1) });
  const response = await worker.fetch(request, env);
  const config = await response.json();
  assert.deepEqual(config.tracks.filter(t => t.metadata?.btedConditionSignal).map(t => t.metadata.condition_id), ['log']);
});

test('condition registration requires exact pinned registered pair and verified reference', async () => {
  for (const change of ['missing-file', 'moving-url', 'foreign-source', 'unverified-reference']) {
    const { env, row, assets, request } = fixture();
    if (change === 'missing-file') assets.pop();
    if (change === 'moving-url') assets[0].origin_url = assets[0].origin_url.replace(registry.revision, 'main');
    if (change === 'foreign-source') assets[0].source_id = 'BATTER_S1_001';
    if (change === 'unverified-reference') {
      const metadata = JSON.parse(row.metadata_json);
      metadata.signal_conditions[0].reference.browser_status = 'pending';
      row.metadata_json = JSON.stringify(metadata);
    }
    assert.equal((await worker.fetch(request, env)).status, 503, change);
  }
});

test('applying condition tracks again preserves session, reference aliases and other tracks', async () => {
  const { config, row, env, request } = fixture();
  await applyConditionSignals(config, request, env, registry.genome_id, [row]);
  const before = structuredClone(config);
  await applyConditionSignals(config, request, env, registry.genome_id, [row]);
  assert.deepEqual(config, before);
  const { assets } = fixture();
  assert.ok(registeredConditionAsset(assets[0]));
  assert.equal(registeredConditionAsset({ ...assets[0], origin_url:'https://evil.test/data.bw' }), null);
});
