"""Check that genome filters act on one source record at a time."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
function control(value = '') {
  return { value, options: [{value:''},{value:'A'},{value:'B'},{value:'Term-seq'},{value:'Rend-seq'},{value:'yes'},{value:'no'}], listeners:{}, addEventListener(type, fn){this.listeners[type]=fn;}, fire(type){this.listeners[type]?.({preventDefault(){}});} };
}
function source(study, assay, signal, search) { return {dataset:{study,assay,signal,evidence:'author_called_endpoint',search}}; }
function row(accession, organism, endpoints, sources) {
  return {dataset:{genomeSearch:`${accession} ${organism}`.toLowerCase(),sortAccession:accession,sortOrganism:organism,sortStudies:'1',sortEndpoints:String(endpoints),sortSignal:sources.some(s=>s.dataset.signal==='yes')?'1':'0'},hidden:false,querySelectorAll(){return sources;}};
}
const rows=[
  row('GCF_A','Alpha',100,[source('A','Term-seq','no','study a'),source('B','Rend-seq','yes','study b')]),
  row('GCF_B','Beta',300,[source('A','Term-seq','yes','study a')]),
  row('GCF_C','Gamma',200,[source('B','Term-seq','yes','study b')]),
];
const search=control();const study=control();const assay=control();const evidence=control();const signal=control();
const sortSelect=control('accession');const direction=control();const clear=control();const form=control();
const count={textContent:''};const empty={hidden:true};const tbody={children:[],querySelectorAll(){return rows;},append(item){this.children=this.children.filter(x=>x!==item);this.children.push(item);}};
const headings={};const buttons=['accession','organism','studies','endpoints','signal'].map(value=>({dataset:{sort:value},listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},click(){this.listeners.click();},closest(){return headings[value]??={setAttribute(key,v){this[key]=v;}};}}));
const elements={'[data-genome-search-form]':form,'[data-genome-search]':search,'[data-genome-results]':tbody,'[data-visible-count]':count,'[data-empty]':empty,'[data-clear-filters]':clear,'[data-filter-study]':study,'[data-filter-assay]':assay,'[data-filter-evidence]':evidence,'[data-filter-signal]':signal,'[data-sort-select]':sortSelect,'[data-sort-direction]':direction};
global.document={querySelector(key){return elements[key]??null;},querySelectorAll(key){return key==='[data-sort]'?buttons:[];}};
const listeners={};let href='https://bted.example/index.html?study=A&assay=Term-seq&signal=yes';
global.window={location:{get href(){return href;},get search(){return new URL(href).search;}},history:{replaceState(_s,_t,url){href=String(url);}},addEventListener(type,fn){listeners[type]=fn;}};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const initial={visible:rows.filter(r=>!r.hidden).map(r=>r.dataset.sortAccession),count:count.textContent,study:study.value,assay:assay.value,signal:signal.value};
clear.fire('click');
const cleared={visible:rows.filter(r=>!r.hidden).length,href};
buttons.find(b=>b.dataset.sort==='endpoints').click();
buttons.find(b=>b.dataset.sort==='endpoints').click();
const sorted=tbody.children.map(r=>r.dataset.sortAccession);
search.value='GCF_B';search.fire('input');
const searched={visible:rows.filter(r=>!r.hidden).map(r=>r.dataset.sortAccession),href};
search.value='study Alpha';search.fire('input');
const multiword=rows.filter(r=>!r.hidden).map(r=>r.dataset.sortAccession);
study.value='A';assay.value='Rend-seq';search.fire('input');
const inconsistent=rows.filter(r=>!r.hidden).length;
process.stdout.write(JSON.stringify({initial,cleared,sorted,searched,multiword,inconsistent}));
"""


class GenomeFiltersTests(unittest.TestCase):
    def test_same_source_filter_sort_and_url_state(self) -> None:
        result = subprocess.run(
            ["node", "-e", HARNESS, str(ROOT / "site/assets/genome-index.js")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["initial"], {
            "visible": ["GCF_B"], "count": "1", "study": "A", "assay": "Term-seq", "signal": "yes",
        })
        self.assertEqual(data["cleared"]["visible"], 3)
        self.assertNotIn("study=", data["cleared"]["href"])
        self.assertEqual(data["sorted"], ["GCF_B", "GCF_C", "GCF_A"])
        self.assertEqual(data["searched"]["visible"], ["GCF_B"])
        self.assertIn("q=GCF_B", data["searched"]["href"])
        self.assertEqual(data["multiword"], ["GCF_A"])
        self.assertEqual(data["inconsistent"], 0)


if __name__ == "__main__":
    unittest.main()
