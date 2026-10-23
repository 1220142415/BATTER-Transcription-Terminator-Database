import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, rmSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

const source = readFileSync(new URL('../worker/src/worker.js', import.meta.url), 'utf8');
const {default: worker} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dir = mkdtempSync(join(tmpdir(), 'bted-collections-'));
const db = join(dir, 'test.sqlite');
const bridge = fileURLToPath(new URL('genome_directory_sqlite.py', import.meta.url));
const python = process.platform === 'win32' ? 'py' : 'python3';
const flags = process.platform === 'win32' ? ['-3.13'] : [];
execFileSync(python, [...flags, bridge, db, 'init']);
execFileSync(python, [...flags, '-c', `
import sqlite3,json,sys
d=sqlite3.connect(sys.argv[1])
d.executescript(open(sys.argv[2],encoding='utf-8').read())
d.executescript(open(sys.argv[3],encoding='utf-8').read())
for i,key in enumerate(['gtdb','experimental','gem'],1):
 v=str(i)*24
 summary=dict(total=1,sources=[key],phyla=['P1'],counts=dict(source={key:1},genome_type={'environmental':1},annotation={'Available':1},phylum={'P1':1},dataset={'prediction':int(i!=2),'experimental':int(i==2)}),feature_totals=dict(predictions=3 if i!=2 else 0,endpoints=5 if i==2 else 0,training=0))
 d.execute('INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)',(v,'a'*40,'b'*40,json.dumps(summary),'ready'))
 system=['gtdb','ncbi','gem_original'][i-1]
 taxversion='R207.0' if i==1 else ''
 d.execute('INSERT INTO bted_collections VALUES(?,?,?,?,?,?,?,?,?)',(key,v,key,'GTDB R207.0' if i==1 else 'Original','description',2 if i==1 else 1,int(i==1),system,taxversion))
 columns=[r[1] for r in d.execute('PRAGMA table_info(hf_directory_genomes)') if r[1]!='id']
 row=dict(zip(columns,d.execute('SELECT '+','.join('"'+c+'"' for c in columns)+' FROM hf_directory_genomes LIMIT 1').fetchone()))
 row.update(version=v,genome_id='GCA_000007325.1',source=key,genome_type='environmental',size=10000,contigs=1,predictions=3 if i!=2 else 0,training=0,endpoints=5 if i==2 else 0)
 d.execute('INSERT INTO hf_directory_genomes('+','.join('"'+c+'"' for c in columns)+') VALUES('+','.join('?' for _ in columns)+')',list(row.values()))
 d.execute('INSERT INTO gtdb_genome_assets VALUES(?,?,?,?)',(v,'GCA_000007325.1','0000','c'*40))
 d.execute('INSERT INTO bted_taxonomy_records(version,genome_id,system,taxonomy_version,status,match_method,phylum,species,source_url,retrieved_at,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
  (v,'GCA_000007325.1',system,taxversion,'verified','exact_assembly','P1','NCBI species' if i==2 else 'GTDB species','https://official.test/'+key,'2026-10-22','{}'))
 if i==2:
  d.execute('INSERT INTO bted_taxonomy_records(version,genome_id,system,taxonomy_version,status,match_method,phylum,species,source_url,retrieved_at,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
   (v,'GCA_000007325.1','gtdb','R207.0','verified','exact_assembly','GTDB phylum','Different GTDB species','https://official.test/gtdb','2026-10-22','{}'))
d.execute("INSERT INTO hf_directory_search(hf_directory_search) VALUES('rebuild')")
d.commit()
`, db, fileURLToPath(new URL('../database/migrations/0009_collections.sql', import.meta.url)), fileURLToPath(new URL('../database/migrations/0010_taxonomy_records.sql', import.meta.url))]);
const queries = [];
const env = {BTED_METADATA_REVISION: 'a'.repeat(40), BTED_ANNOTATION_REVISION: 'b'.repeat(40), BTED_D1_ONLY: 'on',
  BTED_DB: {prepare: sql => ({bind: (...binds) => {
    const execute = () => {
      queries.push({sql, binds});
      return JSON.parse(execFileSync(python, [...flags, bridge, db, 'query'], {input: JSON.stringify({sql, binds}), encoding:'utf8'}));
    };
    return {first: async () => execute()[0], all: async () => ({results: execute()})};
  }})}, ASSETS: {fetch: async () => {throw new Error('Collection metadata must not use static snapshots');}}};
