import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import test from "node:test";
const source=readFileSync(new URL("../worker/src/worker.js",import.meta.url),"utf8");
const {default:worker}=await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
test("inline extension matches its maintainable source",()=>{
 const module=readFileSync(new URL("../worker/src/experimental-v05.js",import.meta.url),"utf8").replaceAll("export async function ","async function ");
 assert(source.replaceAll("\r\n","\n").startsWith("// BTED_EXPERIMENTAL_V05_EXTENSION_BEGIN\n"+module.replaceAll("\r\n","\n")+"\n// BTED_EXPERIMENTAL_V05_EXTENSION_END"));
});
const db=new DatabaseSync(":memory:");
db.exec(`CREATE TABLE bted_experimental_v05_assemblies(accession TEXT,organism TEXT,endpoint_count INTEGER,source_count INTEGER,contigs_json TEXT,hf_revision TEXT);
CREATE TABLE bted_experimental_v05_sources(source_id TEXT,assembly_accession TEXT,pmid TEXT,doi TEXT,evidence_class TEXT,assay TEXT,record_count INTEGER,metadata_json TEXT);
CREATE TABLE bted_experimental_v05_files(logical_path TEXT,assembly_accession TEXT,source_id TEXT,file_kind TEXT,byte_size INTEGER,sha256 TEXT,hf_revision TEXT);`);
const id="GCF_003019785.1", revision="277f829ad3b408f60925122ff2a498c8a158e7c3", prefix=`genomes/experimental-only/${id}`;
db.prepare("INSERT INTO bted_experimental_v05_assemblies VALUES(?,?,?,?,?,?)").run(id,"Approved reference",663,1,JSON.stringify({ref:2000000}),revision);
db.prepare("INSERT INTO bted_experimental_v05_sources VALUES(?,?,?,?,?,?,?,?)").run("R03",id,"38436569","10.example/approved","author_called_TTS","Term-seq",663,JSON.stringify({paper_title:"Study title",scientific_caveat:"Author-reported sites"}));
for(const name of ["reference/reference.fa.gz","reference/reference.fa.gz.fai","reference/reference.fa.gz.gzi","annotations/genes.gff3.gz","annotations/genes.gff3.gz.tbi","studies/DOI_example/sources/R03/endpoints.gff3.gz","studies/DOI_example/sources/R03/endpoints.gff3.gz.tbi","studies/DOI_example/sources/R03/endpoints.bed.gz"]) {
 db.prepare("INSERT INTO bted_experimental_v05_files VALUES(?,?,?,?,?,?,?)").run(prefix+"/"+name,id,name.includes("R03")?"R03":null,name.split("/").at(-1),100,"a".repeat(64),revision);
}
for(const name of ["0005_genome_directory.sql","0009_collections.sql","0010_taxonomy_records.sql"]) {
 const base=new URL("../database/migrations/",import.meta.url);
 db.exec(readFileSync(new URL(name,base),"utf8"));
}
const version="a".repeat(24);
db.prepare("INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)").run(version,revision,revision,JSON.stringify({total:1}),"ready");
db.prepare("INSERT INTO bted_collections VALUES(?,?,?,?,?,?,?,?,?)").run("experimental",version,"Experimental 3′ ends","NCBI Taxonomy","",1,0,"ncbi","");
db.prepare(`INSERT INTO hf_directory_genomes(version,genome_id,accession_key,organism_key,organism,source,genome_type,annotation,endpoints,predictions,training,phylum,class,"order",family,genus,species,search_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(version,id,id,"reference","Approved reference","NCBI RefSeq","unknown","Available",663,0,0,"","","","","","",id);
db.prepare("INSERT INTO bted_taxonomy_records(version,genome_id,system,taxonomy_version,status,match_method,source_url,retrieved_at,evidence_json) VALUES(?,?,?,?,?,?,?,?,?)").run(version,id,"ncbi","","pending","approved_reference","https://example.test/assembly","2026-10-31","{}");
db.exec("CREATE TABLE release_versions(release_version TEXT,is_current INTEGER);INSERT INTO release_versions VALUES('v0.4.0',1)");
const assetPaths=[];
const env={ASSETS:{fetch:async request=>{assetPaths.push(new URL(request.url).pathname);return new Response('<main data-live-experimental>Shared experimental shell</main>',{headers:{"content-type":"text/html"}})}},BTED_EXPERIMENTAL_V05:"on",BTED_DB:{prepare(sql){return {bind(...args){return {first:async()=>db.prepare(sql).get(...args),all:async()=>({results:db.prepare(sql).all(...args)})}}}}}};
const request=(path,options)=>worker.fetch(new Request("https://bted.test"+path,options),env);
test("approved new assembly page, metadata and config retain evidence and reference binding",async()=>{
 const page=await request(`/experimental/${id}.html`);assert.equal(page.status,200);assert.match(await page.text(),/Shared experimental shell/);assert.equal(assetPaths.at(-1),"/experimental/genome");
 const meta=await (await request(`/api/experimental-v05/assemblies/${id}`)).json();assert.equal(meta.sources[0].evidence_class,"author_called_TTS");assert.equal(meta.files.length,8);
 const cfg=await (await request(`/api/experimental-v05/assemblies/${id}/config`)).json();assert.equal(cfg.assemblies[0].name,id);assert.equal(cfg.tracks.length,2);assert.equal(cfg.metadata.endpoint_count,663);
 assert.equal(cfg.assemblies[0].sequence.adapter.type,"BgzipFastaAdapter");assert.match(cfg.assemblies[0].sequence.adapter.gziLocation.uri,/reference.fa.gz.gzi/);
 assert.equal(cfg.plugins[0].name,"BTEDTrackPlugin");
 assert.equal(cfg.tracks[1].displays[0].renderer.color1,"jexl:btedStrandColor(feature)");
 assert.deepEqual(cfg.tracks[0].displays[0].filter,{genes:"only"});
 assert.equal(cfg.tracks[1].metadata.evidence_class,"author_called_TTS");assert.match(cfg.tracks[1].adapter.index.location.uri,/endpoints.gff3.gz.tbi/);
});
test("new assemblies use the established study metadata and package contract",async()=>{
 const r=await request(`/api/assemblies/${id}/page-metadata`);assert.equal(r.status,200);const data=await r.json();
 assert.equal(data.metadata_source,"d1");assert.equal(data.assembly.accession,id);assert.equal(data.record_count,663);assert.equal(data.study_count,1);
 assert.equal(data.sources[0].publication.paper_title,"Study title");assert.equal(data.sources[0].metadata.interpretation_note,"Author-reported sites");assert.equal(data.sources[0].evidence_class,"author_called_TTS");
 assert.equal(data.downloads.length,4);assert(data.downloads.every(file=>file.path&&file.url));
 const tsv=await request(`/api/assemblies/${id}/metadata.tsv`);assert.equal(tsv.status,200);assert.match(await tsv.text(),/author_called_TTS/);
 const config=await request(`/api/assemblies/${id}/jbrowse-config`);assert.equal(config.status,200);assert.equal((await config.json()).plugins[0].name,"BTEDTrackPlugin");
});
test("unregistered files, traversal, methods and malformed ranges fail before origin fetch",async()=>{
 assert.equal((await request("/api/experimental-v05/files?path=genomes/experimental-only/missing")).status,404);
 assert.equal((await request("/api/experimental-v05/files?path=genomes/experimental-only/../private")).status,400);
 assert.equal((await request("/api/experimental-v05/assemblies",{method:"POST"})).status,405);
 assert.equal((await request(`/experimental/${id}`,{method:"POST"})).status,405);
 const path=encodeURIComponent(prefix+"/reference/reference.fa.gz");
 assert.equal((await request("/api/experimental-v05/files?path="+path,{headers:{range:"bytes=1-2,4-5"}})).status,416);
});
test("scientific file proxy uses immutable revision and preserves range responses",async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async(url,options)=>{assert.match(String(url),new RegExp("/resolve/"+revision+"/v0.5.0/"));assert.equal(options.headers.range,"bytes=0-9");return new Response("0123456789",{status:206,headers:{"content-range":"bytes 0-9/100","content-length":"10"}})};
 try {
  const r=await request("/api/experimental-v05/files?path="+encodeURIComponent(prefix+"/reference/reference.fa.gz"),{headers:{range:"bytes=0-9"}});
  assert.equal(r.status,206);assert.equal(r.headers.get("x-bted-revision"),revision);assert.equal(await r.text(),"0123456789");
 } finally {globalThis.fetch=original;}
});
test("a newly registered D1 assembly needs no generated page or code allowlist",async()=>{
 const next="GCF_999999999.1";
 db.prepare("INSERT INTO bted_experimental_v05_assemblies SELECT ?,organism,endpoint_count,source_count,contigs_json,hf_revision FROM bted_experimental_v05_assemblies WHERE accession=?").run(next,id);
 db.prepare("INSERT INTO bted_experimental_v05_sources SELECT 'FUTURE',?,pmid,doi,evidence_class,assay,record_count,metadata_json FROM bted_experimental_v05_sources WHERE source_id='R03'").run(next);
 db.prepare(`INSERT INTO hf_directory_genomes(version,genome_id,accession_key,organism_key,organism,source,genome_type,annotation,endpoints,predictions,training,phylum,class,"order",family,genus,species,search_text) SELECT version,?,?,organism_key,organism,source,genome_type,annotation,endpoints,predictions,training,phylum,class,"order",family,genus,species,search_text FROM hf_directory_genomes WHERE genome_id=?`).run(next,next,id);
 db.prepare("INSERT INTO bted_taxonomy_records SELECT version,?,system,taxonomy_version,status,tax_id,scientific_name,matched_accession,match_method,domain,phylum,class,\"order\",family,genus,species,source_url,retrieved_at,evidence_json FROM bted_taxonomy_records WHERE genome_id=?").run(next,id);
 db.prepare("UPDATE bted_experimental_v05_assemblies SET hf_revision=? WHERE accession=?").run("b".repeat(40),next);
 const page=await request(`/experimental/${next}`);assert.equal(page.status,200);assert.equal(assetPaths.at(-1),"/experimental/genome");
 const data=await (await request(`/api/assemblies/${next}/page-metadata`)).json();assert.equal(data.assembly.accession,next);assert.equal(data.record_count,663);assert.equal(data.hf_revision,"b".repeat(40));
});
test("registered scientific revision changes are read from D1, not deployed code",async()=>{
 const file=prefix+"/reference/reference.fa.gz", nextRevision="c".repeat(40), original=globalThis.fetch;
 db.prepare("UPDATE bted_experimental_v05_files SET hf_revision=? WHERE logical_path=?").run(nextRevision,file);
 globalThis.fetch=async url=>{assert(String(url).includes("/resolve/"+nextRevision+"/"));return new Response("data")};
 try {const r=await request("/api/experimental-v05/files?path="+encodeURIComponent(file));assert.equal(r.status,200);assert.equal(r.headers.get("x-bted-revision"),nextRevision);}
 finally {globalThis.fetch=original;db.prepare("UPDATE bted_experimental_v05_files SET hf_revision=? WHERE logical_path=?").run(revision,file);}
});
test("v05 predictions use pinned files, complete references and independent evidence",async()=>{
 db.exec(readFileSync(new URL("../database/migrations/0014_experimental_prediction_bindings.sql",import.meta.url),"utf8"));
 const run="BATTER-TPE-20261104",predictionRevision="d".repeat(40);
 db.prepare("UPDATE bted_experimental_v05_assemblies SET prediction_count=3,prediction_run=?,prediction_revision=?,prediction_reference_sha256=?,prediction_contig_counts_json=? WHERE accession=?")
   .run(run,predictionRevision,"a".repeat(64),JSON.stringify({ref:2,plasmid:1}),id);
 db.prepare("UPDATE bted_experimental_v05_assemblies SET contigs_json=? WHERE accession=?").run(JSON.stringify({ref:2000000,plasmid:94287}),id);
 for (const name of ["prediction.bed","prediction.gff3.gz","prediction.gff3.gz.tbi"]) {
   db.prepare("INSERT INTO bted_experimental_v05_files VALUES(?,?,?,?,?,?,?)").run(`${prefix}/predictions/${run}/${name}`,id,null,name,100,"e".repeat(64),predictionRevision);
 }
 const cfg=await (await request(`/api/assemblies/${id}/jbrowse-config`)).json();
 const prediction=cfg.tracks.find(t=>t.trackId==="bted_experimental_prediction");
 assert(prediction);assert.equal(cfg.tracks.length,3);assert.equal(cfg.metadata.prediction_count,3);
 assert.deepEqual(prediction.metadata.btedContigCounts,{ref:2,plasmid:1});
 assert.match(prediction.adapter.gffGzLocation.uri,new RegExp(`/resolve/${predictionRevision}/`));
 assert.equal(prediction.metadata.evidence_class,"model_prediction");
 const data=await (await request(`/api/assemblies/${id}/page-metadata`)).json();
 assert.equal(data.predictions.count,3);assert.equal(data.predictions.reference_contigs,2);
 assert.equal(data.predictions.downloads.length,2);assert.equal(data.record_count,663);
 assert.equal(data.sources[0].evidence_class,"author_called_TTS");
 const index=`${prefix}/predictions/${run}/prediction.gff3.gz.tbi`;
 db.prepare("UPDATE bted_experimental_v05_files SET hf_revision=? WHERE logical_path=?").run(revision,index);
 const mismatch=await request(`/api/assemblies/${id}/jbrowse-config`);assert.equal(mismatch.status,503);
 db.prepare("UPDATE bted_experimental_v05_files SET hf_revision=? WHERE logical_path=?").run(predictionRevision,index);
});
test.after(()=>db.close());
