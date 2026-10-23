"""Check genome search, cascading taxonomy, pagination and shared URLs."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const fs=require('fs'), vm=require('vm');
function control(value='') {return {value,options:[{value:''}],listeners:{},children:[],dataset:{},textContent:'',
  parentElement:{classList:{toggle(){}}},
  querySelector(){return this.children.find(node=>Object.hasOwn(node.dataset,'gemOtu'))??null;},
  addEventListener(type,fn){this.listeners[type]=fn;},fire(type){this.listeners[type]?.({preventDefault(){}});},
  append(...nodes){this.children.push(...nodes);this.options.push(...nodes);},replaceChildren(...nodes){this.children=[...nodes];this.options=[...nodes];}};}
const source=(study,assay,search,published='yes')=>({dataset:{study,assay,search,published}});
function row(id,name,endpoints,phylum,cl,order,family,genus,sources){return {dataset:{genomeSearch:`${id} ${name}`.toLowerCase(),sortAccession:id,sortOrganism:name,sortEndpoints:String(endpoints),taxonomyPhylum:phylum,taxonomyClass:cl,taxonomyOrder:order,taxonomyFamily:family,taxonomyGenus:genus},querySelectorAll(){return sources;},cells:{},querySelector(key){return this.cells[key]??=control();}};}
const rows=[row('GCF_A','Alpha',100,'P1','C1','O1','F1','Alpha',[source('A','Term-seq','study a')]),
row('GCF_B','Beta',300,'P1','C2','O2','F2','Beta',[source('A','Term-seq','study a'),source('AUDIT','Review only','audit','no')]),
row('GCF_C','Gamma',200,'P2','C3','O3','F3','Gamma',[source('B','Rend-seq','study b')])];
rows.forEach(row=>Object.assign(row.dataset,{genomeSource:'NCBI RefSeq',genomeType:'unknown',genomeAnnotation:'Available'}));
const search=control(),clear=control(),form=control(),count=control(),empty=control();
const taxonomy=['phylum','class','order','family','genus'].map(rank=>{const select=control();select.dataset.taxonomyRank=rank;return select;});
const tbody={children:[],querySelectorAll(){return rows;},append(node){this.children=this.children.filter(n=>n!==node);this.children.push(node);},replaceChildren(...nodes){this.children=[...nodes];}};
const buttons=['accession','organism','size','endpoints','predictions','training'].map(value=>({dataset:{sort:value},listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},click(){this.listeners.click();},closest(){return {setAttribute(){}};}}));
const elements={'[data-genome-search-form]':form,'[data-genome-search]':search,'[data-genome-results]':tbody,'[data-visible-count]':count,'[data-result-range]':control(),'[data-empty]':empty,'[data-clear-filters]':clear};
global.document={createElement:()=>control(),querySelector:key=>elements[key]??null,querySelectorAll:key=>key==='[data-sort]'?buttons:key==='[data-taxonomy-rank]'?taxonomy:[]};
let href='https://bted.example/genomes.html?taxon=phylum:P1&study=unused&assay=unused';const listeners={};
global.window={location:{get href(){return href;},get search(){return new URL(href).search;}},history:{replaceState(_s,_t,url){href=String(url);}},addEventListener(type,fn){listeners[type]=fn;}};
const visible=()=>rows.filter(row=>!row.hidden).map(row=>row.dataset.sortAccession);
const choose=(rank,value)=>{const select=taxonomy.find(s=>s.dataset.taxonomyRank===rank);select.value=value;select.fire('change');};
const run=()=>vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
"""

