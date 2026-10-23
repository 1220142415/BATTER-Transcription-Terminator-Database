import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source=readFileSync(new URL('../site/assets/study-metadata.js',import.meta.url),'utf8');
const element={dataset:{assembly:'GCF_123.1'},querySelector:()=>({addEventListener(){}})};
const sandbox={document:{baseURI:'https://bted.test/experimental/GCF_123.1',querySelector:()=>element},fetch:()=>new Promise(()=>{}),URL};
runInNewContext(source.replace('  function sourceFacts(source)', '  globalThis.taxonomyMarkup = taxonomyMarkup;\n  function sourceFacts(source)'),sandbox);
const row=(system,version,status,phylum)=>({system,taxonomy_version:version,status,phylum,label:system==='ncbi'?'NCBI Taxonomy':'GTDB R207.0',source_url:'https://official.test',retrieved_at:'2026-10-22',evidence:{},species:''});

test('display names its default and keeps supplementary lineages distinct and escaped',()=>{
 const html=sandbox.taxonomyMarkup({default_system:'ncbi',default_version:'',records:[row('gtdb','R207.0','verified','GTDB phylum'),row('ncbi','','verified','NCBI <phylum>')]});
 assert.match(html,/<h3>NCBI Taxonomy<\/h3>/); assert.match(html,/Default classification/);
 assert.match(html,/NCBI &lt;phylum&gt;/);
 assert.match(html,/<details[^>]*><summary>GTDB R207.0 · supplementary classification/);
 assert(html.indexOf('data-taxonomy-system="ncbi"')<html.indexOf('data-taxonomy-system="gtdb"'));
 assert.match(html,/<dd>Not assigned<\/dd>/);
});

test('unresolved assemblies and absent exact GTDB matches remain explicit rather than falling back',()=>{
 const html=sandbox.taxonomyMarkup({default_system:'ncbi',default_version:'',records:[row('ncbi','','pending',''),row('gtdb','R207.0','unmatched','')]});
 assert.match(html,/Exact NCBI assembly version unresolved/);
 assert.match(html,/No exact assembly-version match in GTDB R207.0/);
 assert.doesNotMatch(html,/<dl class="taxonomy-lineage">/);
 assert.throws(()=>sandbox.taxonomyMarkup({default_system:'ncbi',default_version:'',records:[row('gtdb','R207.0','verified','P')]}),/Default classification unavailable/);
});
