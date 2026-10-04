"""Check genome search, cascading taxonomy, pagination and shared URLs."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const fs=require('fs'), vm=require('vm');
function control(value='') {return {value,options:[{value:''}],listeners:{},children:[],dataset:{},textContent:'',
  addEventListener(type,fn){this.listeners[type]=fn;},fire(type){this.listeners[type]?.({preventDefault(){}});},
  append(...nodes){this.children.push(...nodes);this.options.push(...nodes);},replaceChildren(...nodes){this.children=[...nodes];this.options=[...nodes];}};}
const source=(study,assay,search,published='yes')=>({dataset:{study,assay,search,published}});
function row(id,name,endpoints,phylum,cl,order,family,genus,sources){return {dataset:{genomeSearch:`${id} ${name}`.toLowerCase(),sortAccession:id,sortOrganism:name,sortStudies:'1',sortEndpoints:String(endpoints),sortSignal:'0',taxonomyPhylum:phylum,taxonomyClass:cl,taxonomyOrder:order,taxonomyFamily:family,taxonomyGenus:genus},querySelectorAll(){return sources;},cells:{},querySelector(key){return this.cells[key]??=control();}};}
const rows=[row('GCF_A','Alpha',100,'P1','C1','O1','F1','Alpha',[source('A','Term-seq','study a')]),
row('GCF_B','Beta',300,'P1','C2','O2','F2','Beta',[source('A','Term-seq','study a'),source('AUDIT','Review only','audit','no')]),
row('GCF_C','Gamma',200,'P2','C3','O3','F3','Gamma',[source('B','Rend-seq','study b')])];
const search=control(),clear=control(),form=control(),count=control(),empty=control(),sortSelect=control(),direction=control();
const taxonomy=['phylum','class','order','family','genus'].map(rank=>{const select=control();select.dataset.taxonomyRank=rank;return select;});
const tbody={children:[],querySelectorAll(){return rows;},append(node){this.children=this.children.filter(n=>n!==node);this.children.push(node);},replaceChildren(){this.children=[];}};
const buttons=['accession','organism','studies','endpoints','signal'].map(value=>({dataset:{sort:value},listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},click(){this.listeners.click();},closest(){return {setAttribute(){}};}}));
const elements={'[data-genome-search-form]':form,'[data-genome-search]':search,'[data-genome-results]':tbody,'[data-visible-count]':count,'[data-empty]':empty,'[data-clear-filters]':clear,'[data-sort-select]':sortSelect,'[data-sort-direction]':direction};
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
const initial={visible:visible(),classes:taxonomy[1].options.map(o=>o.value)};
choose('class','C2');const narrowed={visible:visible(),orders:taxonomy[2].options.map(o=>o.value),href};
choose('order','O2');buttons.find(b=>b.dataset.sort==='endpoints').click();buttons.find(b=>b.dataset.sort==='endpoints').click();
const shared=href;listeners.popstate();const restored={visible:visible(),order:taxonomy[2].value,direction:direction.textContent};
choose('phylum','P2');const switched={visible:visible(),children:taxonomy.slice(1).map(s=>s.value)};
clear.fire('click');const cleared={visible:visible(),href};
choose('genus','Beta');const directGenus=visible();clear.fire('click');
buttons.find(b=>b.dataset.sort==='endpoints').click();buttons.find(b=>b.dataset.sort==='endpoints').click();const sorted=tbody.children.map(r=>r.dataset.sortAccession);
search.value='study Alpha';search.fire('input');const multiword=visible();
search.value='no match';search.fire('input');const noMatch={count:count.textContent,empty:empty.hidden};
process.stdout.write(JSON.stringify({initial,narrowed,shared,restored,switched,cleared,directGenus,sorted,multiword,noMatch}));
''')
        self.assertEqual(data['initial'], {'visible':['GCF_A','GCF_B'],'classes':['','C1','C2']})
        self.assertEqual(data['narrowed']['visible'], ['GCF_B'])
        self.assertEqual(data['narrowed']['orders'], ['', 'O2'])
        self.assertNotIn('study=', data['narrowed']['href'])
        self.assertNotIn('assay=', data['narrowed']['href'])
        self.assertIn('order=O2', data['shared'])
        self.assertIn('direction=desc', data['shared'])
        self.assertEqual(data['restored'], {'visible':['GCF_B'],'order':'O2','direction':'Descending'})
        self.assertEqual(data['switched'], {'visible':['GCF_C'],'children':['','','','']})
        self.assertEqual(len(data['cleared']['visible']), 3)
        self.assertNotIn('phylum=', data['cleared']['href'])
        self.assertEqual(data['directGenus'], ['GCF_B'])
        self.assertEqual(data['sorted'], ['GCF_B','GCF_C','GCF_A'])
        self.assertEqual(data['multiword'], ['GCF_A'])
        self.assertEqual(data['noMatch'], {'count':'0','empty':False})

    def test_unified_catalogue_deduplicates_counts_and_retries(self):
        data = self.run_js(r'''
href='https://bted.example/genomes.html?q=GCF_B';
const dataset=control();dataset.options=['','experimental','prediction','augmentation'].map(value=>({value}));
Object.assign(elements,{'[data-genome-dataset]':dataset,'[data-genome-prev]':control(),'[data-genome-next]':control(),'[data-genome-page-number]':control(),'[data-genome-load-status]':control(),'[data-genome-retry]':control(),'[data-total-count]':control()});
global.fetch=async()=>({ok:true,json:async()=>({genomes:[
['GCF_B','000','OTU-1','Beta','isolate',5,5,1,1,'matched',12,'d__Bacteria;p__P1;c__C2;o__O2;f__F2;g__Beta'],
['GCF_Z','000','OTU-2','Zeta','MAG',9,9,0,0,'unavailable',20,'d__Bacteria;p__P3;c__C4;o__O4;f__F4;g__Zeta'],
['GCF_W','000','OTU-3','Empty','MAG',0,0,0,0,'unavailable',0,''],
]})});run();
setImmediate(()=>{
  const states=[];for(const value of ['experimental','prediction','augmentation','']){dataset.value=value;dataset.fire('change');states.push({count:count.textContent,nodes:tbody.children.length,duplicate:tbody.children.filter(r=>r===rows[1]).length});}
  const mixed={studies:rows[1].cells['[data-label="Studies"]'].textContent,methods:rows[1].cells['[data-label="Methods"]'].textContent};
  search.value='';search.fire('input');choose('phylum','P3');choose('class','C4');choose('order','O4');choose('family','F4');choose('genus','Zeta');
  const synthetic={count:count.textContent,nodes:tbody.children.length,studies:tbody.children[0].children[3].textContent,methods:tbody.children[0].children[4].textContent};
  clear.fire('click');search.value='GCF_W';search.fire('input');const noFeatures=count.textContent;
  elements['[data-genome-retry]'].fire('click');
  setImmediate(()=>process.stdout.write(JSON.stringify({total:elements['[data-total-count]'].textContent,states,mixed,synthetic,noFeatures,retriedStudies:rows[1].dataset.sortStudies,status:elements['[data-genome-load-status]'].textContent})));
});
''')
        self.assertEqual(data['total'], '5')
        self.assertTrue(all(s == {'count':'1','nodes':1,'duplicate':1} for s in data['states']))
        self.assertEqual(data['mixed'], {'studies':'2','methods':'BATTER-TPE \u00b7 Term-seq \u00b7 Training augmentation'})
        self.assertEqual(data['synthetic'], {'count':'1','nodes':1,'studies':'1','methods':'BATTER-TPE \u00b7 Training augmentation'})
        self.assertEqual(data['noFeatures'], '1')
        self.assertEqual(data['retriedStudies'], '2')
        self.assertIn('Each genome is listed once', data['status'])

if __name__ == '__main__':
    unittest.main()