class GenomeFiltersTests(unittest.TestCase):
    def test_d1_linked_menus_keep_labels_restore_urls_and_clear_taxonomy_children(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html';
form.dataset.genomePages='api/genome-directory?v=aaaaaaaaaaaaaaaaaaaaaaaa';
const dataset=control(),sourceFilter=control(),typeFilter=control(),annotationFilter=control();
const options=(select,pairs)=>{select.options=pairs.map(([value,textContent])=>({value,textContent}));};
options(dataset,[['','All data'],['experimental','Experimental'],['prediction','Prediction'],['augmentation','Augmentation / Rfam']]);
options(sourceFilter,[['','All sources'],['IMG','IMG'],['NCBI RefSeq','NCBI RefSeq']]);
options(typeFilter,[['','All types'],['MAG','MAG · Metagenome-assembled'],['isolate','Isolate']]);
options(annotationFilter,[['','All statuses'],['Available','Available'],['Missing','Missing']]);
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-source-filter]':sourceFilter,'[data-genome-type-filter]':typeFilter,'[data-genome-annotation-filter]':annotationFilter,'.genome-result-count':control(),'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
const requests=[];
global.fetch=async url=>{
 requests.push(url);const q=new URL(url).searchParams,source=q.get('source');
 const img=source==='IMG',none=q.has('q');
 const facets={source:['IMG','NCBI RefSeq'],genome_type:img?['MAG']:source?['isolate']:['MAG','isolate'],annotation:img?['Missing']:source?['Available']:['Available','Missing'],dataset:img?['prediction']:source?['experimental','prediction']:['experimental','prediction'],phylum:img?['P9']:source?['P1']:['P1','P9']};
 if(q.get('phylum'))facets.class=img?['C9']:['C1'];
 if(q.get('class'))facets.order=img?['O9']:['O1'];
 if(none)for(const key of Object.keys(facets))facets[key]=[];
 return {ok:true,json:async()=>({page:1,total:none?0:img?5:source?2:7,rows:[],facets})};
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const values=select=>select.options.map(option=>option.value);
const select=async(control,value)=>{control.value=value;control.fire('change');await tick();};
run();
(async()=>{
 await tick();await select(sourceFilter,'IMG');
 const narrowed={types:values(typeFilter),annotations:values(annotationFilter),datasets:values(dataset),phyla:values(taxonomy[0]),labels:typeFilter.options.map(o=>o.textContent)};
 await select(taxonomy[0],'P9');await select(taxonomy[1],'C9');
 const parentUrl=href;
 await select(taxonomy[0],'');
 const parentCleared={classValue:taxonomy[1].value,classDisabled:taxonomy[1].disabled,orderValue:taxonomy[2].value,orderDisabled:taxonomy[2].disabled,url:href};
 href='https://bted.example/genomes.html?source=NCBI%20RefSeq&genome_type=isolate&annotation=Available';listeners.popstate();await tick();
 const restored={source:sourceFilter.value,type:typeFilter.value,annotation:annotationFilter.value,count:count.textContent,options:values(typeFilter)};
 search.value='no matches';form.fire('submit');await tick();
 const zero={count:count.textContent,source:sourceFilter.value,type:typeFilter.value,annotation:annotationFilter.value,href};
 clear.fire('click');await tick();
 const cleared={source:sourceFilter.value,type:typeFilter.value,annotation:annotationFilter.value,types:values(typeFilter),datasets:values(dataset),count:count.textContent,href};
 process.stdout.write(JSON.stringify({narrowed,parentUrl,parentCleared,restored,zero,cleared,requests}));
})();
''')
        self.assertEqual(data['narrowed'], {'types': ['', 'MAG'], 'annotations': ['', 'Missing'],
                                           'datasets': ['', 'prediction'], 'phyla': ['', 'P9'],
                                           'labels': ['All types', 'MAG · Metagenome-assembled']})
        self.assertIn('class=C9', data['parentUrl'])
        self.assertEqual(data['parentCleared']['classValue'], '')
        self.assertTrue(data['parentCleared']['classDisabled'])
        self.assertTrue(data['parentCleared']['orderDisabled'])
        self.assertNotIn('class=', data['parentCleared']['url'])
        self.assertEqual(data['restored'], {'source': 'NCBI RefSeq', 'type': 'isolate', 'annotation': 'Available',
                                           'count': '2', 'options': ['', 'isolate']})
        self.assertEqual(data['zero']['count'], '0')
        self.assertEqual(data['zero']['source'], 'NCBI RefSeq')
        self.assertEqual(data['zero']['type'], 'isolate')
        self.assertEqual(data['zero']['annotation'], 'Available')
        self.assertIn('q=no+matches', data['zero']['href'])
        self.assertEqual(data['cleared'], {'source': '', 'type': '', 'annotation': '', 'types': ['', 'MAG', 'isolate'],
                                          'datasets': ['', 'experimental', 'prediction'], 'count': '7',
                                          'href': 'https://bted.example/genomes.html'})

    def test_d1_pages_fetch_only_current_page_and_reuse_visited_results(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html';
form.dataset.genomePages='api/genome-directory?v=aaaaaaaaaaaaaaaaaaaaaaaa';
const dataset=control();dataset.options=['','prediction'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'.genome-result-count':control(),'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
let requests=[];
global.fetch=async url=>{requests.push(url);const p=Number(new URL(url).searchParams.get('page'));return {ok:true,json:async()=>({page:p,page_size:25,total:60,sources:['IMG'],facets:{phylum:['P1']},rows:Array.from({length:p===3?10:25},(_,i)=>({batter:[`GCF_${(p-1)*25+i}`,'000','','Species','MAG',0,0,0,0,'matched',1,'p__P1','IMG'],dataset:{sortEndpoints:'0',sortPredictions:'1',sortTraining:'0',taxonomyPhylum:'P1'}}))})};};
run();setImmediate(()=>{
  const initial={requests:requests.length,count:count.textContent,nodes:tbody.children.length,range:elements['[data-result-range]'].textContent};
  elements['[data-genome-next]'].fire('click');setImmediate(()=>{
    const second={requests:requests.length,range:elements['[data-result-range]'].textContent,href};
    elements['[data-genome-prev]'].fire('click');setImmediate(()=>{
      const returned={requests:requests.length,range:elements['[data-result-range]'].textContent};
      search.value='xx';form.fire('submit');setImmediate(()=>process.stdout.write(JSON.stringify({initial,second,returned,urls:requests,shortQueryRequests:requests.length,status:elements['[data-genome-load-status]'].textContent})));
    });
  });
});
''')
        self.assertEqual(data['initial'], {'requests': 1, 'count': '60', 'nodes': 25, 'range': 'Showing 1–25'})
        self.assertEqual(data['second']['requests'], 2)
        self.assertIn('page=2', data['second']['href'])
        self.assertEqual(data['second']['range'], 'Showing 26–50')
        self.assertEqual(data['returned'], {'requests': 2, 'range': 'Showing 1–25'})
        self.assertTrue(all('/api/genome-directory?' in url for url in data['urls']))
        self.assertEqual(data['shortQueryRequests'], 2)
        self.assertEqual(data['status'], 'Enter at least 3 characters.')

    def test_d1_pages_ignore_stale_responses_and_allow_retry_without_full_download(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html';form.dataset.genomePages='api/genome-directory?v=aaaaaaaaaaaaaaaaaaaaaaaa';
const dataset=control();dataset.options=[{value:''}];
Object.assign(elements,{'[data-genome-dataset]':dataset,'.genome-result-count':control(),'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
const pending=[];global.fetch=url=>new Promise(resolve=>pending.push({url,resolve}));
const payload=(total)=>({ok:true,json:async()=>({rows:[],total,page:1,facets:{phylum:[]},sources:[]})});
run();search.value='latest';form.fire('submit');pending[1].resolve(payload(2));
setImmediate(()=>{pending[0].resolve(payload(99));setImmediate(()=>{
 const fresh=count.textContent;search.value='offline';form.fire('submit');pending[2].resolve({ok:false,status:503});
 setImmediate(()=>{const failed={status:elements['[data-genome-load-status]'].textContent,hidden:tbody.hidden,retry:elements['[data-genome-retry]'].hidden};
 elements['[data-genome-retry]'].fire('click');pending[3].resolve(payload(3));setImmediate(()=>process.stdout.write(JSON.stringify({fresh,failed,retried:count.textContent,requests:pending.length})));
 });
});});
''')
        self.assertEqual(data['fresh'], '2')
        self.assertEqual(data['failed'], {'status': 'Catalog unavailable.', 'hidden': True, 'retry': False})
        self.assertEqual(data['retried'], '3')
        self.assertEqual(data['requests'], 4)

    def test_pagination_reuses_sort_and_pinned_catalogue_without_more_requests(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html';
form.dataset.genomeCatalogue='api/batter-catalogue?revision=r&annotation=a&v=1';
const dataset=control();dataset.options=['','prediction'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
let requests=[],comparisons=0;const Collator=Intl.Collator;
Intl.Collator=function(...args){const c=new Collator(...args);return {compare(a,b){comparisons++;return c.compare(a,b);}};};
global.fetch=async url=>{requests.push(url);return {ok:true,json:async()=>({genomes:Array.from({length:30},(_,i)=>
[`GCF_${i}`,'000',`OTU-${i}`,'Predicted','MAG',0,0,0,0,'unavailable',i,'p__P1','IMG'])})};};
run();setImmediate(()=>{
  comparisons=0;elements['[data-genome-next]'].fire('click');const pagination=comparisons;
  search.value='Ｐｒｅｄｉｃｔｅｄ';search.fire('input');const searched=count.textContent;
  const filtering=comparisons;buttons.find(b=>b.dataset.sort==='accession').click();const sorting=comparisons;
  Intl.Collator=Collator;process.stdout.write(JSON.stringify({requests,pagination,filtering,sorting,searched}));
});
''')
        self.assertEqual(data['requests'], ['api/batter-catalogue?revision=r&annotation=a&v=1'])
        self.assertEqual(data['pagination'], 0)
        self.assertEqual(data['filtering'], 0)
        self.assertGreater(data['sorting'], 0)
        self.assertEqual(data['searched'], '30')

    def test_verified_partial_annotations_are_available_without_a_third_status(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html?annotation=Available';
rows.length=0;
const dataset=control(),annotationFilter=control();
dataset.options=['','experimental','prediction','augmentation'].map(value=>({value}));
annotationFilter.options=['','Available','Missing'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-annotation-filter]':annotationFilter,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
global.fetch=async()=>({ok:true,json:async()=>({revision:'r',genomes:[['RECOVERED','000','OTU-1','Example','MAG',0,0,0,0,'mismatch',1,'p__P1','GEM']],
annotation_recovery:{reference_revision:'r',genomes:{RECOVERED:{coverage:'partial',matched_reference_contigs:1,total_reference_contigs:3}}}})});
run();setImmediate(()=>{
 const badge=tbody.children[0].children[6].children[0];
 const result={count:count.textContent,label:badge.textContent,title:badge.title};
 annotationFilter.value='Missing';annotationFilter.fire('change');result.missing=count.textContent;
 process.stdout.write(JSON.stringify(result));
});
''')
        self.assertEqual(data['count'], '1')
        self.assertEqual(data['label'], 'Available')
        self.assertIn('1/3', data['title'])
        self.assertIn('partial', data['title'])
        self.assertEqual(data['missing'], '0')

    def run_js(self, script):
        result = subprocess.run(['node', '-e', HARNESS + script, str(ROOT / 'site/assets/genome-index.js')],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_cascading_taxonomy_search_sort_reset_and_shared_urls(self):
        data = self.run_js(r'''
run();
const initial={visible:visible(),classes:taxonomy[1].options.map(o=>o.value),disabled:taxonomy.map(s=>s.disabled)};
choose('class','C2');const narrowed={visible:visible(),orders:taxonomy[2].options.map(o=>o.value),disabled:taxonomy.map(s=>s.disabled),href};
choose('order','O2');buttons.find(b=>b.dataset.sort==='endpoints').click();buttons.find(b=>b.dataset.sort==='endpoints').click();
const shared=href;listeners.popstate();const restored={visible:visible(),order:taxonomy[2].value,direction:buttons.find(b=>b.dataset.sortDirection)?.dataset.sortDirection==='asc'?'Ascending':'Descending'};
choose('phylum','P2');const switched={visible:visible(),children:taxonomy.slice(1).map(s=>s.value)};
clear.fire('click');const cleared={visible:visible(),disabled:taxonomy.map(s=>s.disabled),href};
choose('genus','Beta');const blockedGenus={visible:visible(),selected:taxonomy[4].value};clear.fire('click');
buttons.find(b=>b.dataset.sort==='endpoints').click();buttons.find(b=>b.dataset.sort==='endpoints').click();const sorted=tbody.children.map(r=>r.dataset.sortAccession);
search.value='study Alpha';search.fire('input');const multiword=visible();
search.value='no match';search.fire('input');const noMatch={count:count.textContent,empty:empty.hidden};
process.stdout.write(JSON.stringify({initial,narrowed,shared,restored,switched,cleared,blockedGenus,sorted,multiword,noMatch}));
''')
        self.assertEqual(data['initial'], {'visible':['GCF_A','GCF_B'],'classes':['','C1','C2'],'disabled':[False,False,True,True,True]})
        self.assertEqual(data['narrowed']['visible'], ['GCF_B'])
        self.assertEqual(data['narrowed']['orders'], ['', 'O2'])
        self.assertEqual(data['narrowed']['disabled'], [False,False,False,True,True])
        self.assertNotIn('study=', data['narrowed']['href'])
        self.assertNotIn('assay=', data['narrowed']['href'])
        self.assertIn('order=O2', data['shared'])
        self.assertNotIn('direction=', data['shared'])
        self.assertEqual(data['restored'], {'visible':['GCF_B'],'order':'O2','direction':'Descending'})
        self.assertEqual(data['switched'], {'visible':['GCF_C'],'children':['','','','']})
        self.assertEqual(len(data['cleared']['visible']), 3)
        self.assertEqual(data['cleared']['disabled'], [False,True,True,True,True])
        self.assertNotIn('phylum=', data['cleared']['href'])
        self.assertEqual(data['blockedGenus'], {'visible':['GCF_A','GCF_B','GCF_C'],'selected':''})
        self.assertEqual(data['sorted'], ['GCF_B','GCF_C','GCF_A'])
        self.assertEqual(data['multiword'], ['GCF_A'])
        self.assertEqual(data['noMatch'], {'count':'0','empty':False})

    def test_species_filter_shared_url_and_parent_reset(self):
        data = self.run_js(r'''
const species=control();species.dataset.taxonomyRank='species';taxonomy.push(species);
rows[0].dataset.taxonomySpecies='Alpha species';
href='https://bted.example/genomes.html?phylum=P1&class=C1&order=O1&family=F1&genus=Alpha&species=Alpha+species';
run();const restored={visible:visible(),value:species.value,disabled:species.disabled};
choose('phylum','P2');const switched={value:species.value,href};
clear.fire('click');listeners.popstate();const cleared={visible:visible(),value:species.value,href};
process.stdout.write(JSON.stringify({restored,switched,cleared}));
''')
        self.assertEqual(data['restored'], {'visible': ['GCF_A'], 'value': 'Alpha species', 'disabled': False})
        self.assertEqual(data['switched']['value'], '')
        self.assertNotIn('species=', data['switched']['href'])
        self.assertEqual(len(data['cleared']['visible']), 3)
        self.assertEqual(data['cleared']['value'], '')
        self.assertNotIn('species=', data['cleared']['href'])

    def test_experimental_first_default_preserves_manual_sort_and_reset(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html';
const dataset=control();dataset.options=['','experimental','prediction','augmentation'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
global.fetch=async()=>({ok:true,json:async()=>({genomes:Array.from({length:30},(_,i)=>
  [String(i).padStart(3,'0'),'000',`OTU-${i}`,'Predicted','MAG',0,0,0,0,'unavailable',1000,'p__P1','IMG'])})});
const ids=()=>tbody.children.map(r=>r.dataset.sortAccession||r.children[0].children[0].children[0].textContent);
run();setImmediate(()=>{
  const initial={ids:ids().slice(0,4),count:count.textContent,range:elements['[data-result-range]'].textContent,dataset:dataset.value,sort:buttons.find(b=>b.dataset.sortDirection)?.dataset.sort,direction:buttons.find(b=>b.dataset.sortDirection)?.dataset.sortDirection==='asc'?'Ascending':'Descending'};
  buttons.find(b=>b.dataset.sort==='accession').click();const manual=ids().slice(0,3);listeners.popstate();const restored=ids().slice(0,3);
  clear.fire('click');const reset=ids().slice(0,3);
  choose('phylum','P1');choose('class','C1');choose('order','O1');listeners.popstate();const filtered=ids();
  href='https://bted.example/genomes.html?sort=accession';listeners.popstate();const legacy=ids().slice(0,3);
  href='https://bted.example/genomes.html?sort=endpoints&direction=asc';listeners.popstate();const ascending=ids().slice(0,3);
  process.stdout.write(JSON.stringify({initial,manual,restored,reset,filtered,legacy,ascending}));
});
''')
        self.assertEqual(data['initial'], {'ids':['GCF_B','GCF_C','GCF_A','000'], 'count':'33',
                         'range':'Showing 1–25', 'dataset':'', 'sort':'endpoints', 'direction':'Descending'})
        self.assertEqual(data['reset'], ['GCF_B','GCF_C','GCF_A'])
        self.assertEqual(data['filtered'], ['GCF_A'])
        for state in ('manual', 'restored', 'legacy', 'ascending'):
            self.assertEqual(data[state], ['000','001','002'])

    def test_unified_catalogue_deduplicates_counts_and_retries(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html?q=GCF_B';
const dataset=control();dataset.options=['','experimental','prediction','augmentation'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
let catalogueFetches=0;global.fetch=async()=>{catalogueFetches++;return {ok:true,json:async()=>({genomes:[
['GCF_B','000','OTU-1','Beta','isolate',5,5,1,1,'matched',12,'d__Bacteria;p__P1;c__C2;o__O2;f__F2;g__Beta','NCBI-RefSeq'],
['GCF_Z','000','OTU-2','Zeta','MAG',9,9,0,0,'unavailable',20,'d__Bacteria;p__P3;c__C4;o__O4;f__F4;g__Zeta','IMG'],
['GCF_W','000','OTU-3','Empty','MAG',0,0,0,0,'mismatch',0,''],
],reference_sizes:{GCF_B:[10000,2],GCF_Z:[20000,1]}})};};run();
setImmediate(()=>{
  const states=[];for(const value of ['experimental','prediction','augmentation','']){dataset.value=value;dataset.fire('change');states.push({count:count.textContent,nodes:tbody.children.length,duplicate:tbody.children.filter(r=>r===rows[1]).length});}
  const mixed={otu:rows[1].cells['[data-label="Genome ID"]'].children[0].textContent,predictions:rows[1].cells['[data-prediction-count]'].textContent,training:rows[1].cells['[data-augmentation-count]'].textContent};
  search.value='';search.fire('input');choose('phylum','P3');choose('class','C4');choose('order','O4');choose('family','F4');choose('genus','Zeta');
  const cells=tbody.children[0].children;
  const synthetic={count:count.textContent,nodes:tbody.children.length,columns:cells.map(c=>c.dataset.label),assembly:cells[0].children[0].children[0].textContent,href:cells[0].children[0].href,otu:cells[0].children[1].textContent,source:cells[1].textContent,size:cells[4].children.map(c=>c.textContent),counts:cells[5].children[0].children.map(c=>c.children[0].textContent),annotation:cells[6].children[0].textContent};
  clear.fire('click');search.value='GCF_W';search.fire('input');const noFeatures=count.textContent;const mismatchAnnotation=tbody.children[0].children[6].children[0].textContent;
  const ids=()=>tbody.children.map(r=>r.dataset.sortAccession||r.children[0].children[0].children[0].textContent);
  clear.fire('click');buttons.find(b=>b.dataset.sort==='predictions').click();buttons.find(b=>b.dataset.sort==='predictions').click();const predictionOrder=ids();
  buttons.find(b=>b.dataset.sort==='training').click();buttons.find(b=>b.dataset.sort==='training').click();const trainingOrder=ids();
  buttons.find(b=>b.dataset.sort==='size').click();const sizeAscending=ids();buttons.find(b=>b.dataset.sort==='size').click();const sizeDescending=ids();
  const fetchesAfterFiltering=catalogueFetches;elements['[data-genome-retry]'].fire('click');
  setImmediate(()=>process.stdout.write(JSON.stringify({total:count.textContent,range:elements['[data-result-range]'].textContent,states,mixed,synthetic,noFeatures,mismatchAnnotation,predictionOrder,trainingOrder,sizeAscending,sizeDescending,fetchesAfterFiltering,catalogueFetches,retriedTraining:rows[1].dataset.sortTraining,retriedOtuLabels:rows[1].cells['[data-label="Genome ID"]'].children.length,status:elements['[data-genome-load-status]'].textContent})));
});
''')
        self.assertEqual(data['total'], '5')
        self.assertEqual(data['range'], 'Showing 1–5')
        self.assertTrue(all(s == {'count':'1','nodes':1,'duplicate':1} for s in data['states']))
        self.assertEqual(data['mixed'], {'otu':'GEM OTU: OTU-1','predictions':'12','training':'6'})
        self.assertEqual(data['synthetic'], {'count':'1','nodes':1,'columns':['Genome ID','Genome source','Organism','Taxonomy','Assembly size','Transcript 3′-end data','Annotation'],'assembly':'GCF_Z','href':'genomes/GCF_Z','otu':'GEM OTU: OTU-2','source':'IMG','size':['20,000 bp','1 contig'],'counts':['20','9'],'annotation':'Missing'})
        self.assertEqual(data['noFeatures'], '1')
        self.assertEqual(data['mismatchAnnotation'], 'Missing')
        self.assertEqual(data['fetchesAfterFiltering'], 1)
        self.assertEqual(data['catalogueFetches'], 2)
        self.assertEqual(data['predictionOrder'], ['GCF_Z','GCF_B','GCF_A','GCF_C','GCF_W'])
        self.assertEqual(data['trainingOrder'], data['predictionOrder'])
        self.assertEqual(data['sizeAscending'], ['GCF_B','GCF_Z','GCF_A','GCF_C','GCF_W'])
        self.assertEqual(data['sizeDescending'], ['GCF_Z','GCF_B','GCF_A','GCF_C','GCF_W'])
        self.assertEqual(data['retriedTraining'], '6')
        self.assertEqual(data['retriedOtuLabels'], 1)
        self.assertEqual('', data['status'])

    def test_waits_for_full_catalogue_and_recovers_when_fetch_fails(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html';
const dataset=control();dataset.options=[{value:''}];
const resultCount=control();resultCount.hidden=true;tbody.hidden=true;
Object.assign(elements,{'[data-genome-dataset]':dataset,'.genome-result-count':resultCount,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
let rejectFetch;global.fetch=()=>new Promise((_resolve,reject)=>{rejectFetch=reject;});run();
search.fire('input');
const loading={nodes:tbody.children.length,inert:form.inert,hidden:tbody.hidden,countHidden:resultCount.hidden,count:count.textContent};
rejectFetch(new Error('offline'));
setImmediate(()=>process.stdout.write(JSON.stringify({loading,recovered:{nodes:tbody.children.length,inert:form.inert,hidden:tbody.hidden,countHidden:resultCount.hidden,count:count.textContent,retryHidden:elements['[data-genome-retry]'].hidden,status:elements['[data-genome-load-status]'].textContent}})));
''')
        self.assertEqual(data['loading'], {'nodes':0,'inert':True,'hidden':True,'countHidden':True,'count':''})
        self.assertEqual(data['recovered']['nodes'], 3)
        self.assertEqual(data['recovered']['count'], '3')
        self.assertFalse(data['recovered']['inert'])
        self.assertFalse(data['recovered']['hidden'])
        self.assertFalse(data['recovered']['countHidden'])
        self.assertFalse(data['recovered']['retryHidden'])
        self.assertIn('Experimental genomes shown', data['recovered']['status'])

    def test_reference_filters_combine_restore_urls_and_preserve_unknowns(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html?source=IMG&genome_type=MAG&annotation=Available';
const dataset=control();dataset.options=['','experimental','prediction','augmentation'].map(value=>({value}));
const sourceFilter=control(),typeFilter=control(),annotationFilter=control();
typeFilter.options=['','isolate','MAG','SAG','unknown'].map(value=>({value}));
annotationFilter.options=['','Available','Missing'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-source-filter]':sourceFilter,'[data-genome-type-filter]':typeFilter,'[data-genome-annotation-filter]':annotationFilter,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
let fetches=0;global.fetch=async()=>{fetches++;return {ok:true,json:async()=>({genomes:[
...Array.from({length:30},(_,i)=>[`IMG_${i}`,'000',`OTU-${i}`,`Species ${i}`,'MAG',1,1,0,0,'matched',1,'p__P9;c__C9','IMG']),
['GCF_B','000','OTU-B','Beta','isolate',1,1,0,0,'matched',1,'p__P1;c__C2','NCBI-RefSeq'],
['IMG_S','000','OTU-S','Single cell','SAG',0,0,0,0,'contig_mismatch',1,'p__P9;c__C9','IMG'],
['NCBI_M','000','OTU-M','MAG','MAG',0,0,0,0,'unavailable',1,'p__P9;c__C9','NCBI-MAG'],
['NCBI_S','000','OTU-N','SAG','SAG',0,0,0,0,'no_ncbi_accession',1,'p__P9;c__C9','NCBI-SAG'],
]})};};run();
setImmediate(()=>{
  const state=()=>({count:count.textContent,range:elements['[data-result-range]'].textContent});
  const set=(select,value)=>{select.value=value;select.fire('change');};
  const initial=state(),sources=sourceFilter.options.map(o=>o.value);
  elements['[data-genome-next]'].fire('click');const paged=state();
  set(annotationFilter,'Available');const resetPage=state();
  choose('phylum','P9');choose('class','C9');set(search,'Species 29');search.fire('input');const searched=count.textContent;
  clear.fire('click');set(sourceFilter,'IMG');set(typeFilter,'SAG');set(annotationFilter,'Missing');const incompatible=count.textContent;
  clear.fire('click');set(sourceFilter,'NCBI GenBank');const genbank=count.textContent;
  set(typeFilter,'SAG');set(annotationFilter,'Missing');const unrecorded=count.textContent,shared=href;
  clear.fire('click');href=shared;listeners.popstate();const restored={count:count.textContent,source:sourceFilter.value,type:typeFilter.value,annotation:annotationFilter.value};
  const legacyAnnotations=['Incompatible','Unavailable','Not cataloged'].map(value=>{href='https://bted.example/genomes.html?source=IMG&genome_type=SAG&annotation='+encodeURIComponent(value);listeners.popstate();return {value:annotationFilter.value,count:count.textContent};});
  clear.fire('click');set(dataset,'experimental');
  set(sourceFilter,'IMG');const none={count:count.textContent,empty:empty.hidden};
  clear.fire('click');set(typeFilter,'unknown');const unknown=count.textContent;
  clear.fire('click');const cleared={count:count.textContent,href,values:[sourceFilter.value,typeFilter.value,annotationFilter.value,dataset.value]};
  href='https://bted.example/genomes.html?source=invalid&genome_type=invalid&annotation=invalid&dataset=experimental_prediction';listeners.popstate();const invalid={count:count.textContent,values:[sourceFilter.value,typeFilter.value,annotationFilter.value,dataset.value]};
  process.stdout.write(JSON.stringify({initial,sources,paged,resetPage,searched,incompatible,genbank,unrecorded,shared,restored,legacyAnnotations,none,unknown,cleared,invalid,fetches}));
});
''')
        self.assertEqual(data['initial'], {'count': '30', 'range': 'Showing 1–25'})
        self.assertEqual(data['sources'], ['', 'IMG', 'NCBI GenBank', 'NCBI RefSeq'])
        self.assertEqual(data['paged'], {'count': '30', 'range': 'Showing 26–30'})
        self.assertEqual(data['resetPage'], data['initial'])
        self.assertEqual(data['searched'], '1')
        self.assertEqual(data['incompatible'], '1')
        self.assertEqual(data['genbank'], '2')
        self.assertEqual(data['unrecorded'], '1')
        self.assertIn('genome_type=SAG', data['shared'])
        self.assertEqual(data['restored'], {'count': '1', 'source': 'NCBI GenBank', 'type': 'SAG', 'annotation': 'Missing'})
        self.assertEqual(data['legacyAnnotations'], [{'value': 'Missing', 'count': '1'}] * 3)
        self.assertEqual(data['none'], {'count': '0', 'empty': False})
        self.assertEqual(data['unknown'], '2')
        self.assertEqual(data['cleared'], {'count': '36', 'href': 'https://bted.example/genomes.html', 'values': ['', '', '', '']})
        self.assertEqual(data['invalid'], {'count': '36', 'values': ['', '', '', '']})
        self.assertEqual(data['fetches'], 1)

    def test_result_totals_and_ranges_follow_filters_and_pagination(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html';
const dataset=control();dataset.options=['','experimental','prediction','augmentation'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control()});
global.fetch=async()=>({ok:true,json:async()=>({genomes:Array.from({length:50},(_,i)=>[`GCF_X${i}`, '000', `OTU-${i}`, `Species ${i}`, 'MAG', i%2,0,0,0,'unavailable',1,'p__P9;c__C9;o__O9;f__F9;g__G9'])})});run();
setImmediate(()=>{
  const state=()=>({total:count.textContent,range:elements['[data-result-range]'].textContent});
  const all=state();elements['[data-genome-next]'].fire('click');const next=state();
  dataset.value='experimental';dataset.fire('change');const experimental=state();
  dataset.value='augmentation';dataset.fire('change');const augmentation=state();
  clear.fire('click');choose('phylum','P9');choose('class','C9');const taxonomyResult=state();
  search.value='Species 49';search.fire('input');const searchResult=state();
  search.value='no such genome';search.fire('input');const noMatches=state();
  process.stdout.write(JSON.stringify({all,next,experimental,augmentation,taxonomyResult,searchResult,noMatches}));
});
''')
        self.assertEqual(data['all'], {'total':'53','range':'Showing 1–25'})
        self.assertEqual(data['next'], {'total':'53','range':'Showing 26–50'})
        self.assertEqual(data['experimental'], {'total':'3','range':'Showing 1–3'})
        self.assertEqual(data['augmentation'], {'total':'25','range':'Showing 1–25'})
        self.assertEqual(data['taxonomyResult'], {'total':'50','range':'Showing 1–25'})
        self.assertEqual(data['searchResult'], {'total':'1','range':'Showing 1–1'})
        self.assertEqual(data['noMatches'], {'total':'0','range':'Showing 0–0'})

if __name__ == '__main__':
    unittest.main()
