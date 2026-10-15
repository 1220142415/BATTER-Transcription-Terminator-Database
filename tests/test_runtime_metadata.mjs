import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const source = readFileSync(new URL('../prototype/accession-range/src/worker.js', import.meta.url), 'utf8');
const { default: worker, runtimeGenomeMetadata, runtimeCatalogueRow } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const revision = 'a'.repeat(40), id = 'GCF_TEST.1';
const row = { id: 1, genome_id: id, batch: '007', batch_rank: 1, otu_id: 'OTU-1', organism: 'Test bacterium', genome_type: 'MAG', source_collection: 'IMG', taxonomy: 'p__Test',
  augmentation_status: 'has_features', otu_augmentation_span: 1, otu_augmentation_window: 1, rfam_training_span: 0, rfam_training_window: 0, tes_prediction: 2,
  reference_bases: 10, reference_contigs: 1, reference_source: 'GEM representative', reference_source_sha256: 'b'.repeat(64), annotation_status: 'matched',
  annotation_accession: id, annotation_features: 3, annotation_reason: '', annotation_source_gff_sha256: 'c'.repeat(64), annotation_circular_overhang_features: 0,
  validation_augmentation: 'exact_training_window_sequence', validation_augmentation_features: 2, validation_prediction: 'contig_bounds_checked', validation_prediction_features: 2,
  metadata_sha256: 'd'.repeat(64) };
const files = Array.from({length:9}, (_, file_kind) => ({genome_key:1,file_kind,byte_size:100,sha256:'e'.repeat(64)}));

test('scalar schema reconstructs current metadata and file checksums without genome JSON, stored paths or correction history', async () => {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../prototype/accession-range/migrations/0006_runtime_metadata.sql', import.meta.url), 'utf8'));
  db.prepare('INSERT INTO hf_runtime_release VALUES(1,?,?,?,?,?)').run(revision,'ready',42904,9,'f'.repeat(64));
  db.prepare(`INSERT INTO hf_runtime_genomes(${Object.keys(row).join(',')}) VALUES(${Object.keys(row).map(()=>'?').join(',')})`).run(...Object.values(row));
  for(const file of files) db.prepare('INSERT INTO hf_runtime_files VALUES(?,?,?,?)').run(...Object.values(file));
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name='hf_runtime_corrections'").get().n,0);
  db.exec('CREATE TABLE hf_metadata_releases(revision TEXT,catalogue_header_json TEXT,status TEXT)');
  db.prepare('INSERT INTO hf_metadata_releases VALUES(?,?,?)').run(revision,JSON.stringify({revision,layout:'genome-first'}),'ready');
  const queries=[];
  const env={ BTED_METADATA_REVISION:revision, BTED_RUNTIME_FIELDS:'on', BTED_DB:{prepare(sql){
    assert.ok(!/metadata_json|catalogue_row_json|hf_genome_metadata|hf_registered_files/.test(sql),sql);
    return { bind(...values) { return {
      async first() { queries.push(sql); return db.prepare(sql).get(...values); },
      async all() { queries.push(sql); return {results:db.prepare(sql).all(...values)}; },
    }; } }; }
  }, ASSETS:{fetch:async()=>Response.json({revision,experimental:{},overlays:{}})} };
  try{
    const response=await worker.fetch(new Request('https://bted.example/api/batter/'+id),env);
    assert.equal(response.status,200);
    const actual=await response.json();
    const expected=runtimeGenomeMetadata(row,files);
    for(const key of Object.keys(expected)) assert.deepEqual(actual[key],expected[key]);
    assert.equal(actual.revision,revision);
    assert.equal(actual.reference.source_path,'genomes/OTU-1.fna.gz');
    assert.ok(actual.browser_files['reference.fa.gz'].url.endsWith(`/v0.5.0/genomes/batter-007/${id}/reference/reference.fa.gz`));
    assert.ok(!Object.keys(actual.validation).some(key=>key.includes('correction')));
    assert.deepEqual(runtimeCatalogueRow(row),[id,'007','OTU-1','Test bacterium','MAG',1,1,0,0,'matched',2,'p__Test','IMG']);
    const reads=queries.length;
    await worker.fetch(new Request('https://bted.example/api/batter/'+id),env);
    assert.equal(queries.length,reads,'cached scalar reads are shared');
    assert.equal((await worker.fetch(new Request('https://bted.example/api/batter/unknown'),env)).status,404);
    assert.throws(()=>runtimeGenomeMetadata(row,[...files,files[0]]),/invalid_file_kind/);
    const unready={...env,BTED_DB:{prepare:()=>({bind:()=>({first:async()=>({reference_revision:revision,status:'loading',genome_count:42904})})})}};
    assert.equal((await worker.fetch(new Request('https://bted.example/api/batter/'+id),unready)).status,503);
  }finally{db.close();}
});