const req = (path, init) => new Request('https://bted.test' + path, init);

test('three collections expose separate D1 counts and independent paged scopes', async () => {
  const response = await worker.fetch(req('/api/collections'), env);
  assert.equal(response.headers.get('x-bted-metadata-source'), 'd1');
  const summary = await response.json();
  assert.equal(summary.collections.length, 3);
  assert.equal(summary.collections[0].partial, true);
  for (const [i, key] of ['gtdb','experimental'].entries()) {
    const result = await worker.fetch(req(`/api/collections/${key}/directory?v=${String(i+1).repeat(24)}`), env);
    assert.equal(result.status, 200);
    const data = await result.json();
    assert.equal(data.total, 1);
    assert.deepEqual(data.sources, [key]);
    assert.equal(data.rows[0].dataset.sortEndpoints, i === 0 ? '0' : '5');
    assert.equal(data.rows[0].dataset.sortPredictions, i === 0 ? '3' : '0');
    if (key === 'experimental') assert.equal(data.rows[0].dataset.taxonomyStatus,'verified');
    assert.ok(queries.some(q => q.sql.includes('LIMIT 25 OFFSET ?') && q.binds[0] === String(i+1).repeat(24)));
  }
  assert.equal((await worker.fetch(req(`/api/collections/gtdb/directory?v=${'2'.repeat(24)}`), env)).status, 409);
  assert.equal((await worker.fetch(req(`/api/collections/gtdb/directory?v=${'1'.repeat(24)}&genome_type=environmental`), env)).status, 200);
});

test('classification records retain conflicting systems within each collection and expose the named default', async () => {
  const path='/api/collections/experimental/GCA_000007325.1/taxonomy';
  const r=await worker.fetch(req(path),env);
  assert.equal(r.status,200);
  const data=await r.json();
  assert.equal(data.default_system,'ncbi'); assert.equal(data.default_version,'');
  assert.equal(data.records.length,2);
  assert.equal(data.records.find(r=>r.system==='ncbi').species,'NCBI species');
  assert.equal(data.records.find(r=>r.system==='gtdb').species,'Different GTDB species');
  assert(data.records.every(r=>r.version==='2'.repeat(24)));
  assert.equal((await worker.fetch(req('/api/collections/gem/GCA_000007325.1/taxonomy'),env).then(r=>r.json())).records.length,1);
  assert.equal((await worker.fetch(req(path.replace('GCA_000007325.1','GCA_999999999.1')),env)).status,404);
  assert.equal((await worker.fetch(req(path+'?revision='+'f'.repeat(40)),env)).status,409);
});

