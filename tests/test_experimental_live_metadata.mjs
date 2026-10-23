import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const code = readFileSync(new URL("../worker/src/worker.js", import.meta.url), "utf8");
const { default: worker, applyD1Descriptions } = await import(`data:text/javascript;base64,${Buffer.from(code + "\nexport { applyD1Descriptions };").toString("base64")}`);

function fixture(predictionCount=0) {
  const id = "GCF_000009765.2";
  const source = { source_id: "S1", release_version: "v0.4.0", assembly_accession: id, publication_pmid: "123", record_count: 2,
    release_status: "published_standardized", assay_family: "Term-seq", evidence_class: "author_called_endpoint",
    record_root: `genomes/${id}/studies/PMID_123/endpoints.gff3.gz`,
    metadata_json: JSON.stringify({ assay: "Term-seq", sample_strain: "Reviewed strain", raw_data_accessions: "GSE123" }) };
  const paper = { pmid: "123", paper_title: "D1 paper", published_year: 2026, doi: "10.123/example", citation_json: '{"authors":"A; B"}' };
  const assembly = { accession: id, organism_name: "D1 organism", strain: "D1 reference", prediction_count:predictionCount,prediction_run:'BATTER-TPE-20261014' };
  const assets=[{ asset_key:"registered-file", logical_path:source.record_root, asset_kind:"gff3" },
    ...['prediction.bed','prediction.gff3.gz'].map(name=>({asset_key:name,logical_path:`genomes/experimental-only/${id}/predictions/${assembly.prediction_run}/${name}`,is_public:1}))];
  const track = { source_id: "S1", is_public: 1, metadata_json: '{}' };
  const queries = [];
  const release = { release_version: "v0.4.0", is_current: 1 };
  const env = { ASSETS: { fetch() { throw new Error("Live metadata must never read a TSV or static manifest"); } }, BTED_DB: { prepare(sql) {
    queries.push(sql);
    return { bind(...params) { return {
      async first() {
        if (sql.includes('FROM bted_collections')) return { version:'2'.repeat(24),taxonomy_system:'ncbi',taxonomy_version:'' };
        if (sql.includes("FROM release_versions")) return release;
        if (sql.includes("FROM assemblies")) return params[1] === id ? assembly : null;
        if (sql.includes("SELECT genome_id,predictions")) return {genome_id:id,predictions:predictionCount};
        if (sql.includes("SELECT d.*")) return { genome_id: id, phylum: "D1 phylum", source: "NCBI RefSeq",predictions:predictionCount };
        throw new Error(sql);
      },
      async all() {
        if (sql.includes('FROM bted_taxonomy_records')) return {results:[{version:'2'.repeat(24),genome_id:id,system:'ncbi',taxonomy_version:'',status:'verified',tax_id:227882,phylum:'D1 phylum',species:'NCBI species',source_url:'https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=227882',retrieved_at:'2026-10-22',evidence_json:'{}'}]};
        if (sql.includes("FROM source_accessions")) return { results: [{ source_id: "S1", external_url: "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123" }] };
        if (sql.includes("FROM publications")) return { results: [paper] };
        if (sql.includes("FROM sources")) return { results: [source] };
        if (sql.includes("FROM tracks")) return { results: [track] };
        if (sql.includes("FROM contigs")) return { results: [{ contig_accession: "chr", length_bp: 100 }] };
        if (sql.includes("FROM assets")) return { results: assets };
        throw new Error(sql);
      },
    }; } };
  } } };
  return { id, env, source, paper, queries, assets };
}

test('registered predictions are separate from study records and ZIP, with D1 download links',async()=>{
 const f=fixture(9),request=new Request(`https://bted.test/api/assemblies/${f.id}/page-metadata`);
 const data=await (await worker.fetch(request,f.env)).json();
 assert.equal(data.record_count,2);assert.equal(data.predictions.count,9);
 assert.equal(data.predictions.reference_scope,'experimental');
 assert.deepEqual(data.predictions.downloads.map(r=>r.url),['/api/assets/prediction.bed','/api/assets/prediction.gff3.gz']);
 assert(data.downloads.every(r=>!r.url.includes('prediction')));
 f.assets.pop();
 assert.equal((await worker.fetch(request,f.env)).status,503);
});

test('experimental collection config retains predictions and signals without importing training tracks',async()=>{
 const f=fixture(9);
 const tracks=['reference','endpoint','signal','prediction','augmentation'].map(kind=>({trackId:kind,adapter:{uri:`fixed-${kind}`},metadata:{btedAbout:{kind}}}));
 const config={tracks,defaultSession:{views:[{tracks:tracks.map(t=>({type:'FeatureTrack',configuration:t.trackId}))}]},metadata:{}};
 f.env.ASSETS={fetch:async()=>Response.json(config)};
 const response=await worker.fetch(new Request(`https://bted.test/api/collections/experimental/${f.id}/config`),f.env);
 assert.equal(response.status,200);const data=await response.json();
 assert.deepEqual(data.tracks.map(t=>t.trackId),['reference','endpoint','signal','prediction']);
 assert.deepEqual(data.tracks.find(t=>t.trackId==='prediction').adapter,{uri:'fixed-prediction'});
 assert.equal(data.defaultSession.views[0].tracks.at(-1).configuration,'prediction');
});

