import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const code = readFileSync(new URL('../worker/src/worker.js', import.meta.url), 'utf8');
const { default: worker } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const version = 'a'.repeat(24), storage = 'b'.repeat(24), revision = 'c'.repeat(40);
const db = new DatabaseSync(':memory:');
db.exec(readFileSync(new URL('../database/migrations/0005_genome_directory.sql', import.meta.url), 'utf8'));
db.exec('CREATE TABLE hf_genome_metadata(revision TEXT,genome_id TEXT,catalogue_row_json TEXT)');
const entries = [
  ['IMG', 'MAG', 'Available', 'Z9', 'C1', 'O1', 'Alpha', 0, 5, 1],
  ['IMG', 'SAG', 'Missing', 'P2', 'C2', 'O2', 'Beta', 0, 5, 0],
  ['NCBI RefSeq', 'isolate', 'Available', 'Z9', 'C1', 'O1', 'Alpha', 7, 0, 0],
  ['GEM', 'MAG', 'Missing', 'P3', 'C3', 'O3', 'Gamma', 0, 5, 0],
  ['NCBI RefSeq', 'isolate', 'Missing', 'P2', 'C2', 'O2', 'Beta', 2, 5, 0],
  ['IMG', 'MAG', 'Missing', 'Z9', 'C1', 'OX', 'Alpha auxiliary', 0, 0, 1],
];
const summary = { total: 6, sources: ['GEM', 'IMG', 'NCBI RefSeq'], phyla: ['P2', 'P3', 'Z9'],
  storage_version: storage, counts: { source: { GEM: 1, IMG: 3, 'NCBI RefSeq': 2 },
    genome_type: { MAG: 3, SAG: 1, isolate: 2 }, annotation: { Available: 2, Missing: 4 },
    phylum: { Z9: 3, P2: 2, P3: 1 }, dataset: { experimental: 2, prediction: 4, augmentation: 2 } } };
