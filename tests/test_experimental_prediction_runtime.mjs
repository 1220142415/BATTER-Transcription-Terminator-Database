import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const code = readFileSync(new URL('../worker/src/worker.js', import.meta.url), 'utf8') + '\nexport {experimentalPredictionTrack};';
const { default: worker, experimentalPredictionTrack } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const registry = JSON.parse(readFileSync(new URL('../data/registry/experimental-predictions.json', import.meta.url)));

test('experimental predictions require the exact reference and registered files and keep model evidence', () => {
  for (const [genome, row] of Object.entries(registry.genomes)) {
    const manifest = { assets: {} }, assets = [];
    for (const [file, info] of Object.entries(row.files)) {
      const path = `genomes/experimental-only/${genome}/predictions/${registry.run}/${file}`;
      const asset_kind = file.endsWith('.bed') ? 'bed' : file.endsWith('.tbi') ? 'tbi' : 'gff3';
      manifest.assets[path] = { ...info, asset_kind, revision: registry.revision, url: `https://huggingface.co/datasets/liurulong/terminator/resolve/${registry.revision}/v0.5.0/${path}` };
      assets.push({ ...info, asset_kind, logical_path: path, is_public: 1 });
    }
    const assembly = { accession: genome, prediction_count: row.prediction_count, prediction_run: registry.run, prediction_revision: registry.revision,
      prediction_reference_sha256: row.reference.fasta_sha256, prediction_contig_counts_json: JSON.stringify(row.contig_counts) };
    const fasta = { sha256: row.reference.fasta_sha256 };
    const request = new Request('https://bted.example');
    const track = experimentalPredictionTrack(request, manifest, assembly, assets, genome, fasta);
    assert.equal(track.metadata.btedAbout.evidence, 'Model prediction');
    assert.equal(track.metadata.btedAbout.record_count, row.prediction_count);
    assert.deepEqual(track.metadata.btedContigCounts, row.contig_counts);
    assert.throws(() => experimentalPredictionTrack(request, manifest, assembly, assets, genome, { sha256: 'wrong' }), /prediction_reference_mismatch/);
    assert.throws(() => experimentalPredictionTrack(request, manifest, assembly, assets.slice(1), genome, fasta), /prediction_asset_mismatch/);
  }
});

test('a new public directory version uses the current indexed rows and only accepts verified experimental prediction counts', async () => {
  const db = new DatabaseSync(':memory:');
  const version = 'c'.repeat(24), storage = 'a'.repeat(24), revision = 'b'.repeat(40), genome = 'GCF_000005845.2';
  db.exec(readFileSync(new URL('../database/migrations/0005_genome_directory.sql', import.meta.url), 'utf8'));
  db.exec(readFileSync(new URL('../database/migrations/0006_runtime_metadata.sql', import.meta.url), 'utf8'));
  db.prepare('INSERT INTO hf_runtime_release VALUES(1,?,?,?,?,?)').run(revision, 'ready', 42904, 0, 'd'.repeat(64));
  db.prepare('INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)').run(storage, revision, 'original', '{}', 'loading');
  const summary = { total: 1, sources: ['NCBI RefSeq'], phyla: [], counts: {}, storage_version: storage, experimental_predictions: { [genome]: 4447 } };
  db.prepare('INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)').run(version, revision, 'original', JSON.stringify(summary), 'ready');
  db.prepare('INSERT INTO hf_directory_genomes(version,genome_id,accession_key,organism_key,organism,source,genome_type,annotation,endpoints,predictions,training,phylum,class,"order",family,genus,species,search_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .run(storage, genome, genome, 'ecoli', 'E. coli', 'NCBI RefSeq', 'unknown', 'Missing', 0, 4447, 0, '', '', '', '', '', '', 'ecoli');
  const queries = [];
  const database = () => ({ prepare: sql => ({ bind: (...binds) => ({
    first: async () => { queries.push({sql,binds}); return db.prepare(sql).get(...binds); },
    all: async () => { queries.push({sql,binds}); return { results: db.prepare(sql).all(...binds) }; },
  }) }) });
  const env = { BTED_METADATA_REVISION: revision, BTED_RUNTIME_FIELDS: 'on', BTED_DB: database(),
    ASSETS: { fetch: async () => Response.json({ version, reference_revision: revision, annotation_revision: 'original' }) } };
  const request = new Request(`https://bted.example/api/genome-directory?v=${version}`);
  try {
    const response = await worker.fetch(request, env); assert.equal(response.status, 200);
    const data = await response.json(); assert.equal(data.rows[0].batter[10], 4447); assert.equal(data.rows[0].dataset.sortPredictions, '4447');
    assert.equal(queries.length, 4, 'no extra per-genome prediction lookup');
    assert.equal(queries.find(q => q.sql.includes('LIMIT 25 OFFSET')).binds[0], storage);
    db.prepare('UPDATE hf_directory_genomes SET predictions=9999 WHERE genome_id=?').run(genome);
    assert.equal((await worker.fetch(request, {...env, BTED_DB:database()})).status, 503);
  } finally { db.close(); }
});