test("study metadata and ZIP manifest query D1 without static files, including refreshed values", async () => {
  const f = fixture();
  const request = new Request(`https://bted.example/api/assemblies/${f.id}/page-metadata`);
  let response = await worker.fetch(request, f.env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-bted-metadata-source"), "d1");
  let data = await response.json();
  assert.equal(data.sources[0].assay_family, "Term-seq");
  assert.equal(data.sources[0].publication.paper_title, "D1 paper");
  assert.equal(data.record_count, 2);
  assert.equal(data.assembly.classifications.default_system,'ncbi');
  assert.equal(data.assembly.classifications.records[0].tax_id,227882);
  assert.deepEqual(data.downloads, [
    { path: `${f.id}/metadata.tsv`, url: `/api/assemblies/${f.id}/metadata.tsv` },
    { path: `${f.id}/studies/PMID_123/endpoints.gff3.gz`, url: "/api/assets/registered-file" },
  ]);
  f.source.assay_family = "D1 changed assay"; f.paper.paper_title = "D1 changed title";
  data = await (await worker.fetch(request, f.env)).json();
  assert.equal(data.sources[0].assay_family, "D1 changed assay");
  const tsv = await worker.fetch(new Request(`https://bted.example/api/assemblies/${f.id}/metadata.tsv`), f.env);
  assert.equal(tsv.headers.get("cache-control"), "no-store");
  const text = await tsv.text();
  assert.match(text, /D1 changed assay/); assert.match(text, /D1 changed title/); assert.doesNotMatch(text, /dRNA-seq/);
  assert.match(text,/taxonomy_system/); assert.match(text,/NCBI species/);
  assert(f.queries.some(sql => sql.includes('d.version=? AND d.genome_id=?')));
  assert(f.queries.every(sql => !sql.includes('ORDER BY r.rowid DESC')));
  assert(f.queries.every(sql => !/endpoints|hf_runtime_genomes/.test(sql)));
});

test("unknown assembly returns 404, failed D1 returns 503 instead of old metadata", async () => {
  const f = fixture();
  assert.equal((await worker.fetch(new Request("https://bted.example/api/assemblies/GCF_999.1/page-metadata"), f.env)).status, 404);
  const original = f.env.BTED_DB.prepare;
  f.env.BTED_DB.prepare = sql => { if (sql.includes("FROM assemblies")) throw new Error("offline"); return original(sql); };
  const response = await worker.fetch(new Request(`https://bted.example/api/assemblies/${f.id}/page-metadata`), f.env);
  assert.equal(response.status, 503); assert.equal(response.headers.get("cache-control"), "no-store");
});

test("JBrowse descriptions use current D1 while coordinates and data adapters stay intact", async () => {
  const f = fixture();
  const config = { tracks: [{ adapter: { type: "Gff3Adapter", gffLocation: { uri: "fixed-coordinate-file" } },
    metadata: { source_id: "S1", raw_data_links: "https://old.example", btedAbout: { kind: "endpoint", raw_data_url: "https://old.example", assay: "Term-seq / dRNA-seq", title: "old", record_count: 999 } } }] };
  const adapter = structuredClone(config.tracks[0].adapter);
  await applyD1Descriptions(config, f.env, f.id);
  const about = config.tracks[0].metadata.btedAbout;
  assert.equal(about.assay, "Term-seq"); assert.equal(about.title, "D1 paper"); assert.equal(about.record_count, 2);
  assert.equal(about.raw_data_url, "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123");
  assert.equal(config.tracks[0].metadata.raw_data_links, about.raw_data_url);
  assert.deepEqual(config.tracks[0].adapter, adapter);
});

test("production D1-only mode never falls back to HF metadata when misconfigured", async () => {
  for (const path of ["/api/batter-catalogue", "/api/batter/GCF_000009765.2"]) {
    const response = await worker.fetch(new Request('https://bted.example' + path), { BTED_D1_ONLY: 'on' });
    assert.equal(response.status,503);
    assert.equal((await response.json()).error,'d1_metadata_not_configured');
  }
});


test('audit-only reference metadata retains its explicitly pinned D1 registration after collection exclusion', async () => {
  const f=fixture(9), original=f.env.BTED_DB.prepare;
  f.source.release_status='audit_only'; f.source.record_count=0;
  f.env.BTED_DB.prepare=sql=>({bind(...params){const statement=original(sql).bind(...params);
    if(sql.includes('FROM bted_collections'))return {...statement, async first(){return {...await statement.first(),version:'6'.repeat(24),summary_json:JSON.stringify({reference_registry_version:'5'.repeat(24)})};}};
    if(sql.includes('SELECT d.*'))return {...statement, async first(){return params[0]==='5'.repeat(24)?statement.first():null;}};
    return statement;
  }});
  const response=await worker.fetch(new Request(`https://bted.test/api/assemblies/${f.id}/page-metadata`),f.env);
  assert.equal(response.status,200);
  const data=await response.json();assert.equal(data.record_count,0);assert.equal(data.study_count,0);assert.equal(data.predictions.count,9);
  assert.equal(data.sources[0].release_status,'audit_only');assert.equal(data.assembly.classifications.records[0].species,'NCBI species');
});
