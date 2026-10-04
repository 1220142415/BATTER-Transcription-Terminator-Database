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
const search=control(),clear=control(),form=control(),count=control(),empty=control(),sortSelect=control(),direction=control();
const taxonomy=['phylum','class','order','family','genus'].map(rank=>{const select=control();select.dataset.taxonomyRank=rank;return select;});
const tbody={children:[],querySelectorAll(){return rows;},append(node){this.children=this.children.filter(n=>n!==node);this.children.push(node);},replaceChildren(){this.children=[];}};
const buttons=['accession','organism','size','endpoints','predictions','training'].map(value=>({dataset:{sort:value},listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},click(){this.listeners.click();},closest(){return {setAttribute(){}};}}));
const elements={'[data-genome-search-form]':form,'[data-genome-search]':search,'[data-genome-results]':tbody,'[data-visible-count]':count,'[data-result-range]':control(),'[data-empty]':empty,'[data-clear-filters]':clear,'[data-sort-select]':sortSelect,'[data-sort-direction]':direction};
global.document={createElement:()=>control(),querySelector:key=>elements[key]??null,querySelectorAll:key=>key==='[data-sort]'?buttons:key==='[data-taxonomy-rank]'?taxonomy:[]};
let href='https://bted.example/genomes.html?taxon=phylum:P1&study=unused&assay=unused';const listeners={};
global.window={location:{get href(){return href;},get search(){return new URL(href).search;}},history:{replaceState(_s,_t,url){href=String(url);}},addEventListener(type,fn){listeners[type]=fn;}};
const visible=()=>rows.filter(row=>!row.hidden).map(row=>row.dataset.sortAccession);
const choose=(rank,value)=>{const select=taxonomy.find(s=>s.dataset.taxonomyRank===rank);select.value=value;select.fire('change');};
const run=()=>vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
"""

class GenomeFiltersTests(unittest.TestCase):
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
const shared=href;listeners.popstate();const restored={visible:visible(),order:taxonomy[2].value,direction:direction.textContent};
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
        self.assertIn('direction=desc', data['shared'])
        self.assertEqual(data['restored'], {'visible':['GCF_B'],'order':'O2','direction':'Descending'})
        self.assertEqual(data['switched'], {'visible':['GCF_C'],'children':['','','','']})
        self.assertEqual(len(data['cleared']['visible']), 3)
        self.assertEqual(data['cleared']['disabled'], [False,True,True,True,True])
        self.assertNotIn('phylum=', data['cleared']['href'])
        self.assertEqual(data['blockedGenus'], {'visible':['GCF_A','GCF_B','GCF_C'],'selected':''})
        self.assertEqual(data['sorted'], ['GCF_B','GCF_C','GCF_A'])
        self.assertEqual(data['multiword'], ['GCF_A'])
        self.assertEqual(data['noMatch'], {'count':'0','empty':False})

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
        self.assertEqual(data['synthetic'], {'count':'1','nodes':1,'columns':['Genome ID','Genome source','Organism','Taxonomy','Assembly size','Terminator data','Annotation'],'assembly':'GCF_Z','href':'genomes/GCF_Z','otu':'GEM OTU: OTU-2','source':'IMG','size':['20,000 bp','1 contig'],'counts':['0','20','9'],'annotation':'Missing'})
        self.assertEqual(data['noFeatures'], '1')
        self.assertEqual(data['mismatchAnnotation'], 'Incompatible')
        self.assertEqual(data['fetchesAfterFiltering'], 1)
        self.assertEqual(data['catalogueFetches'], 2)
        self.assertEqual(data['predictionOrder'], ['GCF_Z','GCF_B','GCF_A','GCF_C','GCF_W'])
        self.assertEqual(data['trainingOrder'], data['predictionOrder'])
        self.assertEqual(data['sizeAscending'], ['GCF_B','GCF_Z','GCF_A','GCF_C','GCF_W'])
        self.assertEqual(data['sizeDescending'], ['GCF_Z','GCF_B','GCF_A','GCF_C','GCF_W'])
        self.assertEqual(data['retriedTraining'], '6')
        self.assertEqual(data['retriedOtuLabels'], 1)
        self.assertIn('OTU augmentation and Rfam', data['status'])

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
        self.assertIn('Experimental genomes remain available', data['recovered']['status'])

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
