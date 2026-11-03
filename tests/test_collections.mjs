import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, rmSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('../worker/src/worker.js', import.meta.url), 'utf8');
const {default: worker} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('homepage experimental record total comes from D1 and updates on reload', async () => {
  const cards = new Map(['experimental', 'gtdb', 'gem'].map(key => [key, new Map()]));
  const card = key => ({querySelector(selector) {
    if (!cards.get(key).has(selector)) cards.get(key).set(selector, {textContent: ''});
    return cards.get(key).get(selector);
  }});
  let reload, records = 29460;
  const payload = () => ({metadata_source: 'd1', collections: [
    {collection:'experimental',total:20,taxonomy_label:'NCBI Taxonomy',feature_totals:{endpoints:records,predictions:124740}},
    {collection:'gtdb',total:27275,partial:true,source_genome_count:62291,taxonomy_label:'GTDB R207.0'},
    {collection:'gem',total:42904,taxonomy_label:'GTDB R89 (GEM)',feature_totals:{predictions:122039507}}
  ]});
  const document = {querySelector(selector) {
    if (selector === '[data-collections-retry]') return {addEventListener(_, handler) {reload = handler;}};
    const match = /^\[data-collection-card="(\w+)"\]$/.exec(selector);
    return match ? card(match[1]) : null;
  }};
  runInNewContext(readFileSync(new URL('../site/assets/collections.js', import.meta.url), 'utf8'), {
    document, fetch: async () => ({ok:true,json:async () => payload()})
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(cards.get('experimental').get('[data-collection-progress]').textContent, '29,460 3′-end records');
  assert.match(cards.get('gtdb').get('[data-collection-progress]').textContent, /27,275 of 62,291/);
  assert.equal(cards.get('gem').get('[data-collection-progress]').textContent, '');
  records = 30000;
  await reload();
  assert.equal(cards.get('experimental').get('[data-collection-progress]').textContent, '30,000 3′-end records');
});

test('directory version follows D1 collection metadata without rebuilding HTML', async () => {
  let reload, version='a'.repeat(24);const events=[];
  const directory={dispatchEvent:event=>events.push(event)};
  const document={querySelector(selector){
    if(selector==='[data-collections-retry]')return {addEventListener:(_,handler)=>{reload=handler;}};
    return selector==='[data-genome-search-form][data-genome-prefix="experimental"]'?directory:null;
  }};
  class CustomEvent {constructor(type,options){this.type=type;this.detail=options.detail;}}
  runInNewContext(readFileSync(new URL('../site/assets/collections.js',import.meta.url),'utf8'),{document,CustomEvent,
    fetch:async()=>({ok:true,json:async()=>({metadata_source:'d1',collections:[{collection:'experimental',version,total:29,feature_totals:{endpoints:39896,predictions:124740}}]})})});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(events.at(-1).detail.version,version);
  version='b'.repeat(24);await reload();assert.equal(events.at(-1).detail.version,version);
  assert.equal(events.at(-1).type,'bted:collection-version');
});

test('retired aggregate directory and summary never access D1, assets or old cache entries', async () => {
  const prior = globalThis.caches;
  const untouched = () => assert.fail('retired entry point accessed a backing service');
  globalThis.caches = {default:{match:untouched,put:untouched}};
  const env = {BTED_DB:{prepare:untouched},ASSETS:{fetch:untouched}};
  try {
    for (const path of ['/api/genome-directory?v=old', '/api/site-summary']) {
      const r = await worker.fetch(new Request('https://bted.test'+path),env);
      assert.equal(r.status,410);
      assert.equal(r.headers.get('cache-control'),'no-store');
      assert.equal((await r.json()).collections,'/api/collections');
    }
    for (const path of ['/genomes','/genomes/','/genomes.html']) {
      const r = await worker.fetch(new Request('https://bted.test'+path+'?q=ecoli&sort=accession'),env);
      assert.equal(r.status,302);
      assert.equal(r.headers.get('location'),'https://bted.test/gem.html?q=ecoli&sort=accession');
    }
    for (const path of ['/assets/genome-directory.json','/assets/home.js']) {
      assert.equal((await worker.fetch(new Request('https://bted.test'+path),env)).status,410);
    }
  } finally {globalThis.caches=prior;}
});
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
d.execute('INSERT INTO tracks VALUES(?,?,?,?)', ('GCA_000007325.1', 'v0.4.0', 1, json.dumps({'signal_sample': {'sample_id': 'GSM1'}})))
d.executemany('INSERT INTO sources VALUES(?,?,?,?,?)', [
 ('GCA_000007325.1','v0.4.0','published_standardized',3,'Term-seq'),
 ('GCA_000007325.1','v0.4.0','published_standardized',2,'Rend-seq'),
 ('GCA_000007325.1','v0.4.0','published_standardized',1,'Term-seq'),
 ('GCA_000007325.1','v0.4.0','published_standardized',1,'3′ RNA-seq (modified from Term-seq)'),
 ('GCA_000007325.1','v0.4.0','audit_only',0,'dRNA-seq'),
 ('GCA_000007325.1','v0.4.0','published_standardized',0,'SEnd-seq'),
 ('GCA_000007325.1','v0.3.0','published_standardized',2,'Old-seq')])
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
  assert.deepEqual(summary.collections[0].phylum_counts, {P1: 1});
  for (const [i, key] of ['gtdb','experimental'].entries()) {
    const result = await worker.fetch(req(`/api/collections/${key}/directory?v=${String(i+1).repeat(24)}`), env);
    assert.equal(result.status, 200);
    const data = await result.json();
    assert.equal(data.total, 1);
    assert.deepEqual(data.sources, [key]);
    assert.equal(data.rows[0].dataset.sortEndpoints, i === 0 ? '0' : '5');
    assert.equal(data.rows[0].dataset.sortPredictions, i === 0 ? '3' : '0');
    if (key === 'experimental') assert.equal(data.rows[0].dataset.taxonomyStatus,'verified');
    if (key === 'experimental') {
      assert.equal(data.rows[0].dataset.signalTracks,'1');
      assert.deepEqual(data.rows[0].sequencingTechnologies,['Rend-seq','Term-seq']);
      assert.deepEqual(data.rows[0].filterData.assay,data.rows[0].sequencingTechnologies);
      assert.deepEqual(data.facets.assay,['Rend-seq','Term-seq']);
    }
    assert.ok(queries.some(q => q.sql.includes('LIMIT 25 OFFSET ?') && q.binds[0] === String(i+1).repeat(24)));
  }
  assert.equal((await worker.fetch(req(`/api/collections/gtdb/directory?v=${'2'.repeat(24)}`), env)).status, 409);
  assert.equal((await worker.fetch(req(`/api/collections/gtdb/directory?v=${'1'.repeat(24)}&genome_type=environmental`), env)).status, 200);
});