db.prepare('INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)').run(storage, revision, 'original', '{}', 'loading');
db.prepare('INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)').run(version, revision, 'original', JSON.stringify(summary), 'ready');
for (const [index, [source, type, annotation, phylum, cl, order, name, endpoints, predictions, training]] of entries.entries()) {
  const id = `GCF_TEST${index}.1`;
  const lineage = `p__${phylum};c__${cl};o__${order};f__F${order};g__G${order};s__Species ${order}`;
  const record = [id, '000', `OTU-${index}`, name, type, training, 0, 0, 0, annotation === 'Available' ? 'matched' : 'unavailable', predictions, lineage, source];
  db.prepare('INSERT INTO hf_directory_genomes(version,genome_id,accession_key,organism_key,organism,source,genome_type,annotation,endpoints,predictions,training,phylum,class,"order",family,genus,species,search_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .run(storage, id, id, name, name, source, type, annotation, endpoints, predictions, training, phylum, cl, order, `F${order}`, `G${order}`, `Species ${order}`, `${id} ${name}`.toLowerCase());
  db.prepare('INSERT INTO hf_genome_metadata VALUES(?,?,?)').run(revision, id, JSON.stringify(record));
}
db.exec("INSERT INTO hf_directory_search(hf_directory_search) VALUES('rebuild')");
const queries = [];
const env = { BTED_METADATA_REVISION: revision,
  ASSETS: { fetch: async () => Response.json({ version, reference_revision: revision, annotation_revision: 'original' }) },
  BTED_DB: { prepare: sql => ({ bind: (...binds) => ({
    first: async () => { queries.push({ sql, binds }); return db.prepare(sql).get(...binds); },
    all: async () => { queries.push({ sql, binds }); return { results: db.prepare(sql).all(...binds) }; },
  }) }) } };
async function query(params) {
  const response = await worker.fetch(new Request('https://bted.example/api/genome-directory?' + new URLSearchParams({ v: version, ...params })), env);
  assert.equal(response.status, 200);
  return response.json();
}

test('source, dataset, annotation and taxonomy constrain each other using indexed scoped facets', async () => {
  const all = await query({});
  assert.deepEqual(all.facets.source, summary.sources);
  assert.deepEqual(all.facets.phylum, ['Z9', 'P2', 'P3'], 'initial phyla use counts rather than names');
  assert.equal(queries.filter(q => q.sql.includes('json_group_array')).length, 0, 'initial menus reuse the published summary');
  const img = await query({ source: 'IMG' });
  assert.equal(img.total, 3);
  assert.deepEqual(img.facets.phylum, ['Z9', 'P2']);
  assert.deepEqual(img.facets.genome_type, ['MAG', 'SAG']);
  assert.deepEqual(img.facets.annotation, ['Available', 'Missing']);
  assert.deepEqual(img.facets.dataset, ['prediction', 'augmentation']);
  assert.deepEqual(img.facets.source, summary.sources, 'source alternatives ignore only their own selection');
  const aggregates = queries.filter(q => q.sql.includes('json_group_array'));
  assert.equal(aggregates.length, 1, 'menus with the same scope share one aggregate scan');
  assert.deepEqual(aggregates[0].binds, [storage, 'IMG']);
  const plan = db.prepare('EXPLAIN QUERY PLAN ' + aggregates[0].sql).all(...aggregates[0].binds);
  assert(plan.some(row => row.detail.includes('directory_source')));
  assert.equal(queries.filter(q => q.sql.includes('GROUP BY +phylum')).length, 1);
  await query({ source: 'IMG', sort: 'organism', direction: 'asc', page: '2' });
  assert.equal(queries.filter(q => q.sql.includes('json_group_array')).length, 1, 'sorting and pagination reuse facets');
  assert.equal(queries.filter(q => q.sql.includes('GROUP BY +phylum')).length, 1, 'pagination reuses phylum counts');
  const experimental = await query({ dataset: 'experimental' });
  assert.deepEqual(experimental.facets.source, ['NCBI RefSeq']);
  assert.deepEqual(experimental.facets.genome_type, ['isolate']);
  assert.deepEqual(experimental.facets.phylum, ['P2', 'Z9'], 'equal counts use name order');
  const annotated = await query({ source: 'IMG', annotation: 'Available' });
  assert.deepEqual(annotated.facets.source, ['IMG', 'NCBI RefSeq']);
  assert.deepEqual(annotated.facets.phylum, ['Z9']);
  assert.deepEqual(annotated.facets.genome_type, ['MAG']);
  assert.deepEqual(annotated.facets.annotation, ['Available', 'Missing']);
});

test('taxonomy menus follow parents and other filters without trapping parent choices', async () => {
  const data = await query({ source: 'IMG', phylum: 'Z9', class: 'C1', order: 'O1' });
  assert.equal(data.total, 1);
  assert.deepEqual(data.facets.phylum, ['Z9', 'P2']);
  assert.deepEqual(data.facets.class, ['C1']);
  assert.deepEqual(data.facets.order, ['O1', 'OX']);
  assert.deepEqual(data.facets.family, ['FO1']);
  assert.deepEqual(data.facets.source, ['IMG', 'NCBI RefSeq']);
  assert.deepEqual(data.facets.genome_type, ['MAG']);
  assert(!Object.hasOwn(data.facets, 'genus'), 'child menus remain locked until their parents are selected');
  const species = await query({ phylum: 'Z9', class: 'C1', order: 'O1', family: 'FO1', genus: 'GO1' });
  assert.deepEqual(species.facets.species, ['Species O1']);
});

test('search constrains menu values and impossible combinations report zero consistently', async () => {
  assert.equal((await query({ q: '!!!' })).total, 6);
  const beta = await query({ q: 'beta' });
  assert.equal(beta.total, 2);
  assert.deepEqual(beta.facets.source, ['IMG', 'NCBI RefSeq']);
  assert.deepEqual(beta.facets.genome_type, ['SAG', 'isolate']);
  assert.deepEqual(beta.facets.phylum, ['P2']);
  assert.deepEqual(beta.facets.dataset, ['experimental', 'prediction']);
  const empty = await query({ source: 'GEM', dataset: 'experimental' });
  assert.equal(empty.total, 0);
  assert.deepEqual(empty.rows, []);
  assert.deepEqual(empty.facets.source, ['NCBI RefSeq']);
  assert.deepEqual(empty.facets.dataset, ['prediction']);
  assert.deepEqual(empty.facets.phylum, []);
});

test('phylum order follows counts within the current filter scope', async () => {
  const prediction = await query({ dataset: 'prediction' });
  assert.deepEqual(prediction.facets.phylum, ['P2', 'P3', 'Z9']);
  const selected = await query({ dataset: 'prediction', phylum: 'Z9', class: 'C1' });
  assert.deepEqual(selected.facets.phylum, prediction.facets.phylum, 'phylum alternatives ignore their own selection and descendants');
});

test('complete small D1 pages filter locally with the same linked facets, search and ordering', async () => {
  const client=readFileSync(new URL('../site/assets/genome-index.js',import.meta.url),'utf8');
  const fn=client.slice(client.indexOf('function filterExperimental('),client.indexOf('    function restoreMenu('));
  const ranks=['phylum','class','order','family','genus','species'];
  const initial=await query({});
  for(const row of initial.rows) row.filterData=db.prepare('SELECT * FROM hf_directory_genomes WHERE version=? AND genome_id=?').get(storage,row.batter[0]);
  for(const params of [{},{q:'beta'},{q:'!!!'},{source:'IMG'},{source:'GEM',dataset:'experimental'},
    {phylum:'Z9',class:'C1'},{source:'IMG',annotation:'Available'},{sort:'organism',direction:'asc'},
    {q:'alpha',sort:'predictions',direction:'desc'},{dataset:'prediction',phylum:'Z9'}]){
    const scope={taxonomy:ranks.map(rank=>({dataset:{taxonomyRank:rank}})),sortField:params.sort||'endpoints',direction:params.direction||'desc'};
    runInNewContext(fn+';globalThis.filter=filterExperimental;',scope);
    const actual=JSON.parse(JSON.stringify(scope.filter(initial,new URL('https://test/?'+new URLSearchParams(params)))));
    const expected=await query(params);
    assert.deepEqual(actual.rows.map(r=>r.batter[0]),expected.rows.map(r=>r.batter[0]),JSON.stringify(params));
    assert.deepEqual(actual.facets,expected.facets,JSON.stringify(params));assert.equal(actual.total,expected.total);
  }
});

test.after(() => db.close());
