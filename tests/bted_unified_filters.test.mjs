import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import worker from '../prototype/accession-range/src/worker.js';

function environment() {
  const db = new DatabaseSync(':memory:');
  db.exec(`CREATE TABLE assemblies(release_version TEXT,accession TEXT,organism_name TEXT,strain TEXT);
    CREATE TABLE batter_genomes(genome_id TEXT,search_text TEXT,otu_id TEXT,genome_type TEXT,source_collection TEXT,
      domain TEXT,phylum TEXT,class TEXT,"order" TEXT,family TEXT,genus TEXT,species TEXT,tes_prediction INTEGER,
      otu_augmentation_window INTEGER,otu_augmentation_span INTEGER,rfam_training_window INTEGER,rfam_training_span INTEGER,augmentation_status TEXT);
    CREATE TABLE tracks(release_version TEXT,assembly_accession TEXT,source_id TEXT,pmid TEXT,assay TEXT,is_public INTEGER);
    CREATE TABLE publications(pmid TEXT,paper_title TEXT);
    CREATE TABLE sources(release_version TEXT,source_id TEXT,release_status TEXT,record_count INTEGER);
    CREATE TABLE endpoints(release_version TEXT,reference_assembly TEXT);
    CREATE TABLE assets(release_version TEXT,assembly_accession TEXT,asset_kind TEXT,active INTEGER,is_public INTEGER);
    CREATE TABLE release_versions(release_version TEXT,is_current INTEGER);
    INSERT INTO release_versions VALUES('v0.5.0',1);
    INSERT INTO assemblies VALUES('v0.5.0','shared','shared',''),('v0.5.0','experiment','experiment','');
    INSERT INTO batter_genomes(genome_id,search_text) VALUES('shared','shared'),('prediction','prediction');
    INSERT INTO assets VALUES('v0.5.0','shared','bigwig',1,0),('v0.5.0','experiment','bigwig',0,0);
    UPDATE batter_genomes SET phylum='P',class='Class P',"order"='Order P',genome_type='isolate',source_collection='NCBI',tes_prediction=7 WHERE genome_id='shared';
    UPDATE batter_genomes SET phylum='Q',class='Class Q',"order"='Order Q',genome_type='MAG',source_collection='IMG',tes_prediction=42 WHERE genome_id='prediction';`);
  return {BTED_RELEASE_VERSION:'v0.5.0', BTED_DB:{prepare(sql) {return {bind(...params) {return {
    first:async()=>db.prepare(sql).get(...params), all:async()=>({results:db.prepare(sql).all(...params)}),
  };}};}}};
}
async function ids(query) {
  const response = await worker.fetch(new Request('http://127.0.0.1/api/genomes?page_size=50&'+query), environment());
  assert.equal(response.status,200);
  return (await response.json()).data.map(row=>row.genome_id);
}
test('inclusive evidence filters include shared genomes; legacy membership stays exclusive', async()=>{
  assert.deepEqual(await ids('evidence=experimental'),['experiment','shared']);
  assert.deepEqual(await ids('evidence=prediction'),['prediction','shared']);
  assert.deepEqual(await ids('evidence=both'),['shared']);
  assert.deepEqual(await ids('membership=experimental'),['experiment']);
  assert.deepEqual(await ids('membership=batter'),['prediction']);
});
test('signal filter represents active scientific inventory even when still pending', async()=>{
  assert.deepEqual(await ids('has_bigwig=true'),['shared']);
  assert.deepEqual(await ids('has_bigwig=false'),['experiment','prediction']);
  assert.deepEqual(await ids('evidence=experimental&has_bigwig=true&q=shared'),['shared']);
});
test('invalid new filters are rejected', async()=>{
  for (const query of ['evidence=unknown','has_bigwig=yes']) {
    const response = await worker.fetch(new Request('http://127.0.0.1/api/genomes?'+query),environment());
    assert.equal(response.status,422);
  }
});

async function facets(query) {
  const response = await worker.fetch(new Request('http://127.0.0.1/api/genomes/facets?'+query), environment());
  assert.equal(response.status,200);
  return (await response.json()).options;
}
test('taxonomy options and counts depend only on parent ranks', async()=>{
  const all = [{value:'P',count:1},{value:'Q',count:1}];
  assert.deepEqual(await facets('rank=phylum'),all);
  assert.deepEqual(await facets('rank=phylum&q=no-match&evidence=experimental&has_bigwig=true&source=IMG&type=MAG&phylum=P&class=Class+P'),all);
  assert.deepEqual(await facets('rank=class&phylum=P&q=no-match&evidence=prediction&has_bigwig=false'),[{value:'Class P',count:1}]);
  assert.deepEqual(await facets('rank=order&phylum=P&class=Class+P&order=invalid'),[{value:'Order P',count:1}]);
  assert.deepEqual(await facets('rank=class&phylum=missing'),[]);
});
test('lists still combine text, taxonomy, source, type, evidence, and signal filters', async()=>{
  assert.deepEqual(await ids('q=shared&phylum=P&class=Class+P&source=NCBI&type=isolate&evidence=experimental&has_bigwig=true'),['shared']);
  assert.deepEqual(await ids('q=shared&phylum=P&source=IMG'),[]);
  assert.deepEqual(await ids('phylum=P&has_bigwig=false'),[]);
  assert.deepEqual(await ids('q=SHAR'),['shared']);
});
test('header sort values have stable ordering and reject unknown values', async()=>{
  assert.deepEqual(await ids('sort=genome_id_desc'),['shared','prediction','experiment']);
  assert.deepEqual(await ids('sort=predictions_desc'),['prediction','shared','experiment']);
  assert.deepEqual(await ids('sort=predictions_asc'),['shared','prediction','experiment']);
  for (const sort of ['otu_augmentation_asc','otu_augmentation_desc','rfam_training_asc','rfam_training_desc']) {
    assert.deepEqual(await ids('sort='+sort),['experiment','prediction','shared']);
  }
  const response=await worker.fetch(new Request('http://127.0.0.1/api/genomes?sort=unknown'),environment());
  assert.equal(response.status,422);
});