test('sequencing technology filters multi-labelled genomes and linked facets without changing counts', async () => {
  const path = `/api/collections/experimental/directory?v=${'2'.repeat(24)}`;
  const initial=await worker.fetch(req(path),env).then(r=>r.json());
  const client=readFileSync(new URL('../site/assets/genome-index.js',import.meta.url),'utf8');
  const fn=client.slice(client.indexOf('function filterExperimental('),client.indexOf('    function restoreMenu('));
  const legacyAssay=encodeURIComponent('3′ RNA-seq (modified from Term-seq)');
  const legacy=await worker.fetch(req(path+'&assay='+legacyAssay),env).then(r=>r.json());
  assert.equal(legacy.total,1);
  assert.deepEqual(legacy.facets.assay,['Rend-seq','Term-seq']);
  for (const params of ['', 'assay=Term-seq', 'assay=Rend-seq', 'assay=dRNA-seq', 'assay=Term-seq&annotation=Missing', 'assay=Rend-seq&phylum=P1', 'assay=Term-seq&q=Species']) {
    const scope={taxonomy:['phylum','class','order','family','genus','species'].map(rank=>({dataset:{taxonomyRank:rank}})),sortField:'endpoints',direction:'desc'};
    runInNewContext(fn+';globalThis.filter=filterExperimental;',scope);
    const local=JSON.parse(JSON.stringify(scope.filter(initial,new URL('https://bted.test/?'+params))));
    const remote=await worker.fetch(req(path+'&'+params),env).then(r=>r.json());
    assert.deepEqual(local.rows,remote.rows,params);
    assert.deepEqual(local.facets,remote.facets,params);assert.equal(local.total,remote.total,params);
  }
  for (const assay of ['Term-seq','Rend-seq']) {
    const r = await worker.fetch(req(path+'&assay='+encodeURIComponent(assay)),env);
    assert.equal(r.status,200);
    const data=await r.json();
    assert.equal(data.total,1);
    assert.equal(data.rows[0].dataset.sortEndpoints,'5');
    assert.deepEqual(data.rows[0].sequencingTechnologies,['Rend-seq','Term-seq']);
    assert.deepEqual(data.facets.assay,['Rend-seq','Term-seq']);
  }
  for (const params of ['assay=dRNA-seq','assay=SEnd-seq','assay=Old-seq','assay=Term-seq&annotation=Missing',"assay=%27%20OR%201%3D1--"]) {
    const r=await worker.fetch(req(path+'&'+params),env);
    assert.equal(r.status,200);
    const data=await r.json();assert.equal(data.total,0);assert.deepEqual(data.rows,[]);
  }
  const scoped=await worker.fetch(req(path+'&assay=Term-seq&annotation=Missing'),env).then(r=>r.json());
  assert.deepEqual(scoped.facets.assay,[]);
  assert.deepEqual(scoped.facets.annotation,['Available']);
  assert.equal((await worker.fetch(req(`/api/collections/gtdb/directory?v=${'1'.repeat(24)}&assay=Term-seq`),env)).status,400);
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
  const gem = await worker.fetch(req('/api/collections/gem/GCA_000007325.1/taxonomy'),env).then(r=>r.json());
  assert.equal(gem.records.length,1);
  assert.equal(gem.records[0].label,'GTDB R89 (GEM)');
  assert.equal(gem.records[0].taxonomy_version,'');
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