test('GTDB scientific URLs retain per-genome revision and config uses the exact reference', async () => {
  const path = '/api/collections/gtdb/GCA_000007325.1';
  const data = await (await worker.fetch(req(path), env)).json();
  assert.match(data.browser_files['reference.fa.gz'].url, new RegExp(`/resolve/${'c'.repeat(40)}/v0.5.0/GTDB-TES-predictions/genomes/0000/`));
  assert.equal(data.revision, 'a'.repeat(40));
  assert.equal(data.taxonomy_label, 'GTDB R207.0');
  const original = globalThis.fetch;
  globalThis.fetch = async url => { assert.match(String(url), /reference.fa.gz.fai$/); return new Response('chr\t10000\t0\t60\t61\n'); };
  try {
    const response = await worker.fetch(req(path + '/config'), env);
    assert.equal(response.status, 200);
    const config = await response.json();
    assert.equal(config.metadata.collection, 'gtdb');
    assert.deepEqual(config.tracks.map(t => t.metadata.btedAbout.kind), ['reference','prediction']);
    const allTracks = [config.assemblies[0].sequence, ...config.tracks];
    assert.equal(new Set(allTracks.map(t => t.trackId)).size, allTracks.length, 'Reference sequence and feature track identifiers must be distinct');
    assert.equal(config.defaultSession.views[0].displayedRegions[0].end, 10000);
    assert.deepEqual(config.tracks.find(t => t.metadata.btedAbout.kind === 'prediction').metadata.btedContigCounts, {chr:3});
    assert.ok(config.tracks.every(t => t.adapter.gffGzLocation.uri.includes('/api/collections/gtdb/')));
    globalThis.fetch = async () => new Response('chr\t9999\t0\t60\t61\n');
    assert.equal((await worker.fetch(req(path + '/config'), env)).status, 503);
  } finally { globalThis.fetch = original; }
});

test('unregistered IDs, files, query URLs and stale scientific revisions fail closed', async () => {
  const base = '/api/collections/gtdb/GCA_000007325.1';
  for (const [path, status] of [[base+'?revision='+'f'.repeat(40),409], [base+'?url=https://evil.test/',409], [base+'/files/secrets.txt',404], [base+'/files/prediction.gff3.gz',416], ['/api/collections/gtdb/GCA_999999999.1',404]]) {
    const result = await worker.fetch(req(path, {headers: {range:'bytes=invalid'}}), env);
    assert.equal(result.status, status, path);
  }
});

test('warm collection page and pointer need no D1 reads in another isolate',async()=>{
 const prior=globalThis.caches,entries=new Map();
 globalThis.caches={default:{match:async k=>entries.get(k.url)?.clone(),put:async(k,r)=>entries.set(k.url,r.clone())}};
 try{
  const path='/api/collections/gtdb/directory?v='+'1'.repeat(24);
  const first=await worker.fetch(req(path),env);assert.equal(first.status,200);
  assert.equal(first.headers.get('x-bted-cache'),'MISS');
  const coldIsolate={...env,BTED_DB:{prepare(){throw new Error('Warm edge entry must not query D1');}}};
  const hit=await worker.fetch(req(path),coldIsolate);
  assert.equal(hit.status,200);assert.equal(hit.headers.get('x-bted-cache'),'HIT');
  assert.equal((await worker.fetch(req(path.replace('1'.repeat(24),'f'.repeat(24))),coldIsolate)).status,409);
  const pointer=[...entries].find(([key])=>key.includes('collection-pointer-v1'));
  assert.match(pointer[1].headers.get('cache-control'),/s-maxage=60(?:$|,)/);
 }finally{globalThis.caches=prior;}
});

test.after(() => rmSync(dir, {recursive:true, force:true}));


test('removed experimental reference links redirect only when explicitly registered, preserving view parameters',async()=>{
 const database={prepare(sql){return {bind(...params){return {async first(){
  if(sql.includes('FROM bted_collections'))return {version:'6'.repeat(24),summary_json:JSON.stringify({reference_registry_version:'5'.repeat(24)})};
  if(sql.includes('SELECT genome_id FROM hf_directory_genomes'))return params[0]==='5'.repeat(24)&&params[1]==='GCF_000005845.2'?{genome_id:params[1]}:null;
  throw new Error(sql);
 }}}}}};
 const env={BTED_DB:database};
 const r=await worker.fetch(new Request('https://bted.test/experimental/GCF_000005845.2.html?loc=NC_000913.3%3A1..2000'),env);
 assert.equal(r.status,302);assert.equal(r.headers.get('location'),'https://bted.test/genomes/GCF_000005845.2?loc=NC_000913.3%3A1..2000');
 assert.equal((await worker.fetch(new Request('https://bted.test/experimental/GCF_999.1'),env)).status,404);
});
