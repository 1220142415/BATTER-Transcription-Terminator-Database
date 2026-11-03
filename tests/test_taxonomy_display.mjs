import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source=readFileSync(new URL('../site/assets/study-metadata.js',import.meta.url),'utf8');
const element={dataset:{assembly:'GCF_123.1'},querySelector:selector=>selector==='[data-browser-frame]'?null:({addEventListener(){}})};
const sandbox={document:{baseURI:'https://bted.test/experimental/GCF_123.1',querySelector:()=>element},fetch:()=>new Promise(()=>{}),URL};
runInNewContext(source.replace('  function sourceFacts(source)', '  Object.assign(globalThis, {taxonomyMarkup, sourceFacts, studyMarkup, rawDataMarkup, signalMarkup});\n  function sourceFacts(source)'),sandbox);
const row=(system,version,status,phylum)=>({system,taxonomy_version:version,status,phylum,label:system==='ncbi'?'NCBI Taxonomy':'GTDB R207.0',source_url:'https://official.test',retrieved_at:'2026-10-22',evidence:{},species:''});

test('display names its default and keeps supplementary lineages distinct and escaped',()=>{
 const html=sandbox.taxonomyMarkup({default_system:'ncbi',default_version:'',records:[row('gtdb','R207.0','verified','GTDB phylum'),row('ncbi','','verified','NCBI <phylum>')]});
 assert.match(html,/<h3>NCBI Taxonomy<\/h3>/); assert.match(html,/Default taxonomy/);
 assert.match(html,/NCBI &lt;phylum&gt;/);
 assert.match(html,/<details[^>]*><summary>GTDB R207.0 · supplementary taxonomy/);
 assert(html.indexOf('data-taxonomy-system="ncbi"')<html.indexOf('data-taxonomy-system="gtdb"'));
 assert.match(html,/<dd>Not assigned<\/dd>/);
});

test('unresolved assemblies and absent exact GTDB matches remain explicit rather than falling back',()=>{
 const html=sandbox.taxonomyMarkup({default_system:'ncbi',default_version:'',records:[row('ncbi','','pending',''),row('gtdb','R207.0','unmatched','')]});
 assert.match(html,/NCBI taxonomy unavailable for this assembly/);
 assert.match(html,/No exact match for this assembly in GTDB R207.0/);
 assert.doesNotMatch(html,/<dl class="taxonomy-lineage">/);
 assert.match(sandbox.taxonomyMarkup({default_system:'ncbi',default_version:'',records:[row('gtdb','R207.0','verified','P')]}),/Default taxonomy unavailable for this assembly/);
 assert.match(sandbox.taxonomyMarkup(null),/Default taxonomy unavailable for this assembly/);
});

test('study cards omit the internal evidence class and retain methods, conditions and source links',()=>{
 const study={source_id:'S1',publication_pmid:'123',release_status:'published_standardized',record_count:607,
  assay_family:'Rend-seq',evidence_class:'curated_record',signals:[],publication:{paper_title:'Study title',journal:'Cell',published_year:2018},
  metadata:{sample_strain:'K-12 MG1655',conditions:'37°C',replicate_label:'Three replicates',replicate_type:'biological',raw_data_accessions:'GSE95211'}};
 const html=sandbox.studyMarkup('123',[study],[study]);
 assert.doesNotMatch(html,/<dt>Evidence<\/dt>|curated_record|Curated 3′-end record/);
 for(const value of ['Rend-seq','K-12 MG1655','37°C','Three replicates (biological)','607','GSE95211','PMID 123'])assert(html.includes(value));
 assert.match(html,/https:\/\/www.ncbi.nlm.nih.gov\/geo\/query\/acc.cgi\?acc=GSE95211/);
});

test('study cards remain concise and omit internal evidence and curation notes',()=>{
 const study={source_id:'R10',publication_pmid:'42156950',release_status:'published_standardized',record_count:807,
  assay_family:'SEnd-seq',evidence_class:'author_called_endpoint',signals:[],
  publication:{paper_title:'RNA study',journal:'Nature Microbiology',published_year:2026},
  metadata:{coordinate_review_status:'unverified',interpretation_note:'Author 2026 internal TTS_A and TTS_B split into separate rows.',raw_data_accessions:'PRJNA1250544'}};
 const html=sandbox.studyMarkup('42156950',[study],[study]);
 for(const useful of ['3′-end assay','SEnd-seq','807','PRJNA1250544','PMID 42156950']) assert(html.includes(useful),useful);
 for(const internal of ['Evidence scope','termination mechanism is not inferred','A 3′ end within an annotated gene',
  'Original-source coordinate convention','Author 2026 internal','author_called_endpoint']) assert(!html.includes(internal),internal);
});
test('original modified Term-seq assay stays visible on publication detail',()=>{
 const study={source_id:'BATTER_S1_021',publication_pmid:'37402717',release_status:'published_standardized',record_count:132,
  assay_family:'3′ RNA-seq (modified from Term-seq)',signals:[],
  publication:{paper_title:'Published study',journal:'Nature Communications',published_year:2023},
  metadata:{sample_strain:'B31 A3',raw_data_accessions:'GSE222087'}};
 const html=sandbox.studyMarkup('37402717',[study],[study]);
 assert(html.includes('3′ RNA-seq (modified from Term-seq)'));
 for(const useful of ['B31 A3','GSE222087','PMID 37402717']) assert(html.includes(useful),useful);
 assert(!html.includes('Evidence scope'));
});
test('GEM supplementary classification names R89 instead of a historical-status label',()=>{
 const gem={...row('gem_original','','retained','P'),label:'GTDB R89 (GEM)'};
 const html=sandbox.taxonomyMarkup({default_system:'ncbi',default_version:'',records:[row('ncbi','','verified','P'),gem]});
 assert(html.includes('<summary>GTDB R89 (GEM) · supplementary taxonomy'));
 assert.doesNotMatch(html,/historical|release not established/);
});

test('raw accessions are grouped by their verified role without dropping links',()=>{
 const html=sandbox.rawDataMarkup({raw_data_accessions:'GSE222084;GSE222087;GSE222088',raw_data_links:[
  {accession:'GSE222087',url:'https://geo.test/GSE222087',data_role:'primary_3prime'},
  {accession:'GSE222084',url:'https://geo.test/GSE222084',data_role:'supporting'},
  {accession:'GSE222088',url:'https://geo.test/GSE222088',data_role:'parent_series'}]});
 assert.match(html,/3′-end sequencing data/);
 assert.match(html,/Related sequencing data/);
 assert.match(html,/Study series/);
 for(const id of ['GSE222084','GSE222087','GSE222088']) assert(html.includes(id));
});
